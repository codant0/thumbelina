"""Markdown 记忆文档解析与索引生成(见设计文档 §5)。

解析约定(§5.2 机器可读元数据):
  - 第一行 ``# 标题`` 为文档标题(含分类前缀便于索引阅读)。
  - 紧随的 ``>`` 引用行携带元数据,以 ``·`` 分隔,支持
    ``分类``/``更新``/``来源``/``摘要`` 四个键(中文键名)。
  - ``## 概览`` 与 ``## 全文`` 为两个区间节标题;概览读取止于
    ``## 全文`` 之前(行受限读),全文区间读到文件末尾。
  - 读取统一 ``encoding="utf-8", errors="replace"``;
    ``UnicodeDecodeError`` 记 warning 按空/跳过降级;显式跳过 ``.tmp``。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from thumbelina.memory.models import MemoryEntry
from thumbelina.memory.paths import INDEX_FILENAME, TMP_SUFFIX

logger = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
_META_LINE_RE = re.compile(r"^>\s*(.+?)\s*$")
_OVERVIEW_HEADER = "## 概览"
_FULL_HEADER = "## 全文"
_META_KV_RE = re.compile(r"(分类|更新|来源|摘要)\s*[:：]\s*(.+?)(?=\s*[·]\s*|$)")


def parse_document(text: str) -> MemoryEntry | None:
    """解析单篇记忆文档文本为 :class:`MemoryEntry`。

    缺少标题或元数据关键字段时返回 ``None``(视为非记忆文档,跳过)。
    概览缺失时为空串;全文缺失时为空串。元数据键名固定为中文
    ``分类``/``更新``/``来源``/``摘要``。
    """
    if not text:
        return None
    lines = text.splitlines()
    title = ""
    meta: dict[str, str] = {}
    overview_lines: list[str] = []
    full_lines: list[str] = []
    section: str | None = None  # None=前导, "overview", "full"

    for line in lines:
        if section is None:
            m_title = _TITLE_RE.match(line)
            if m_title and not title:
                title = m_title.group(1).strip()
                continue
            m_meta = _META_LINE_RE.match(line)
            if m_meta:
                _parse_meta_line(m_meta.group(1), meta)
                continue
            if line.strip() == _OVERVIEW_HEADER:
                section = "overview"
                continue
            if line.strip() == _FULL_HEADER:
                section = "full"
                continue
            # 前导其它行忽略
            continue
        if section == "overview":
            if line.strip() == _FULL_HEADER:
                section = "full"
                continue
            overview_lines.append(line)
        elif section == "full":
            full_lines.append(line)

    overview = _strip_trailing_blank(overview_lines)
    full_text = _strip_trailing_blank(full_lines)

    category = meta.get("分类", "")
    summary = meta.get("摘要", "")
    updated = meta.get("更新", "")
    source = meta.get("来源", "")

    if not title or not category:
        return None
    # slug 由调用方(服务层)从文件名派生,解析阶段置空待补
    slug = ""

    return MemoryEntry(
        title=title,
        category=category,
        slug=slug,
        summary=summary,
        updated=updated,
        overview=overview,
        full_text=full_text,
        source=source,
    )


def parse_overview_only(text: str) -> MemoryEntry | None:
    """行受限解析:只读到 ``## 全文`` 之前,``full_text`` 置空。

    供 :meth:`MemoryService.read_overview` 使用,大全文时省 token。
    """
    entry = parse_document(text)
    if entry is None:
        return None
    entry.full_text = ""
    return entry


def _parse_meta_line(content: str, meta: dict[str, str]) -> None:
    """解析 ``分类:xxx · 更新:yyy · 来源:zzz · 摘要:aaa`` 形态的元数据行。"""
    # 支持 · 或 | 或纯空白分隔;统一先按 · 拆分
    parts = re.split(r"\s*[·|]\s*", content)
    for part in parts:
        m = _META_KV_RE.match(part)
        if m:
            meta[m.group(1)] = m.group(2).strip()


def _strip_trailing_blank(lines: list[str]) -> str:
    """拼接行并去除尾部空行/尾部空白。"""
    kept = list(lines)
    while kept and not kept[-1].strip():
        kept.pop()
    # 去除头部空行
    while kept and not kept[0].strip():
        kept.pop(0)
    return "\n".join(kept)


def read_entry_file(path: Path) -> MemoryEntry | None:
    """读取并解析单个记忆文档文件,注入 slug(从文件名派生)。

    非 ``.md``、``.tmp`` 文件跳过;``UnicodeDecodeError`` 记 warning
    按空返回 ``None``(单文件坏不拖垮整个索引)。
    """
    if path.suffix != ".md" or path.name.endswith(TMP_SUFFIX):
        return None
    if path.name == INDEX_FILENAME:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("记忆文档读取失败,跳过: %s (%s)", path, exc)
        return None
    entry = parse_document(text)
    if entry is None:
        return None
    # slug 从文件名派生(不含 .md)
    entry.slug = path.stem
    return entry


def scan_entries(base: Path, categories: list[str]) -> list[MemoryEntry]:
    """扫描记忆目录,返回分类白名单内的全部条目。

    白名单外分类目录被忽略(保证分组语义稳定);``.tmp`` 与
    ``index.md`` 被跳过。条目顺序按分类白名单顺序,同类内按
    ``updated`` 降序(空值靠后),再按 slug 升序(确定性)。
    """
    cat_set = set(categories)
    entries: list[MemoryEntry] = []
    if not base.is_dir():
        return entries
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if child.name not in cat_set:
            continue
        for md_path in child.glob("*.md"):
            entry = read_entry_file(md_path)
            if entry is not None:
                entries.append(entry)
    return _sort_entries(entries, categories)


def _sort_entries(entries: list[MemoryEntry], categories: list[str]) -> list[MemoryEntry]:
    """按分类白名单顺序分组,同类内按 updated 降序、slug 升序。"""
    # updated 降序需单独处理:先按 slug 升序,再在同类内按 updated 降序(稳定排序)
    by_cat: dict[str, list[MemoryEntry]] = {}
    for e in entries:
        by_cat.setdefault(e.category, []).append(e)
    out: list[MemoryEntry] = []
    for cat in categories:
        items = by_cat.get(cat, [])
        items.sort(key=lambda e: e.slug)
        items.sort(key=lambda e: e.updated, reverse=True)
        out.extend(items)
    return out


def build_index(entries: list[MemoryEntry], categories: list[str]) -> str:
    """生成 ``index.md`` 全文(见设计文档 §5.1)。

    格式:头部标题 + 自动生成声明 + 更新日期;按分类白名单顺序分组,
    每个分类一个 ``## <分类中文名>`` 节,每条目一行
    ``[标题](相对链接) — 摘要``。无条目的分类省略。
    """
    today = date.today().isoformat()
    header = f"# 记忆索引\n\n> 本文件由 MemoryService 自动生成,请勿手工编辑。\n> 更新:{today}\n"
    sections: list[str] = []
    by_cat: dict[str, list[MemoryEntry]] = {}
    for e in entries:
        by_cat.setdefault(e.category, []).append(e)
    for cat in categories:
        items = by_cat.get(cat, [])
        if not items:
            continue
        items.sort(key=lambda e: e.slug)
        items.sort(key=lambda e: e.updated, reverse=True)
        cat_title = _CATEGORY_LABELS.get(cat, cat)
        lines = [f"## {cat_title}\n"]
        for e in items:
            summary = e.summary.strip() or "(无摘要)"
            lines.append(f"- [{e.title}]({e.relpath}) — {summary}")
        sections.append("\n".join(lines))
    body = "\n\n".join(sections)
    if body:
        return header + "\n" + body + "\n"
    return header + "\n"


# 分类白名单 -> 索引展示用的中文标签(与设计文档 §5.1 示例一致)
_CATEGORY_LABELS: dict[str, str] = {
    "user": "用户",
    "project": "项目",
    "decision": "决策",
    "topic": "主题",
}
