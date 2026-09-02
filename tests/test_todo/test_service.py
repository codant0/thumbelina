"""Tests for the TodoService file-backed read/write service."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from thumbelina.todo.service import (
    GroupNameConflictError,
    GroupNotFoundError,
    TodoService,
)

TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


async def make_service(tmp_path: Path) -> TodoService:
    """Create and initialize a TodoService in a fresh ``tmp_path/TODO`` dir."""
    service = TodoService(tmp_path / "TODO")
    await service.init()
    return service


class TestInit:
    """``init()`` only creates the directory, never touches files."""

    async def test_init_creates_directory(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO" / "nested"
        assert not directory.exists()

        await TodoService(str(directory)).init()

        assert directory.is_dir()

    async def test_init_preserves_existing_files(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        directory.mkdir()
        todolist_text = "# 我的待办\n- [ ] 已有条目\n"
        notes_text = "## 2026-08-13 09:15\n已有的随手记\n"
        (directory / "todolist.md").write_text(todolist_text, encoding="utf-8")
        (directory / "notes.md").write_text(notes_text, encoding="utf-8")

        await TodoService(directory).init()

        assert (directory / "todolist.md").read_text(encoding="utf-8") == todolist_text
        assert (directory / "notes.md").read_text(encoding="utf-8") == notes_text

    async def test_list_before_init_returns_empty(self, tmp_path: Path) -> None:
        service = TodoService(tmp_path / "TODO")

        assert await service.list_items() == []
        assert await service.list_notes() == []


class TestItems:
    """CRUD on ``todolist.md`` checkbox items."""

    async def test_add_and_list_items(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)

        await service.add_item("买牛奶")
        items = await service.add_item("写周报")

        assert [item.index for item in items] == [0, 1]
        assert [item.text for item in items] == ["买牛奶", "写周报"]
        assert [item.done for item in items] == [False, False]
        assert await service.list_items() == items

    async def test_update_item_text_and_done(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)
        await service.add_item("买牛奶")
        await service.add_item("写周报")

        updated = await service.update_item(0, text="买脱脂牛奶")
        assert [item.text for item in updated] == ["买脱脂牛奶", "写周报"]
        assert updated[0].done is False

        toggled = await service.update_item(1, done=True)
        assert [item.text for item in toggled] == ["买脱脂牛奶", "写周报"]
        assert toggled[1].done is True
        assert toggled[0].done is False

        with pytest.raises(IndexError):
            await service.update_item(5, text="越界")
        with pytest.raises(IndexError):
            await service.update_item(-1, done=True)

    async def test_update_item_remark(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)
        await service.add_item("买牛奶")
        await service.add_item("写周报")

        updated = await service.update_item(0, remark="记得买**脱脂**的")
        assert [item.remark for item in updated] == ["记得买**脱脂**的", ""]
        # Text and done state are untouched by a remark-only update.
        assert [item.text for item in updated] == ["买牛奶", "写周报"]
        assert updated[0].done is False

        # A remark can span multiple lines and persist to disk as blockquotes.
        revised = await service.update_item(0, remark="第一行\n第二行")
        assert revised[0].remark == "第一行\n第二行"
        file_text = (tmp_path / "TODO" / "todolist.md").read_text(encoding="utf-8")
        assert "> 第一行" in file_text
        assert "> 第二行" in file_text

        # Clearing a remark (empty string) removes the blockquote lines.
        cleared = await service.update_item(0, remark="")
        assert cleared[0].remark == ""
        file_text = (tmp_path / "TODO" / "todolist.md").read_text(encoding="utf-8")
        assert "> " not in file_text

        with pytest.raises(IndexError):
            await service.update_item(5, remark="越界")

    async def test_delete_item(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)
        await service.add_item("a")
        await service.add_item("b")
        await service.add_item("c")

        remaining = await service.delete_item(1)

        assert [item.text for item in remaining] == ["a", "c"]
        assert [item.index for item in remaining] == [0, 1]

        with pytest.raises(IndexError):
            await service.delete_item(2)


class TestNotes:
    """CRUD on ``notes.md`` blocks; newest note first."""

    async def test_add_note_prepends(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()

        await service.add_note("第一条")
        notes = await service.add_note("第二条")

        assert [note.index for note in notes] == [0, 1]
        assert [note.content for note in notes] == ["第二条", "第一条"]
        for note in notes:
            assert TIMESTAMP_RE.fullmatch(note.timestamp)

        # The newest entry sits at the top of the file on disk.
        file_text = (directory / "notes.md").read_text(encoding="utf-8")
        assert file_text.index("第二条") < file_text.index("第一条")

    async def test_update_note(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)
        await service.add_note("第一条")
        await service.add_note("第二条")

        original_timestamp = (await service.list_notes())[1].timestamp
        updated = await service.update_note(1, "修改后的第一条")

        assert [note.content for note in updated] == ["第二条", "修改后的第一条"]
        assert updated[1].timestamp == original_timestamp

        with pytest.raises(IndexError):
            await service.update_note(9, "越界")

    async def test_delete_note(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)
        await service.add_note("a")
        await service.add_note("b")
        await service.add_note("c")

        remaining = await service.delete_note(1)

        assert [note.content for note in remaining] == ["c", "a"]
        assert [note.index for note in remaining] == [0, 1]

        with pytest.raises(IndexError):
            await service.delete_note(2)


class TestFileInteraction:
    """The Markdown files are the source of truth; writes are atomic."""

    async def test_manual_file_edit_visible(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_item("服务写入的条目")

        # Simulate the user editing the file with an external editor.
        (directory / "todolist.md").write_text(
            "# 手工标题\n- [x] 手工修改的条目\n", encoding="utf-8"
        )

        items = await service.list_items()
        assert [(item.text, item.done) for item in items] == [("手工修改的条目", True)]

        # The heading survives a service write (raw lines are preserved).
        after_add = await service.add_item("新增条目")
        assert [item.text for item in after_add] == ["手工修改的条目", "新增条目"]
        file_text = (directory / "todolist.md").read_text(encoding="utf-8")
        assert file_text.startswith("# 手工标题\n")

    async def test_atomic_write(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()

        await service.add_item("原子写入测试")
        await service.add_note("原子写入测试笔记")

        leftovers = sorted(path.name for path in directory.iterdir() if path.name.endswith(".tmp"))
        assert leftovers == []
        assert (directory / "todolist.md").read_text(encoding="utf-8") == "- [ ] 原子写入测试\n"
        notes_text = (directory / "notes.md").read_text(encoding="utf-8")
        assert notes_text.endswith("原子写入测试笔记\n")
        assert TIMESTAMP_RE.match(notes_text.removeprefix("## "))


class TestConcurrency:
    """A single asyncio lock serializes writers; no updates are lost."""

    async def test_concurrent_adds(self, tmp_path: Path) -> None:
        service = await make_service(tmp_path)

        await asyncio.gather(*(service.add_item(f"并发条目 {i}") for i in range(10)))

        items = await service.list_items()
        assert len(items) == 10
        assert sorted(item.text for item in items) == [f"并发条目 {i}" for i in range(10)]


class TestGroupCRUD:
    """Group CRUD: create / rename / delete on todolist.md and notes.md."""

    async def test_create_item_group_appends_marker(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_item("条目 A")

        await service.create_group("items", "工作")

        text = (directory / "todolist.md").read_text(encoding="utf-8")
        assert text.endswith("- [ ] 条目 A\n# 工作\n")
        # Existing items stay ungrouped: only new assignments adopt the group.
        items = await service.list_items()
        assert items[0].group is None

    async def test_add_item_skips_trailing_empty_group_marker(self, tmp_path: Path) -> None:
        """A fresh empty group (a trailing ``# name`` with no members) must
        not capture items added afterwards — new items stay ungrouped until
        the user explicitly drags them into the group."""
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_item("条目 A")
        await service.create_group("items", "工作")

        items = await service.add_item("新条目")

        # Both items stay ungrouped; the marker stays below them.
        assert [item.group for item in items] == [None, None]
        text = (directory / "todolist.md").read_text(encoding="utf-8")
        assert text == "- [ ] 条目 A\n- [ ] 新条目\n# 工作\n"

    async def test_create_item_group_is_idempotent(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()

        await service.create_group("items", "工作")
        await service.create_group("items", "工作")

        text = (directory / "todolist.md").read_text(encoding="utf-8")
        # The second call must not duplicate the heading.
        assert text.count("# 工作") == 1

    async def test_update_item_assigns_group_and_creates_marker(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_item("条目 A")

        updated = await service.update_item(0, group="工作")

        assert updated[0].group == "工作"
        text = (directory / "todolist.md").read_text(encoding="utf-8")
        # The marker is inserted above the first item in the group so the
        # parser tags that item with it.
        assert text == "# 工作\n- [ ] 条目 A\n"

    async def test_update_item_group_empty_string_clears(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        # Pre-seed a grouped item.
        (directory / "todolist.md").write_text("# 工作\n- [ ] 条目 A\n", encoding="utf-8")

        updated = await service.update_item(0, group="")

        assert updated[0].group is None
        text = (directory / "todolist.md").read_text(encoding="utf-8")
        # Clearing the group does not delete the heading marker — other
        # items may still reference it. Empty-string round-trip just emits
        # the marker alone (no items follow it).
        assert "# 工作" in text

    async def test_rename_item_group_swaps_marker_and_members(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_item("条目 A")
        await service.add_item("条目 B")
        # Moving A physically relocates its line, so re-list after each move
        # to observe the fresh ordering the UI would see.
        await service.update_item(0, group="工作")
        remaining = await service.list_items()
        # B is still ungrouped; drag it in using its current index.
        await service.update_item(remaining[0].index, group="工作")

        await service.rename_group("items", "工作", "Projects")

        items = await service.list_items()
        assert [item.group for item in items] == ["Projects", "Projects"]
        text = (directory / "todolist.md").read_text(encoding="utf-8")
        assert "# Projects" in text
        assert "# 工作" not in text

    async def test_rename_item_group_rejects_collision(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.create_group("items", "工作")
        await service.create_group("items", "学习")

        with pytest.raises(GroupNameConflictError):
            await service.rename_group("items", "工作", "学习")

    async def test_rename_item_group_unknown_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()

        with pytest.raises(GroupNotFoundError):
            await service.rename_group("items", "不存在", "学习")

    async def test_delete_item_group_moves_members_to_ungrouped(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_item("条目 A")
        await service.update_item(0, group="工作")
        await service.create_group("items", "学习")
        await service.add_item("条目 B")
        await service.update_item(1, group="学习")

        await service.delete_group("items", "工作")

        items = await service.list_items()
        assert [item.group for item in items] == [None, "学习"]
        text = (directory / "todolist.md").read_text(encoding="utf-8")
        assert "# 工作" not in text
        assert "# 学习" in text

    async def test_delete_item_group_unknown_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()

        with pytest.raises(GroupNotFoundError):
            await service.delete_group("items", "不存在")

    async def test_note_group_crud_round_trip(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_note("笔记 A")
        await service.add_note("笔记 B")
        # Notes list newest-first: [B, A].  Drag each into 工作.  Each move
        # physically relocates notes (groups must stay contiguous), so look
        # up the current index per drag rather than caching it.
        for content in ("笔记 B", "笔记 A"):
            notes = await service.list_notes()
            target = next(note for note in notes if note.content == content)
            await service.update_note(target.index, group="工作")

        notes = await service.list_notes()
        assert all(note.group == "工作" for note in notes)

        await service.rename_group("notes", "工作", "Projects")
        notes = await service.list_notes()
        assert all(note.group == "Projects" for note in notes)

        await service.delete_group("notes", "Projects")
        notes = await service.list_notes()
        assert all(note.group is None for note in notes)
        # No blank placeholder anchor survives the group deletion.
        assert all(note.content for note in notes)

    async def test_update_note_group_empty_string_clears(self, tmp_path: Path) -> None:
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_note("笔记 A")
        await service.update_note(0, "笔记 A", group="工作")

        updated = await service.update_note(0, "笔记 A", group="")

        assert updated[0].group is None

    async def test_create_note_group_uses_blank_placeholder(self, tmp_path: Path) -> None:
        """An empty notes group is anchored by a blank placeholder note so the
        marker survives re-reads without capturing existing notes."""
        directory = tmp_path / "TODO"
        service = TodoService(directory)
        await service.init()
        await service.add_note("真实笔记")

        await service.create_group("notes", "工作")

        notes = await service.list_notes()
        # [真实笔记, 占位符] — the placeholder sits at the tail.
        assert [note.content for note in notes] == ["真实笔记", ""]
        assert notes[-1].group == "工作"
        text = (directory / "notes.md").read_text(encoding="utf-8")
        assert "# 工作" in text

        # Idempotent.
        await service.create_group("notes", "工作")
        assert "# 工作" in (directory / "notes.md").read_text(encoding="utf-8")

        # Deleting the group removes the blank anchor instead of resurrecting it.
        await service.delete_group("notes", "工作")
        notes = await service.list_notes()
        assert [note.content for note in notes] == ["真实笔记"]
        assert "# 工作" not in (directory / "notes.md").read_text(encoding="utf-8")
