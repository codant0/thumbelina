"""File-backed read/write service for the TODO module.

Every operation re-reads the Markdown files from disk, so manual edits made
with an external editor are picked up immediately. Writes go through the
public :mod:`thumbelina.filestore` atomic layer (temp file + ``os.replace``),
and a per-file :class:`FileLocks` gate serializes the read-modify-write
cycles of each file, so concurrent requests never clobber one another.
Missing files are treated as empty.

Group storage model
-------------------
``todolist.md`` keeps group membership *structural*: an item belongs to the
group whose ``# heading`` marker is nearest above it.  Assigning an item to
a group therefore physically moves its checkbox line into that group's
region of the file; assigning it to the empty group moves it above the first
heading.  New items are inserted *before* any trailing group markers that
still have no members, so creating an empty group never captures later
additions.  This keeps ``serialize(parse(text))`` exact so manual edits and
service writes never drift.

``notes.md`` keeps group membership on the note object; the ``# heading``
marker is rewritten above the first note of each group on every save, so
moving a note between groups is a field assignment plus a physical
relocation that keeps each group's notes contiguous.  A *marker with no
notes* cannot be represented (the parser consumes it), so creating an empty
notes group inserts a blank placeholder note that anchors the marker until
real notes are dragged in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from thumbelina.filestore import FileLocks, read_text, write_text_atomic
from thumbelina.todo.models import Note, RawLine, TodoItem
from thumbelina.todo.parser import (
    GROUP_HEADER_RE,
    parse_notes,
    parse_todolist,
    serialize_notes,
    serialize_todolist,
)

TODO_LIST_FILENAME = "todolist.md"
NOTES_FILENAME = "notes.md"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"

GroupKind = Literal["items", "notes"]


class GroupNameConflictError(Exception):
    """Raised when a group rename target collides with an existing group."""

    def __init__(self, name: str) -> None:
        super().__init__(f"group already exists: {name}")
        self.name = name


class GroupNotFoundError(Exception):
    """Raised when a referenced group does not exist in the file."""

    def __init__(self, name: str) -> None:
        super().__init__(f"group not found: {name}")
        self.name = name


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
            segments = await self._read_todolist()
            return self._items(segments)

    async def add_item(self, text: str, remark: str = "") -> list[TodoItem]:
        """Add a new pending item.

        The item stays ungrouped: it is inserted before any trailing group
        markers that have no members yet, so a freshly created empty group
        does not silently capture new additions.
        """
        async with self._locks.locked(self._todolist_path):
            segments = await self._read_todolist()
            new_item = TodoItem(
                index=len(self._items(segments)), text=text, done=False, remark=remark
            )
            segments.insert(self._ungrouped_insert_pos(segments), new_item)
            self._renumber_items(segments)
            await self._write(self._todolist_path, serialize_todolist(segments))
            return self._items(segments)

    async def update_item(
        self,
        index: int,
        *,
        text: str | None = None,
        done: bool | None = None,
        remark: str | None = None,
        group: str | None = None,
    ) -> list[TodoItem]:
        """Update the item at ``index``.

        Every parameter follows the same rule: ``None`` means "leave it
        unchanged".  ``group`` is the exception that can *clear*: ``""``
        moves the item out of any group (the "ungrouped" bucket), while any
        non-empty string moves the checkbox line into that group's region of
        the file so the heading round-trips.
        """
        async with self._locks.locked(self._todolist_path):
            segments = await self._read_todolist()
            item = self._item_at(segments, index)
            if text is not None:
                item.text = text
            if done is not None:
                item.done = done
            if remark is not None:
                item.remark = remark
            if group is not None:
                self._reassign_group(segments, index, "" if group == "" else group)
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

    async def update_note(
        self,
        index: int,
        content: str | None = None,
        *,
        group: str | None = None,
    ) -> list[Note]:
        """Update the note at ``index``.

        ``None`` parameters are left unchanged; ``group`` additionally uses
        ``""`` to clear the note's assignment.  Because a ``# heading`` in
        ``notes.md`` prefixes every note below it, group members must stay
        physically contiguous: moving a note to a different group relocates
        it to the tail of that group (or the top of the file when ungrouped)
        so ``serialize(parse(text))`` stays exact.
        """
        async with self._locks.locked(self._notes_path):
            preamble, notes = await self._read_notes()
            self._require_index(len(notes), index, "note")
            note = notes[index]
            if content is not None:
                note.content = content
            if group is not None:
                target = None if group == "" else group
                self._reassign_note_group(preamble, notes, index, target)
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
    # groups
    # ------------------------------------------------------------------

    async def create_group(self, kind: GroupKind, name: str) -> None:
        """Make sure a group with the given name exists in the file.

        Idempotent.  For ``items`` the marker is appended at the end of the
        file; the first item dragged into the group is physically moved
        beneath it.  For ``notes`` the file format cannot persist a marker
        without a member note, so a blank placeholder note is added to the
        top of the group as an anchor; it shows up in the list until the
        user types over it or drags real notes in.
        """
        if kind == "items":
            async with self._locks.locked(self._todolist_path):
                segments = await self._read_todolist()
                if self._group_marker_pos(segments, name) is None:
                    segments.append(RawLine(text=f"# {name}"))
                    await self._write(self._todolist_path, serialize_todolist(segments))
            return
        async with self._locks.locked(self._notes_path):
            preamble, notes = await self._read_notes()
            if self._has_note_group(preamble, notes, name):
                return
            # The group marker is a prefix in notes.md: it tags every note
            # below it until the next marker.  Anchoring the new group at the
            # *end* of the list (a blank placeholder note) keeps existing
            # notes in their current buckets; the first real note dragged in
            # repositions the marker above itself.
            placeholder = Note(
                index=len(notes),
                timestamp=datetime.now().strftime(TIMESTAMP_FORMAT),
                content="",
                group=name,
            )
            notes.append(placeholder)
            self._renumber_notes(notes)
            await self._write(self._notes_path, serialize_notes(preamble, notes))

    async def rename_group(self, kind: GroupKind, old: str, new: str) -> None:
        """Rename the ``# old`` marker and reassign every member to ``new``.

        Runs inside the per-file lock so a concurrent reader never sees the
        file half-rewritten.  Renaming onto an existing group name would
        make the boundary ambiguous, so that is refused.
        """
        if kind == "items":
            async with self._locks.locked(self._todolist_path):
                segments = await self._read_todolist()
                if self._group_marker_pos(segments, old) is None:
                    raise GroupNotFoundError(old)
                if old != new and self._group_marker_pos(segments, new) is not None:
                    raise GroupNameConflictError(new)
                for segment in segments:
                    if isinstance(segment, RawLine) and segment.text.strip() == f"# {old}":
                        segment.text = f"# {new}"
                for item in self._items(segments):
                    if item.group == old:
                        item.group = new
                await self._write(self._todolist_path, serialize_todolist(segments))
            return
        async with self._locks.locked(self._notes_path):
            preamble, notes = await self._read_notes()
            if not self._has_note_group(preamble, notes, old):
                raise GroupNotFoundError(old)
            if old != new and self._has_note_group(preamble, notes, new):
                raise GroupNameConflictError(new)
            preamble = self._rewrite_lines(
                preamble, match=lambda line: line.strip() == f"# {old}", replacement=f"# {new}"
            )
            for note in notes:
                if note.group == old:
                    note.group = new
            await self._write(self._notes_path, serialize_notes(preamble, notes))

    async def delete_group(self, kind: GroupKind, name: str) -> None:
        """Delete the ``# name`` marker and detach every member.

        Members are physically moved above the first remaining heading (the
        "ungrouped" bucket) so they are not re-tagged by a neighbouring
        marker on the next parse.  Other groups are untouched.
        """
        if kind == "items":
            async with self._locks.locked(self._todolist_path):
                segments = await self._read_todolist()
                if self._group_marker_pos(segments, name) is None:
                    raise GroupNotFoundError(name)
            members = [item for item in self._items(segments) if item.group == name]
            segments = [
                segment
                for segment in segments
                if not (isinstance(segment, RawLine) and segment.text.strip() == f"# {name}")
            ]
            for item in members:
                self._move_item_to_ungrouped(segments, item)
            await self._write(self._todolist_path, serialize_todolist(segments))
        elif kind == "notes":
            async with self._locks.locked(self._notes_path):
                preamble, notes = await self._read_notes()
                if not self._has_note_group(preamble, notes, name):
                    raise GroupNotFoundError(name)
                note_members = [note for note in notes if note.group == name]
                preamble = self._rewrite_lines(
                    preamble,
                    match=lambda line: line.strip() == f"# {name}",
                    replacement=None,  # drop the marker line
                )
                notes = [note for note in notes if note.group != name]
                # Ungrouped notes sit above the first group marker; the
                # deleted group's former members rejoin that top region in
                # their old relative order.  Blank placeholder notes (the
                # anchor created for an empty group) are dropped, not
                # resurrected.
                kept_members = [member for member in note_members if member.content]
                for member in kept_members:
                    member.group = None
                notes = kept_members + notes
                self._renumber_notes(notes)
                await self._write(self._notes_path, serialize_notes(preamble, notes))

    # ------------------------------------------------------------------
    # internals: notes.md layout
    # ------------------------------------------------------------------

    def _reassign_note_group(
        self, preamble: str, notes: list[Note], index: int, target: str | None
    ) -> None:
        """Physically relocate ``notes[index]`` so group regions stay contiguous.

        ``notes.md`` group markers prefix everything below them, so an
        ungrouped note must sit before the first marker and each group's
        members must form one contiguous run.  Moving a note therefore
        splices it out and re-inserts it at the tail of its new run.
        """
        note = notes[index]
        if note.group == target:
            return
        del notes[index]
        note.group = target
        if target is None:
            # Top of the file: before the first grouped note.
            insert_at = 0
            while insert_at < len(notes) and notes[insert_at].group is None:
                insert_at += 1
        else:
            # Tail of the target group's contiguous run.
            insert_at = len(notes)
            for position in range(len(notes) - 1, -1, -1):
                if notes[position].group == target:
                    insert_at = position + 1
                    break
        notes.insert(insert_at, note)
        self._renumber_notes(notes)

    # ------------------------------------------------------------------
    # internals: todolist.md layout
    # ------------------------------------------------------------------

    @staticmethod
    def _group_marker_pos(segments: list[TodoItem | RawLine], name: str) -> int | None:
        """Index of the ``# name`` marker RawLine, or None when absent."""
        for position, segment in enumerate(segments):
            if isinstance(segment, RawLine) and segment.text.strip() == f"# {name}":
                return position
        return None

    @staticmethod
    def _heading_pos(segments: list[TodoItem | RawLine]) -> int | None:
        """Index of the first group-heading RawLine (the ungrouped boundary)."""
        for position, segment in enumerate(segments):
            if isinstance(segment, RawLine) and GROUP_HEADER_RE.match(segment.text.strip()):
                return position
        return None

    @staticmethod
    def _ungrouped_insert_pos(segments: list[TodoItem | RawLine]) -> int:
        """Insertion index for a new item.

        Matches the legacy "append to the end" behaviour, except that a
        file ending with *empty* group markers (a ``# name`` heading with no
        members beneath it, as freshly created by :meth:`create_group`)
        must not capture the new item: the line goes before those markers
        so it stays ungrouped.
        """
        insert_at = len(segments)
        while insert_at > 0:
            previous = segments[insert_at - 1]
            if isinstance(previous, RawLine) and GROUP_HEADER_RE.match(previous.text.strip()):
                insert_at -= 1
                continue
            break
        return insert_at

    def _reassign_group(self, segments: list[TodoItem | RawLine], index: int, name: str) -> None:
        """Physically move the item at ``index`` into the group ``name``.

        An empty ``name`` means "ungrouped": the line moves above the first
        heading.  Moving an item whose ``group`` already equals ``name`` is
        a no-op (dragging onto the current card keeps its position).
        """
        position, item = self._locate_item(segments, index)
        if name == "":
            if item.group is None:
                return
            del segments[position]
            item.group = None
            boundary = self._heading_pos(segments)
            insert_at = len(segments) if boundary is None else boundary
            segments.insert(insert_at, item)
            self._renumber_items(segments)
            return
        if item.group == name:
            return
        del segments[position]
        item.group = name
        self._insert_item_into_group(segments, item)

    def _insert_item_into_group(self, segments: list[TodoItem | RawLine], item: TodoItem) -> None:
        """Insert ``item`` at the end of its group's region (after the last
        member, before the next heading or end of file).  A marker is created
        at the end of the file when the group does not exist yet."""
        name = item.group or ""
        marker_pos = self._group_marker_pos(segments, name)
        if marker_pos is None:
            segments.append(RawLine(text=f"# {name}"))
            segments.append(item)
            self._renumber_items(segments)
            return
        insert_at = len(segments)
        for position in range(marker_pos + 1, len(segments)):
            segment = segments[position]
            if isinstance(segment, RawLine) and GROUP_HEADER_RE.match(segment.text.strip()):
                insert_at = position
                break
        segments.insert(insert_at, item)
        self._renumber_items(segments)

    def _move_item_to_ungrouped(self, segments: list[TodoItem | RawLine], item: TodoItem) -> None:
        """Move ``item`` (still in ``segments``) above the first heading."""
        position = next(
            (position for position, seg in enumerate(segments) if seg is item), len(segments)
        )
        if position < len(segments):
            del segments[position]
        item.group = None
        boundary = self._heading_pos(segments)
        insert_at = len(segments) if boundary is None else boundary
        segments.insert(insert_at, item)
        self._renumber_items(segments)

    @staticmethod
    def _rewrite_lines(text: str, *, match: Callable[[str], bool], replacement: str | None) -> str:
        """Map matching lines to ``replacement``, dropping them when None."""
        out: list[str] = []
        for line in text.splitlines():
            if match(line):
                if replacement is not None:
                    out.append(replacement)
            else:
                out.append(line)
        return "\n".join(out)

    @staticmethod
    def _has_note_group(preamble: str, notes: list[Note], name: str) -> bool:
        if any(line.strip() == f"# {name}" for line in preamble.splitlines()):
            return True
        return any(note.group == name for note in notes)

    # ------------------------------------------------------------------
    # internals: shared
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
