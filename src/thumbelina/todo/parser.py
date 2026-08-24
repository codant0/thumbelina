"""Markdown parsing and serialization for the TODO module.

``todolist.md`` is a checkbox list; non-checkbox lines (headings, comments,
blank lines) are preserved verbatim as :class:`RawLine` segments. A ``#
heading`` line additionally marks a group boundary: every subsequent
checkbox item belongs to that group until the next heading (or None before
the first heading).

``notes.md`` is a sequence of ``## YYYY-MM-DD HH:MM`` blocks. Free-form
content before the first header is kept as the preamble. A ``# heading``
line is a structural group marker: it never becomes part of the preamble or
of any block, and each note belongs to the nearest preceding marker.
Serialization writes the marker back on the first block of its group, so
``serialize(parse(text))`` round-trips exactly for well-formed files
(markers on their own line, directly above the group's first block).
Trailing blank lines of the preamble and of each block are stripped on
parse, so the round trip is exact for well-formed files.
"""

from __future__ import annotations

import re

from thumbelina.todo.models import Note, RawLine, TodoItem

CHECKBOX_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
NOTE_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")
# A remark is stored as one or more blockquote lines immediately after a
# checkbox item, so it can carry arbitrary Markdown (multi-line included).
REMARK_LINE_RE = re.compile(r"^> ?(.*)$")
# A level-1 heading used as a group marker. `^# ` matches a single '#'
# followed by a space, never "## ..." or "### ...".
GROUP_HEADER_RE = re.compile(r"^# (.*)$")


def parse_todolist(text: str) -> list[TodoItem | RawLine]:
    """Parse ``todolist.md`` content into ordered segments.

    Checkbox lines become :class:`TodoItem` (index counts only checkbox
    lines, starting at 0), tagged with the nearest preceding group heading;
    every other line becomes a :class:`RawLine`. Blockquote (``> ``) lines
    directly following a checkbox are collected as that item's Markdown
    ``remark`` rather than standalone raw lines.
    """
    segments: list[TodoItem | RawLine] = []
    index = 0
    pending: TodoItem | None = None
    current_group: str | None = None
    for line in text.splitlines():
        group_match = GROUP_HEADER_RE.match(line)
        if group_match and group_match.group(1).strip():
            current_group = group_match.group(1).strip()
        match = CHECKBOX_RE.match(line)
        if match:
            pending = TodoItem(
                index=index,
                text=match.group(2),
                done=match.group(1) != " ",
                group=current_group,
            )
            segments.append(pending)
            index += 1
            continue
        if pending is not None:
            remark = REMARK_LINE_RE.match(line)
            if remark:
                content = remark.group(1)
                pending.remark = f"{pending.remark}\n{content}" if pending.remark else content
                continue
        pending = None
        segments.append(RawLine(text=line))
    return segments


def serialize_todolist(segments: list[TodoItem | RawLine]) -> str:
    """Serialize segments back to ``todolist.md`` text.

    The result ends with a single trailing newline; an empty segment list
    serializes to an empty string.
    """
    if not segments:
        return ""
    lines: list[str] = []
    for segment in segments:
        if isinstance(segment, TodoItem):
            mark = "x" if segment.done else " "
            lines.append(f"- [{mark}] {segment.text}")
            if segment.remark:
                lines.extend(f"> {remark_line}" for remark_line in segment.remark.splitlines())
        else:
            lines.append(segment.text)
    return "\n".join(lines) + "\n"


def parse_notes(text: str) -> tuple[str, list[Note]]:
    """Parse ``notes.md`` content into ``(preamble, notes)``.

    The preamble is everything before the first ``## YYYY-MM-DD HH:MM``
    header, with trailing blank lines stripped. Each header starts a new
    :class:`Note` whose content runs until the next header; trailing blank
    lines of each block are stripped. A ``# heading`` line is a structural
    group marker: it is skipped (never part of the preamble or of any
    content) and tags every note after it with that group.
    """
    if not text:
        return "", []
    preamble: list[str] = []
    notes: list[Note] = []
    current_group: str | None = None
    current_content: list[str] | None = None
    current_timestamp: str | None = None
    current_note_group: str | None = None
    for line in text.splitlines():
        group_match = GROUP_HEADER_RE.match(line)
        if group_match and group_match.group(1).strip():
            current_group = group_match.group(1).strip()
            continue
        header_match = NOTE_HEADER_RE.match(line)
        if header_match:
            if current_timestamp is not None:
                notes.append(
                    Note(
                        index=len(notes),
                        timestamp=current_timestamp,
                        content=_join_without_trailing_blank(current_content or []),
                        group=current_note_group,
                    )
                )
            current_timestamp = header_match.group(1)
            current_note_group = current_group
            current_content = []
            continue
        if current_timestamp is not None:
            current_content.append(line)
        else:
            preamble.append(line)
    if current_timestamp is not None:
        notes.append(
            Note(
                index=len(notes),
                timestamp=current_timestamp,
                content=_join_without_trailing_blank(current_content or []),
                group=current_note_group,
            )
        )
    return _join_without_trailing_blank(preamble), notes


def serialize_notes(preamble: str, notes: list[Note]) -> str:
    """Serialize preamble and notes back to ``notes.md`` text.

    Blocks are separated by exactly one blank line and the file ends with
    a single newline; empty input serializes to an empty string. A group
    marker is written on the first block of each group (``# group`` directly
    above ``## timestamp``).
    """
    blocks: list[str] = []
    if preamble:
        blocks.append(preamble.rstrip("\n"))
    prev_group: str | None = None
    for note in notes:
        block = ""
        if note.group is not None and note.group != prev_group:
            block = f"# {note.group}"
            prev_group = note.group
        header = f"## {note.timestamp}"
        block = f"{block}\n{header}" if block else header
        if note.content:
            block = f"{block}\n{note.content.rstrip(chr(10))}"
        blocks.append(block)
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _join_without_trailing_blank(lines: list[str]) -> str:
    """Join lines with newlines, dropping trailing blank lines."""
    kept = list(lines)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)
