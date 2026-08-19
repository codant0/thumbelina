"""Data models for the TODO module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TodoItem:
    """A single checkbox item parsed from ``todolist.md``.

    ``remark`` is free-form Markdown (the per-item note) stored as blockquote
    lines immediately following the checkbox in the file; empty when absent.
    """

    index: int
    text: str
    done: bool
    remark: str = ""


@dataclass
class RawLine:
    """A non-checkbox line in ``todolist.md``, preserved verbatim."""

    text: str


@dataclass
class Note:
    """A note block parsed from ``notes.md``."""

    index: int
    timestamp: str  # "YYYY-MM-DD HH:MM"
    content: str
