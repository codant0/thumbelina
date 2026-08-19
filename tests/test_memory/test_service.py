"""MemoryService 存储服务测试(设计文档 §8、§13 任务 14)。

覆盖:增删改查往返、原子写(无 ``.tmp`` 残留)、并发(多协程同时写不同
slug,最终文件完整、索引一致)、手工编辑感知、init() 清理残留 ``.tmp``、
export_all/clear_all、护栏(max_entries 超限/分类白名单外)。
全部用 ``tmp_path`` + 真 :class:`MemoryService`,无网络/LLM。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thumbelina.memory.exceptions import MemoryEntryNotFoundError, MemoryServiceError
from thumbelina.memory.models import MemoryEntry
from thumbelina.memory.service import MemoryService

_CATEGORIES = ["user", "project", "decision", "topic"]


def _entry(
    *,
    title: str = "用户:编程偏好",
    category: str = "user",
    slug: str = "programming-preference",
    summary: str = "偏好 Python、类型注解。",
    overview: str = "偏好 Python 3.11+。",
    full_text: str = "- 2026-08-10:偏好 Python。",
    updated: str = "2026-08-16",
    source: str = "对话 2026-08-10",
) -> MemoryEntry:
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


async def _make_service(
    tmp_path: Path,
    *,
    categories: list[str] | None = None,
    max_full_tokens: int = 4000,
    max_entries: int = 200,
    max_total_bytes: int = 5_000_000,
) -> MemoryService:
    svc = MemoryService(
        tmp_path / "MEMORY",
        categories=categories or _CATEGORIES,
        max_full_tokens=max_full_tokens,
        max_entries=max_entries,
        max_total_bytes=max_total_bytes,
    )
    await svc.init()
    return svc


class TestCRUD:
    """增删改查往返。"""

    async def test_update_and_read_full_roundtrip(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        entry = _entry()
        await svc.update_memory(entry)
        got = await svc.read_full("user", "programming-preference")
        assert got.title == entry.title
        assert got.category == "user"
        assert got.slug == "programming-preference"
        assert got.summary == entry.summary
        assert "偏好 Python 3.11+" in got.overview
        assert "2026-08-10" in got.full_text

    async def test_read_overview_full_text_empty(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry())
        got = await svc.read_overview("user", "programming-preference")
        assert got.full_text == ""
        assert got.overview != ""

    async def test_read_full_truncates_oversized(self, tmp_path: Path) -> None:
        # 构造超过 max_full_tokens 的全文
        big_full = "- " + "内容详细条目。\n" * 2000  # CJK 文本,token 估算较大
        svc = await _make_service(tmp_path, max_full_tokens=200)
        await svc.update_memory(_entry(full_text=big_full, overview="概览"))
        got = await svc.read_full("user", "programming-preference")
        assert "已截断" in got.full_text

    async def test_delete_idempotent(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry())
        # 删除已存在条目
        await svc.delete_memory("user", "programming-preference")
        # 再次删除不抛(idempotent)
        await svc.delete_memory("user", "programming-preference")
        with pytest.raises(MemoryEntryNotFoundError):
            await svc.read_full("user", "programming-preference")

    async def test_read_nonexistent_raises(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        with pytest.raises(MemoryEntryNotFoundError):
            await svc.read_full("user", "nope")
        with pytest.raises(MemoryEntryNotFoundError):
            await svc.read_overview("user", "nope")

    async def test_update_overwrites_existing(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry(summary="旧摘要"))
        await svc.update_memory(_entry(summary="新摘要", overview="新概览"))
        got = await svc.read_full("user", "programming-preference")
        assert got.summary == "新摘要"
        assert got.overview == "新概览"


class TestAtomicWrite:
    """原子写:写后无 ``.tmp`` 残留。"""

    async def test_no_tmp_residual_after_write(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry())
        await svc.update_memory(_entry(slug="another", title="用户:另一条"))
        base = tmp_path / "MEMORY"
        tmps = list(base.rglob("*.tmp"))
        assert tmps == []


class TestConcurrency:
    """并发:多协程同时 update 不同 slug,最终文件完整、索引一致。"""

    async def test_concurrent_different_slugs_same_category(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)

        async def write_one(i: int) -> None:
            await svc.update_memory(
                _entry(
                    slug=f"slug-{i}",
                    title=f"用户:条目{i}",
                    summary=f"摘要{i}",
                    overview=f"概览{i}",
                    full_text=f"- 条目{i}全文",
                )
            )

        await asyncio.gather(*(write_one(i) for i in range(10)))

        entries = await svc.list_entries()
        assert len(entries) == 10
        # 每个条目文件存在且可读
        for i in range(10):
            got = await svc.read_full("user", f"slug-{i}")
            assert f"条目{i}" in got.title
            assert f"概览{i}" in got.overview

        # index.md 含全部条目
        index_text = await svc.load_index_text()
        for i in range(10):
            assert f"slug-{i}.md" in index_text

        # 无 .tmp 残留
        base = tmp_path / "MEMORY"
        assert list(base.rglob("*.tmp")) == []

    async def test_concurrent_different_categories(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        cats = ["user", "project", "decision", "topic"]

        async def write_one(cat: str, i: int) -> None:
            await svc.update_memory(
                _entry(
                    category=cat,
                    slug=f"{cat}-slug-{i}",
                    title=f"{cat}:条目{i}",
                    summary=f"{cat}摘要{i}",
                )
            )

        await asyncio.gather(*(write_one(cats[i % 4], i) for i in range(12)))

        entries = await svc.list_entries()
        assert len(entries) == 12
        # 索引重建一致:含所有分类
        index_text = await svc.load_index_text()
        for cat in cats:
            assert "## " in index_text  # 至少有分组


class TestManualEdit:
    """手工编辑感知:服务写后,外部改文件,再 load_index 反映新摘要。"""

    async def test_external_edit_visible_after_reload(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry(summary="旧摘要"))
        # 外部直接改文件
        path = tmp_path / "MEMORY" / "user" / "programming-preference.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("旧摘要", "手工改的摘要")
        path.write_text(text, encoding="utf-8")
        # load_index 重新扫描磁盘
        index = await svc.load_index()
        match = [e for e in index.entries if e.slug == "programming-preference"]
        assert match
        assert match[0].summary == "手工改的摘要"


class TestInitCleanup:
    """init() 清理残留 ``.tmp``。"""

    async def test_init_removes_tmp_residual(self, tmp_path: Path) -> None:
        base = tmp_path / "MEMORY"
        (base / "user").mkdir(parents=True)
        (base / "user" / "x.tmp").write_text("stale", encoding="utf-8")
        (base / "y.tmp").write_text("stale2", encoding="utf-8")

        svc = MemoryService(base, categories=_CATEGORIES)
        await svc.init()

        assert not (base / "user" / "x.tmp").exists()
        assert not (base / "y.tmp").exists()


class TestExportClear:
    """export_all/clear_all。"""

    async def test_export_returns_entries_and_index(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry())
        await svc.update_memory(_entry(slug="another", title="项目:另一条", category="project"))
        data = await svc.export_all()
        assert "entries" in data
        assert "index" in data
        assert isinstance(data["entries"], list)
        assert len(data["entries"]) == 2
        assert "# 记忆索引" in data["index"]

    async def test_clear_empties_entries_and_index(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        await svc.update_memory(_entry())
        await svc.update_memory(_entry(slug="another", category="project", title="项目:另一条"))
        await svc.clear_all()
        index = await svc.load_index()
        assert index.entries == []
        index_text = await svc.load_index_text()
        # 空索引仍含头部标题
        assert "# 记忆索引" in index_text
        assert "## 用户" not in index_text


class TestGuardrails:
    """护栏:max_entries 超限、分类白名单外。"""

    async def test_max_entries_exceeded_raises(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path, max_entries=2)
        await svc.update_memory(_entry(slug="a", title="用户:A"))
        await svc.update_memory(_entry(slug="b", title="用户:B"))
        # 第 3 个新条目超限
        with pytest.raises(MemoryServiceError):
            await svc.update_memory(_entry(slug="c", title="用户:C"))

    async def test_update_existing_not_counted_as_new(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path, max_entries=2)
        await svc.update_memory(_entry(slug="a", title="用户:A"))
        await svc.update_memory(_entry(slug="b", title="用户:B"))
        # 更新已有条目不应超限
        await svc.update_memory(_entry(slug="a", title="用户:A改"))

    async def test_non_whitelist_category_raises(self, tmp_path: Path) -> None:
        svc = await _make_service(tmp_path)
        with pytest.raises(MemoryServiceError, match="白名单"):
            await svc.update_memory(_entry(category="unknown", slug="x"))
