"""Data models for the TODO module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TodoItem:
    """A single checkbox item parsed from ``todolist.md``."""

    index: int
    text: str
    done: bool


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
