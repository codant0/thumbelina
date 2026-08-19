"""Markdown parsing and serialization for the TODO module.

``todolist.md`` is a checkbox list; non-checkbox lines (headings, comments,
blank lines) are preserved verbatim as :class:`RawLine` segments.

``notes.md`` is a sequence of ``## YYYY-MM-DD HH:MM`` blocks. Free-form
content before the first header is kept as the preamble. Trailing blank
lines of the preamble and of each block are stripped on parse, so
``serialize(parse(text))`` round-trips exactly for well-formed files.
"""

from __future__ import annotations

import re

from thumbelina.todo.models import Note, RawLine, TodoItem

CHECKBOX_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
NOTE_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")
# A remark is stored as one or more blockquote lines immediately after a
# checkbox item, so it can carry arbitrary Markdown (multi-line included).
REMARK_LINE_RE = re.compile(r"^> ?(.*)$")


def parse_todolist(text: str) -> list[TodoItem | RawLine]:
    """Parse ``todolist.md`` content into ordered segments.

    Checkbox lines become :class:`TodoItem` (index counts only checkbox
    lines, starting at 0); every other line becomes a :class:`RawLine`.
    Blockquote (``> ``) lines directly following a checkbox are collected as
    that item's Markdown ``remark`` rather than standalone raw lines.
    """
    segments: list[TodoItem | RawLine] = []
    index = 0
    pending: TodoItem | None = None
    for line in text.splitlines():
        match = CHECKBOX_RE.match(line)
        if match:
            pending = TodoItem(
                index=index,
                text=match.group(2),
                done=match.group(1) != " ",
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
    lines of each block are stripped.
    """
    if not text:
        return "", []
    lines = text.splitlines()
    headers: list[tuple[int, str]] = []
    for line_no, line in enumerate(lines):
        match = NOTE_HEADER_RE.match(line)
        if match:
            headers.append((line_no, match.group(1)))
    if not headers:
        return _join_without_trailing_blank(lines), []
    preamble = _join_without_trailing_blank(lines[: headers[0][0]])
    notes: list[Note] = []
    for position, (line_no, timestamp) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        notes.append(
            Note(
                index=position,
                timestamp=timestamp,
                content=_join_without_trailing_blank(lines[line_no + 1 : end]),
            )
        )
    return preamble, notes


def serialize_notes(preamble: str, notes: list[Note]) -> str:
    """Serialize preamble and notes back to ``notes.md`` text.

    Blocks are separated by exactly one blank line and the file ends with
    a single newline; empty input serializes to an empty string.
    """
    blocks: list[str] = []
    if preamble:
        blocks.append(preamble.rstrip("\n"))
    for note in notes:
        header = f"## {note.timestamp}"
        blocks.append(f"{header}\n{note.content.rstrip(chr(10))}" if note.content else header)
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _join_without_trailing_blank(lines: list[str]) -> str:
    """Join lines with newlines, dropping trailing blank lines."""
    kept = list(lines)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)
