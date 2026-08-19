"""File-backed read/write service for the TODO module.

Every operation re-reads the Markdown files from disk, so manual edits made
with an external editor are picked up immediately. Writes go through the
public :mod:`thumbelina.filestore` atomic layer (temp file + ``os.replace``),
and a per-file :class:`FileLocks` gate serializes the read-modify-write
cycles of each file, so concurrent requests never clobber one another.
Missing files are treated as empty.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from thumbelina.filestore import FileLocks, read_text, write_text_atomic
from thumbelina.todo.models import Note, RawLine, TodoItem
from thumbelina.todo.parser import (
    parse_notes,
    parse_todolist,
    serialize_notes,
    serialize_todolist,
)

TODO_LIST_FILENAME = "todolist.md"
NOTES_FILENAME = "notes.md"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


class TodoService:
    """Async CRUD service over ``todolist.md`` and ``notes.md`` in a directory.

    Locks are keyed per file (``todolist.md`` and ``notes.md`` get independent
    locks), so touching one file never blocks the other. Create one service
    per directory; two services pointing at the same directory do not share
    locks.
    """

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._todolist_path = self._directory / TODO_LIST_FILENAME
        self._notes_path = self._directory / NOTES_FILENAME
        self._locks = FileLocks()

    async def init(self) -> None:
        """Create the storage directory (and parents); never touches files."""
        await asyncio.to_thread(self._directory.mkdir, parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # todolist.md
    # ------------------------------------------------------------------

    async def list_items(self) -> list[TodoItem]:
        """Return all checkbox items in file order."""
        async with self._locks.locked(self._todolist_path):
            return self._items(await self._read_todolist())

    async def add_item(self, text: str, remark: str = "") -> list[TodoItem]:
        """Append a new pending item at the end of the file."""
        async with self._locks.locked(self._todolist_path):
            segments = await self._read_todolist()
            segments.append(
                TodoItem(index=len(self._items(segments)), text=text, done=False, remark=remark)
            )
            await self._write(self._todolist_path, serialize_todolist(segments))
            return self._items(segments)

    async def update_item(
        self,
        index: int,
        *,
        text: str | None = None,
        done: bool | None = None,
        remark: str | None = None,
    ) -> list[TodoItem]:
        """Update the text, done state and/or remark of the item at ``index``."""
        async with self._locks.locked(self._todolist_path):
            segments = await self._read_todolist()
            item = self._item_at(segments, index)
            if text is not None:
                item.text = text
            if done is not None:
                item.done = done
            if remark is not None:
                item.remark = remark
            await self._write(self._todolist_path, serialize_todolist(segments))
            return self._items(segments)

    async def delete_item(self, index: int) -> list[TodoItem]:
        """Delete the item at ``index``; remaining items are renumbered."""
        async with self._locks.locked(self._todolist_path):
            segments = await self._read_todolist()
            position, _ = self._locate_item(segments, index)
            del segments[position]
            self._renumber_items(segments)
            await self._write(self._todolist_path, serialize_todolist(segments))
            return self._items(segments)

    # ------------------------------------------------------------------
    # notes.md
    # ------------------------------------------------------------------

    async def list_notes(self) -> list[Note]:
        """Return all notes in file order (newest first by convention)."""
        async with self._locks.locked(self._notes_path):
            _, notes = await self._read_notes()
            return notes

    async def add_note(self, content: str) -> list[Note]:
        """Insert a new note stamped with the current time at the top."""
        async with self._locks.locked(self._notes_path):
            preamble, notes = await self._read_notes()
            timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
            notes.insert(0, Note(index=0, timestamp=timestamp, content=content))
            self._renumber_notes(notes)
            await self._write(self._notes_path, serialize_notes(preamble, notes))
            return notes

    async def update_note(self, index: int, content: str) -> list[Note]:
        """Replace the content of the note at ``index``; timestamp is kept."""
        async with self._locks.locked(self._notes_path):
            preamble, notes = await self._read_notes()
            self._require_index(len(notes), index, "note")
            notes[index].content = content
            await self._write(self._notes_path, serialize_notes(preamble, notes))
            return notes

    async def delete_note(self, index: int) -> list[Note]:
        """Delete the note at ``index``; remaining notes are renumbered."""
        async with self._locks.locked(self._notes_path):
            preamble, notes = await self._read_notes()
            self._require_index(len(notes), index, "note")
            del notes[index]
            self._renumber_notes(notes)
            await self._write(self._notes_path, serialize_notes(preamble, notes))
            return notes

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _read_todolist(self) -> list[TodoItem | RawLine]:
        text = await self._read(self._todolist_path)
        return parse_todolist(text)

    async def _read_notes(self) -> tuple[str, list[Note]]:
        text = await self._read(self._notes_path)
        return parse_notes(text)

    @staticmethod
    async def _read(path: Path) -> str:
        return await asyncio.to_thread(read_text, path)

    @staticmethod
    async def _write(path: Path, text: str) -> None:
        await asyncio.to_thread(write_text_atomic, path, text)

    @staticmethod
    def _items(segments: list[TodoItem | RawLine]) -> list[TodoItem]:
        return [segment for segment in segments if isinstance(segment, TodoItem)]

    @staticmethod
    def _locate_item(segments: list[TodoItem | RawLine], index: int) -> tuple[int, TodoItem]:
        seen = 0
        for position, segment in enumerate(segments):
            if isinstance(segment, TodoItem):
                if seen == index:
                    return position, segment
                seen += 1
        raise IndexError(f"item index out of range: {index}")

    @classmethod
    def _item_at(cls, segments: list[TodoItem | RawLine], index: int) -> TodoItem:
        return cls._locate_item(segments, index)[1]

    @staticmethod
    def _renumber_items(segments: list[TodoItem | RawLine]) -> None:
        index = 0
        for segment in segments:
            if isinstance(segment, TodoItem):
                segment.index = index
                index += 1

    @staticmethod
    def _renumber_notes(notes: list[Note]) -> None:
        for position, note in enumerate(notes):
            note.index = position

    @staticmethod
    def _require_index(length: int, index: int, kind: str) -> None:
        if not 0 <= index < length:
            raise IndexError(f"{kind} index out of range: {index}")
