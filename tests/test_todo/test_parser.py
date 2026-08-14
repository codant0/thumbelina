"""Tests for the TODO Markdown parser and data models."""

from __future__ import annotations

from thumbelina.todo.models import Note, RawLine, TodoItem
from thumbelina.todo.parser import (
    parse_notes,
    parse_todolist,
    serialize_notes,
    serialize_todolist,
)


class TestParseTodolist:
    """Tests for ``parse_todolist`` / ``serialize_todolist``."""

    def test_parse_todolist_checkbox_lines(self):
        """Checkbox lines (space / x / X) parse into TodoItem with correct text/done."""
        segments = parse_todolist("- [ ] 买牛奶\n- [x] 写周报\n- [X] 大写也可\n")

        assert len(segments) == 3
        first, second, third = segments
        assert isinstance(first, TodoItem)
        assert first.text == "买牛奶"
        assert first.done is False
        assert isinstance(second, TodoItem)
        assert second.text == "写周报"
        assert second.done is True
        assert isinstance(third, TodoItem)
        assert third.text == "大写也可"
        assert third.done is True

    def test_parse_todolist_preserves_raw_lines(self):
        """Non-checkbox lines are kept verbatim in order; round-trip is exact."""
        original = "# 标题\n\n- [ ] 买牛奶\n一些说明文字\n- [x] 写周报\n"

        segments = parse_todolist(original)

        assert [type(segment) for segment in segments] == [
            RawLine,
            RawLine,
            TodoItem,
            RawLine,
            TodoItem,
        ]
        assert isinstance(segments[0], RawLine)
        assert segments[0].text == "# 标题"
        assert isinstance(segments[1], RawLine)
        assert segments[1].text == ""
        assert isinstance(segments[3], RawLine)
        assert segments[3].text == "一些说明文字"
        # Round-trip: serializing the segments reproduces the original text.
        assert serialize_todolist(segments) == original

    def test_parse_todolist_empty(self):
        """Empty input yields an empty segment list."""
        assert parse_todolist("") == []
        assert serialize_todolist([]) == ""

    def test_todo_item_index(self):
        """TodoItem.index counts only checkbox lines, starting at 0."""
        segments = parse_todolist("# 标题\n- [ ] a\n说明\n- [x] b\n\n- [ ] c\n")

        items = [segment for segment in segments if isinstance(segment, TodoItem)]

        assert [item.text for item in items] == ["a", "b", "c"]
        assert [item.index for item in items] == [0, 1, 2]


class TestParseNotes:
    """Tests for ``parse_notes`` / ``serialize_notes``."""

    def test_parse_notes_blocks(self):
        """Two timestamp headers produce two notes; trailing blank lines are dropped."""
        text = "## 2026-08-14 21:30\n第一条随手记\n第二行内容\n\n## 2026-08-13 09:15\n更早的条目\n"

        preamble, notes = parse_notes(text)

        assert preamble == ""
        assert len(notes) == 2
        assert notes[0].index == 0
        assert notes[0].timestamp == "2026-08-14 21:30"
        assert notes[0].content == "第一条随手记\n第二行内容"
        assert notes[1].index == 1
        assert notes[1].timestamp == "2026-08-13 09:15"
        assert notes[1].content == "更早的条目"
        # Round-trip is exact (block-separating blank line belongs to no content).
        assert serialize_notes(preamble, notes) == text

    def test_parse_notes_preamble(self):
        """Content before the first header is the preamble and stays on top."""
        text = "# 随手记\n这里是说明文字\n\n## 2026-08-14 21:30\n内容\n"

        preamble, notes = parse_notes(text)

        assert preamble == "# 随手记\n这里是说明文字"
        assert len(notes) == 1

        serialized = serialize_notes(preamble, notes)
        assert serialized.startswith("# 随手记\n这里是说明文字\n")
        assert parse_notes(serialized) == (preamble, notes)

    def test_parse_notes_empty(self):
        """Empty input yields empty preamble and no notes."""
        preamble, notes = parse_notes("")

        assert preamble == ""
        assert notes == []
        assert serialize_notes("", []) == ""

    def test_serialize_notes_round_trip(self):
        """Serializing preamble + notes and re-parsing keeps the structure."""
        preamble = "# 随手记\n记录一些零碎的想法"
        notes = [
            Note(index=0, timestamp="2026-08-14 21:30", content="今天完成了 TODO 设计"),
            Note(index=1, timestamp="2026-08-13 09:15", content="早上的想法\n\n分两段"),
        ]

        serialized = serialize_notes(preamble, notes)

        assert serialized.endswith("\n")
        parsed_preamble, parsed_notes = parse_notes(serialized)
        assert parsed_preamble == preamble
        assert parsed_notes == notes
