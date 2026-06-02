"""Tests for natural language time parser."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from thumbelina.scheduler.time_parser import TimeParser


@pytest.fixture
def parser():
    """Create a TimeParser."""
    return TimeParser()


class TestTimeParser:
    """Tests for the TimeParser class."""

    def test_parser_class_exists(self):
        """TimeParser should be importable."""
        assert TimeParser is not None

    def test_parser_creates_instance(self):
        """Should create a TimeParser."""
        p = TimeParser()
        assert p is not None

    def test_parse_relative_time_tomorrow(self, parser):
        """Should parse '明天'."""
        result = parser.parse("明天")
        assert result is not None
        expected = datetime.now() + timedelta(days=1)
        assert result.date() == expected.date()

    def test_parse_relative_time_next_week(self, parser):
        """Should parse '下周'."""
        result = parser.parse("下周")
        assert result is not None
        assert result > datetime.now()

    def test_parse_empty_string(self, parser):
        """Should return None for empty string."""
        result = parser.parse("")
        assert result is None

    def test_parse_none(self, parser):
        """Should return None for None."""
        result = parser.parse(None)
        assert result is None

    def test_parse_invalid_string(self, parser):
        """Should return None for unparseable string."""
        result = parser.parse("xyzabc123")
        assert result is None

    def test_parse_english_tomorrow(self, parser):
        """Should parse 'tomorrow'."""
        result = parser.parse("tomorrow")
        assert result is not None
        expected = datetime.now() + timedelta(days=1)
        assert result.date() == expected.date()

    def test_parse_english_next_week(self, parser):
        """Should parse 'next week'."""
        result = parser.parse("next week")
        assert result is not None
        assert result > datetime.now()

    def test_parse_english_with_time(self, parser):
        """Should parse 'tomorrow at 3pm'."""
        result = parser.parse("tomorrow at 3pm")
        assert result is not None
        assert result.hour == 15

    def test_parse_recurring_daily(self, parser):
        """Should detect recurring pattern '每天'."""
        result = parser.parse_recurring("每天")
        assert result is not None
        assert result["frequency"] == "daily"
        assert result["time"] is None

    def test_parse_recurring_weekly(self, parser):
        """Should detect recurring pattern '每周'."""
        result = parser.parse_recurring("每周")
        assert result is not None
        assert result["frequency"] == "weekly"
        assert result["time"] is None

    def test_parse_recurring_english_daily(self, parser):
        """Should detect recurring pattern 'every day'."""
        result = parser.parse_recurring("every day at 9am")
        assert result is not None
        assert result["frequency"] == "daily"

    def test_parse_recurring_empty(self, parser):
        """Should return None for empty recurring."""
        result = parser.parse_recurring("")
        assert result is None

    def test_parse_recurring_no_pattern(self, parser):
        """Should return None for non-recurring text."""
        result = parser.parse_recurring("明天")
        assert result is None
