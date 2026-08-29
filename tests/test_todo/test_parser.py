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

    def test_serialize_todolist_normalizes_trailing_newline(self):
        """Input without a trailing newline is normalized to end with one."""
        assert serialize_todolist(parse_todolist("- [ ] a")) == "- [ ] a\n"

    def test_parse_todolist_crlf(self):
        """Windows CRLF line endings parse identically to LF input."""
        crlf_segments = parse_todolist("- [ ] a\r\n- [x] b\r\n")
        lf_segments = parse_todolist("- [ ] a\n- [x] b\n")

        assert crlf_segments == lf_segments
        assert len(crlf_segments) == 2
        first, second = crlf_segments
        assert isinstance(first, TodoItem)
        assert first.text == "a"
        assert first.done is False
        assert isinstance(second, TodoItem)
        assert second.text == "b"
        assert second.done is True

    def test_parse_remark_single_line(self):
        """A blockquote line after a checkbox becomes the item's remark."""
        segments = parse_todolist("- [ ] 买牛奶\n> 记得买**脱脂**的\n- [ ] 写周报\n")

        assert len(segments) == 2
        first, second = segments
        assert isinstance(first, TodoItem)
        assert first.text == "买牛奶"
        assert first.remark == "记得买**脱脂**的"
        assert isinstance(second, TodoItem)
        assert second.remark == ""

    def test_parse_remark_multi_line(self):
        """Consecutive blockquote lines join into a multi-line remark."""
        segments = parse_todolist("- [ ] 买牛奶\n> 第一行说明\n> 第二行说明\n- [ ] 写周报\n")

        assert len(segments) == 2
        first, _ = segments
        assert isinstance(first, TodoItem)
        assert first.remark == "第一行说明\n第二行说明"

    def test_parse_remark_stops_at_non_blockquote(self):
        """A plain (non-blockquote) line ends the remark and becomes a raw line."""
        segments = parse_todolist("- [ ] 买牛奶\n> 说明\n一段普通文字\n- [ ] 写周报\n")

        assert len(segments) == 3
        assert isinstance(segments[0], TodoItem)
        assert segments[0].remark == "说明"
        assert isinstance(segments[1], RawLine)
        assert segments[1].text == "一段普通文字"

    def test_serialize_remark_round_trip(self):
        """A remark round-trips through serialize/parse identically."""
        original = "- [ ] 买牛奶\n> 第一行\n> 第二行\n- [x] 写周报\n"

        segments = parse_todolist(original)

        assert serialize_todolist(segments) == original

    def test_parse_todolist_groups_by_heading(self):
        """Checkbox items are tagged with the nearest preceding '# heading'."""
        segments = parse_todolist(
            "- [ ] 无分组条目\n# 工作\n- [ ] 写周报\n- [x] 开会\n# 学习\n- [ ] 读论文\n"
        )

        items = [segment for segment in segments if isinstance(segment, TodoItem)]

        assert [item.group for item in items] == [None, "工作", "工作", "学习"]
        assert [item.text for item in items] == ["无分组条目", "写周报", "开会", "读论文"]

    def test_parse_todolist_non_h1_headers_are_not_groups(self):
        """'## ...' and '### ...' lines never become group markers."""
        segments = parse_todolist("## 子标题\n- [ ] a\n### 三级标题\n- [ ] b\n")

        items = [segment for segment in segments if isinstance(segment, TodoItem)]

        assert [item.group for item in items] == [None, None]
        # The headers stay as raw lines (a '#' heading always needs a space).
        assert [type(segment) for segment in segments] == [RawLine, TodoItem, RawLine, TodoItem]

    def test_parse_todolist_blank_heading_is_not_a_group(self):
        """A bare '# ' line is preserved as a raw line, not a group marker."""
        segments = parse_todolist("# \n- [ ] a\n")

        items = [segment for segment in segments if isinstance(segment, TodoItem)]

        assert [item.group for item in items] == [None]
        assert segments[0] == RawLine(text="# ")

    def test_parse_todolist_heading_is_raw_line_round_trip(self):
        """Group headings remain verbatim raw lines; round-trip stays exact."""
        original = "# 工作\n\n- [ ] 写周报\n- [x] 开会\n\n# 学习\n- [ ] 读论文\n"

        segments = parse_todolist(original)

        assert serialize_todolist(segments) == original
        assert [type(segment) for segment in segments] == [
            RawLine,
            RawLine,
            TodoItem,
            TodoItem,
            RawLine,
            RawLine,
            TodoItem,
        ]

    def test_parse_todolist_group_remark_is_not_broken_by_heading(self):
        """A heading ends any pending remark but the next item keeps its group."""
        segments = parse_todolist("# 工作\n- [ ] a\n> 备注\n# 工作\n- [x] b\n")

        first, second = (s for s in segments if isinstance(s, TodoItem))

        assert first.remark == "备注"
        assert first.group == "工作"
        assert second.remark == ""
        assert second.group == "工作"


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
        text = "这里是说明文字\n\n## 2026-08-14 21:30\n内容\n"

        preamble, notes = parse_notes(text)

        assert preamble == "这里是说明文字"
        assert len(notes) == 1

        serialized = serialize_notes(preamble, notes)
        assert serialized.startswith("这里是说明文字\n")
        assert parse_notes(serialized) == (preamble, notes)

    def test_parse_notes_heading_in_preamble_is_group_marker(self):
        """A '# heading' in the preamble tags the following notes, not the text."""
        text = "# 随手记\n这里是说明文字\n\n## 2026-08-14 21:30\n内容\n"

        preamble, notes = parse_notes(text)

        # The heading is structural: it leaves the preamble and tags the note.
        assert preamble == "这里是说明文字"
        assert len(notes) == 1
        assert notes[0].group == "随手记"
        assert notes[0].content == "内容"

    def test_parse_notes_empty(self):
        """Empty input yields empty preamble and no notes."""
        preamble, notes = parse_notes("")

        assert preamble == ""
        assert notes == []
        assert serialize_notes("", []) == ""

    def test_serialize_notes_round_trip(self):
        """Serializing preamble + notes and re-parsing keeps the structure."""
        preamble = "这里记录一些零碎的想法"
        notes = [
            Note(index=0, timestamp="2026-08-14 21:30", content="今天完成了 TODO 设计"),
            Note(index=1, timestamp="2026-08-13 09:15", content="早上的想法\n\n分两段"),
        ]

        serialized = serialize_notes(preamble, notes)

        assert serialized.endswith("\n")
        parsed_preamble, parsed_notes = parse_notes(serialized)
        assert parsed_preamble == preamble
        assert parsed_notes == notes

    def test_parse_notes_groups_between_blocks(self):
        """A heading between blocks tags the following notes and never enters content."""
        text = (
            "# 项目A\n"
            "## 2026-08-14 21:30\n"
            "内容1\n"
            "\n"
            "## 2026-08-13 09:15\n"
            "内容2\n"
            "\n"
            "# 生活\n"
            "## 2026-08-10 09:00\n"
            "内容3\n"
        )

        preamble, notes = parse_notes(text)

        assert preamble == ""
        assert [note.group for note in notes] == ["项目A", "项目A", "生活"]
        assert [note.content for note in notes] == ["内容1", "内容2", "内容3"]

    def test_serialize_notes_group_marker_round_trip(self):
        """Group markers serialize on the first block of each group; round-trip is exact."""
        original = (
            "# 项目A\n"
            "## 2026-08-14 21:30\n"
            "内容1\n"
            "\n"
            "## 2026-08-13 09:15\n"
            "内容2\n"
            "\n"
            "# 生活\n"
            "## 2026-08-10 09:00\n"
            "内容3\n"
        )

        preamble, notes = parse_notes(original)
        serialized = serialize_notes(preamble, notes)

        assert serialized == original

    def test_parse_notes_heading_in_content_is_group_marker(self):
        """A heading at the end of a block still switches the group for later notes."""
        text = "## 2026-08-14 21:30\n内容1\n\n# 生活\n## 2026-08-13 09:15\n内容2\n"

        preamble, notes = parse_notes(text)

        assert [note.group for note in notes] == [None, "生活"]
        assert notes[0].content == "内容1"
        assert notes[1].content == "内容2"
