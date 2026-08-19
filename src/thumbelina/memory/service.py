"""记忆存储服务(见设计文档 §8)。

核心约定:
  - **原子写 + fsync(best-effort)**:复用公共 :mod:`thumbelina.filestore`
    "临时文件 + ``os.replace``"范式;临时文件失败时 ``unlink(missing_ok=True)``。
  - **按文件 + 固定索引锁**:单文件读写走对应 ``<category>/<slug>.md``
    的锁;扫描目录 / 重建 ``index.md`` 的复合操作走 ``index.md`` 的
    固定锁,并用公共锁表 :class:`FileLocks` 按稳定顺序同时占用"条目
    锁 + 索引锁"(先数据、后索引,顺序固定)。
  - **残留清理**:启动时 ``init()`` 清理 ``*.tmp``。
  - **不缓存**:每次重读磁盘(对齐 ``todo/service.py``),手工编辑即时可见。
  - ``user_id`` 参数签名预留(默认 ``"default"``,本期忽略)。
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from thumbelina.filestore import (
    FileLocks,
    cleanup_tmp,
    ensure_dir,
    read_text,
    safe_unlink,
    write_text_atomic,
)
from thumbelina.memory.exceptions import MemoryEntryNotFoundError, MemoryServiceError
from thumbelina.memory.models import MemoryEntry, MemoryIndex
from thumbelina.memory.parser import (
    build_index,
    parse_overview_only,
    scan_entries,
)
from thumbelina.memory.paths import _resolve, resolve_index
from thumbelina.rag.retrieval.context_formatter import estimate_tokens

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "default"
_INDEX_UPDATED_RE = re.compile(r"更新\s*[:：]\s*(\S+)")


class MemoryService:
    """基于 Markdown 文件系统的分层记忆存储服务。

    所有读写经 :func:`thumbelina.memory.paths._resolve` 校验;
    ``index.md`` 固定为 ``base / "index.md"``,永不从用户输入派生。

    Parameters
    ----------
    directory:
        记忆目录(相对路径基于工作目录)。
    categories:
        分类白名单(索引按此顺序分组,白名单外分类被忽略)。
    max_full_tokens:
        ``read_full`` 单条全文注入上限,超限截断并附"…(已截断,共 N 字符)"。
    max_entries:
        记忆条目总量护栏(写操作前检查,超限抛 ``MemoryServiceError``)。
    max_total_bytes:
        记忆目录总字节护栏。
    """

    def __init__(
        self,
        directory: str | Path,
        categories: list[str] | None = None,
        *,
        max_full_tokens: int = 4000,
        max_entries: int = 200,
        max_total_bytes: int = 5_000_000,
    ) -> None:
        self._base = Path(directory)
        if categories:
            self._categories = list(categories)
        else:
            self._categories = ["user", "project", "decision", "topic"]
        self._max_full_tokens = max_full_tokens
        self._max_entries = max_entries
        self._max_total_bytes = max_total_bytes
        self._locks = FileLocks()

    @property
    def _index_path(self) -> Path:
        """固定的 ``index.md`` 路径,兼作"扫描/重建索引"域的锁 key。"""
        return resolve_index(self._base)

    async def init(self) -> None:
        """创建记忆目录(含父级)并清理 ``*.tmp`` 残留。不触碰其它文件。"""
        await asyncio.to_thread(ensure_dir, self._base)
        await asyncio.to_thread(cleanup_tmp, self._base)

    # ------------------------------------------------------------------
    # 读路径
    # ------------------------------------------------------------------

    async def load_index(self, *, user_id: str = DEFAULT_USER_ID) -> MemoryIndex:
        """L0:加载 ``index.md`` 全部摘要,返回 :class:`MemoryIndex`。

        实际从磁盘扫描各分类目录重建条目列表(索引为派生产物,
        真相源是各记忆文档);``updated`` 取索引头部声明的时间。
        """
        del user_id  # 本期忽略,签名预留
        async with self._locks.locked(self._index_path):
            entries = await asyncio.to_thread(scan_entries, self._base, self._categories)
            updated = await asyncio.to_thread(self._read_index_updated)
            return MemoryIndex(entries=entries, updated=updated)

    async def load_index_text(self, *, user_id: str = DEFAULT_USER_ID) -> str:
        """L0:返回 ``index.md`` 全文(供 Agent 注入或 token 估算)。"""
        del user_id
        async with self._locks.locked(self._index_path):
            entries = await asyncio.to_thread(scan_entries, self._base, self._categories)
            return await asyncio.to_thread(build_index, entries, self._categories)

    async def read_overview(
        self,
        category: str,
        slug: str,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> MemoryEntry:
        """L1:读取记忆文档概览区间(止于 ``## 全文``),``full_text`` 置空。"""
        del user_id
        path = await asyncio.to_thread(_resolve, self._base, category, slug)
        async with self._locks.locked(path):
            text = await asyncio.to_thread(self._read_text, path)
            entry = parse_overview_only(text)
            if entry is None:
                raise MemoryEntryNotFoundError(f"记忆条目不存在: {category}/{slug}")
            entry.slug = slug
            return entry

    async def read_full(
        self,
        category: str,
        slug: str,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> MemoryEntry:
        """L2:读取记忆文档全文(受 ``max_full_tokens`` 截断)。

        读前 ``os.stat`` 检查大小,超限时截断并附"…(已截断,共 N 字符)"。
        """
        del user_id
        path = await asyncio.to_thread(_resolve, self._base, category, slug)
        async with self._locks.locked(path):
            text = await asyncio.to_thread(self._read_text_with_stat, path)
            if text is None:
                raise MemoryEntryNotFoundError(f"记忆条目不存在: {category}/{slug}")
            entry = await asyncio.to_thread(parse_overview_only, text)
            if entry is None:
                raise MemoryEntryNotFoundError(f"记忆条目解析失败: {category}/{slug}")
            entry.slug = slug
            # 读取全文区间(止于文件末尾)
            full = await asyncio.to_thread(self._extract_full, text)
            entry.full_text = self._truncate_full(full)
            return entry

    async def list_entries(self, *, user_id: str = DEFAULT_USER_ID) -> list[MemoryEntry]:
        """列出白名单分类内的全部条目(跳过白名单外分类)。"""
        del user_id
        async with self._locks.locked(self._index_path):
            return await asyncio.to_thread(scan_entries, self._base, self._categories)

    async def get_entry(
        self,
        category: str,
        slug: str,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> MemoryEntry:
        """读取单条记忆的完整内容(概览 + 全文,受 ``max_full_tokens`` 截断)。"""
        return await self.read_full(category, slug, user_id=user_id)

    # ------------------------------------------------------------------
    # 写路径
    # ------------------------------------------------------------------

    async def update_memory(
        self,
        entry: MemoryEntry,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> MemoryEntry:
        """写入/更新一条记忆(NEW/UPDATE 同路径,slug 冲突即同义改写覆盖)。

        先原子写 ``<category>/<slug>.md``,再在同一临界区内重建并
        原子写 ``index.md``,顺序固定。护栏检查在写之前。
        """
        del user_id
        path = await asyncio.to_thread(_resolve, self._base, entry.category, entry.slug)
        async with self._locks.locked(path, self._index_path):
            await asyncio.to_thread(self._check_guardrails, entry)
            text = self._serialize_entry(entry)
            await asyncio.to_thread(write_text_atomic, path, text)
            await asyncio.to_thread(self._rebuild_index)
            return entry

    async def delete_memory(
        self,
        category: str,
        slug: str,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> None:
        """删除一条记忆并重建索引。条目不存在时静默成功(idempotent)。"""
        del user_id
        path = await asyncio.to_thread(_resolve, self._base, category, slug)
        async with self._locks.locked(path, self._index_path):
            await asyncio.to_thread(safe_unlink, path)
            await asyncio.to_thread(self._rebuild_index)

    async def export_all(self, *, user_id: str = DEFAULT_USER_ID) -> dict[str, object]:
        """全量条目序列化(供数据导出/备份接入)。

        返回 ``{"entries": [entry_dict, ...], "index": index_text}``。
        """
        del user_id
        async with self._locks.locked(self._index_path):
            entries = await asyncio.to_thread(scan_entries, self._base, self._categories)
            index_text = await asyncio.to_thread(build_index, entries, self._categories)
            return {
                "entries": [self._entry_to_dict(e) for e in entries],
                "index": index_text,
            }

    async def clear_all(self, *, user_id: str = DEFAULT_USER_ID) -> None:
        """清空全部记忆条目并重建空 ``index.md``。

        删除白名单分类目录下所有 ``.md`` 文件,然后重建空索引。
        不删除目录本身与 ``index.md`` 之外的其它文件。
        """
        del user_id
        async with self._locks.locked(self._index_path):
            await asyncio.to_thread(self._clear_entries)
            await asyncio.to_thread(self._rebuild_index)

    # ------------------------------------------------------------------
    # internals: 序列化
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_entry(entry: MemoryEntry) -> str:
        """把 :class:`MemoryEntry` 序列化为记忆文档全文(§5.2 格式)。"""
        meta_parts: list[str] = [f"分类:{entry.category}"]
        if entry.updated:
            meta_parts.append(f"更新:{entry.updated}")
        if entry.source:
            meta_parts.append(f"来源:{entry.source}")
        if entry.summary:
            meta_parts.append(f"摘要:{entry.summary}")
        meta_line = " · ".join(meta_parts)
        overview = entry.overview.rstrip("\n")
        full = entry.full_text.rstrip("\n")
        parts = [
            f"# {entry.title}",
            "",
            f"> {meta_line}",
            "",
            "## 概览",
            "",
            overview,
            "",
            "## 全文",
            "",
            full,
            "",
        ]
        return "\n".join(parts)

    @staticmethod
    def _entry_to_dict(entry: MemoryEntry) -> dict[str, str]:
        return {
            "title": entry.title,
            "category": entry.category,
            "slug": entry.slug,
            "summary": entry.summary,
            "updated": entry.updated,
            "source": entry.source,
            "overview": entry.overview,
            "full_text": entry.full_text,
            "relpath": entry.relpath,
        }

    # ------------------------------------------------------------------
    # internals: 索引重建
    # ------------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """扫描条目并原子写 ``index.md``(在同一临界区内调用)。"""
        entries = scan_entries(self._base, self._categories)
        text = build_index(entries, self._categories)
        index_path = resolve_index(self._base)
        write_text_atomic(index_path, text)

    def _read_index_updated(self) -> str:
        """读取 ``index.md`` 头部声明的更新时间(解析 ``> 更新:xxx``)。"""
        text = read_text(self._index_path)
        for line in text.splitlines():
            if line.startswith(">"):
                # 形如 "> 更新:2026-08-16"
                m = _INDEX_UPDATED_RE.search(line)
                if m:
                    return m.group(1).strip()
        return ""

    # ------------------------------------------------------------------
    # internals: 读写底层
    # ------------------------------------------------------------------

    def _read_text(self, path: Path) -> str:
        return read_text(path)

    def _read_text_with_stat(self, path: Path) -> str | None:
        """读前 ``os.stat`` 检查大小,文件不存在返回 ``None``。"""
        try:
            path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("记忆文档 stat 失败: %s (%s)", path, exc)
            return None
        return read_text(path)

    def _extract_full(self, text: str) -> str:
        """提取 ``## 全文`` 区间内容(到文件末尾)。"""
        lines = text.splitlines()
        in_full = False
        full_lines: list[str] = []
        for line in lines:
            if line.strip() == "## 全文":
                in_full = True
                continue
            if in_full:
                full_lines.append(line)
        # 去除首尾空行
        while full_lines and not full_lines[0].strip():
            full_lines.pop(0)
        while full_lines and not full_lines[-1].strip():
            full_lines.pop()
        return "\n".join(full_lines)

    def _truncate_full(self, full_text: str) -> str:
        """按 ``max_full_tokens`` 截断全文(用 ``estimate_tokens`` 折算)。"""
        if not full_text:
            return ""
        if estimate_tokens(full_text) <= self._max_full_tokens:
            return full_text
        # 按比例截断字符数
        ratio = self._max_full_tokens / max(estimate_tokens(full_text), 1)
        cutoff = max(1, int(len(full_text) * ratio))
        return full_text[:cutoff].rstrip() + f"\n\n…(已截断,共 {len(full_text)} 字符)"

    def _clear_entries(self) -> None:
        """删除白名单分类目录下所有 ``.md`` 文件(不删目录)。"""
        cat_set = set(self._categories)
        if not self._base.is_dir():
            return
        for child in self._base.iterdir():
            if not child.is_dir() or child.name not in cat_set:
                continue
            for md_path in child.glob("*.md"):
                safe_unlink(md_path)

    # ------------------------------------------------------------------
    # internals: 护栏
    # ------------------------------------------------------------------

    def _check_guardrails(self, entry: MemoryEntry) -> None:
        """写前护栏:条目总量、单文件大小、目录总字节(见 §8.6)。"""
        if entry.category not in self._categories:
            raise MemoryServiceError(f"分类不在白名单: {entry.category}")
        existing = scan_entries(self._base, self._categories)
        is_new = not any(e.category == entry.category and e.slug == entry.slug for e in existing)
        if is_new and len(existing) >= self._max_entries:
            raise MemoryServiceError(f"记忆条目总量超限({self._max_entries})")
        # 目录总字节(不含本次新写)
        total = self._total_bytes()
        if total >= self._max_total_bytes:
            raise MemoryServiceError(f"记忆目录总字节超限({self._max_total_bytes})")

    def _total_bytes(self) -> int:
        """统计记忆目录下所有 ``.md`` 文件总字节(含 index.md)。"""
        if not self._base.is_dir():
            return 0
        total = 0
        for p in self._base.rglob("*.md"):
            try:
                total += p.stat().st_size
            except OSError:
                continue
        return total
