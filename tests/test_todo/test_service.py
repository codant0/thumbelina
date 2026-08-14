"""Tests for the TodoService file-backed read/write service."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from thumbelina.todo.service import TodoService

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
