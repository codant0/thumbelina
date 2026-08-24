"""Data models for the TODO module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TodoItem:
    """A single checkbox item parsed from ``todolist.md``.

    ``remark`` is free-form Markdown (the per-item note) stored as blockquote
    lines immediately following the checkbox in the file; empty when absent.
    ``group`` is the nearest preceding ``# heading`` line, or None when the
    item sits before any heading (the "ungrouped" bucket).
    """

    index: int
    text: str
    done: bool
    remark: str = ""
    group: str | None = None


@dataclass
class RawLine:
    """A non-checkbox line in ``todolist.md``, preserved verbatim."""

    text: str


@dataclass
class Note:
    """A note block parsed from ``notes.md``.

    ``group`` is the nearest preceding ``# heading`` line (a structural
    marker that never becomes part of the preamble or content), or None for
    notes before any heading.
    """

    index: int
    timestamp: str  # "YYYY-MM-DD HH:MM"
    content: str
    group: str | None = None
