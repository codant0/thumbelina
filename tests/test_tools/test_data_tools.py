"""Tests for data processing tools."""

from __future__ import annotations

import pytest

from thumbelina.tools.data_tools import analyze_text, parse_csv, parse_json, search_text


class TestParseJson:
    """Tests for the parse_json tool."""

    @pytest.mark.asyncio
    async def test_parse_simple_object(self):
        result = await parse_json.ainvoke({"text": '{"name": "Alice", "age": 30}'})
        assert "object" in result.lower() or "dict" in result.lower()
        assert "name" in result
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_parse_array(self):
        result = await parse_json.ainvoke({"text": "[1, 2, 3]"})
        assert "array" in result.lower() or "list" in result.lower()

    @pytest.mark.asyncio
    async def test_parse_nested(self):
        data = '{"user": {"name": "Bob", "tags": ["a", "b"]}}'
        result = await parse_json.ainvoke({"text": data})
        assert "user" in result
        assert "tags" in result

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self):
        result = await parse_json.ainvoke({"text": "not json"})
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_parse_empty_object(self):
        result = await parse_json.ainvoke({"text": "{}"})
        assert "empty" in result.lower() or "object" in result.lower()


class TestParseCsv:
    """Tests for the parse_csv tool."""

    @pytest.mark.asyncio
    async def test_parse_simple_csv(self):
        csv_text = "name,age\nAlice,30\nBob,25"
        result = await parse_csv.ainvoke({"text": csv_text})
        assert "name" in result
        assert "age" in result
        assert "Rows: 2" in result
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_parse_csv_column_count(self):
        csv_text = "a,b,c\n1,2,3"
        result = await parse_csv.ainvoke({"text": csv_text})
        assert "Columns (3)" in result

    @pytest.mark.asyncio
    async def test_parse_csv_preview_limit(self):
        header = "id,value\n"
        rows = "\n".join(f"{i},val{i}" for i in range(20))
        result = await parse_csv.ainvoke({"text": header + rows})
        assert "Rows: 20" in result
        assert "First 5 rows" in result

    @pytest.mark.asyncio
    async def test_parse_empty_csv(self):
        result = await parse_csv.ainvoke({"text": ""})
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_parse_csv_header_only(self):
        result = await parse_csv.ainvoke({"text": "a,b,c"})
        assert "Columns (3)" in result
        assert "Rows: 0" in result


class TestAnalyzeText:
    """Tests for the analyze_text tool."""

    @pytest.mark.asyncio
    async def test_word_count(self):
        result = await analyze_text.ainvoke({"text": "hello world foo bar"})
        assert "Words: 4" in result

    @pytest.mark.asyncio
    async def test_line_count(self):
        result = await analyze_text.ainvoke({"text": "line1\nline2\nline3"})
        assert "Lines: 3" in result

    @pytest.mark.asyncio
    async def test_character_count(self):
        result = await analyze_text.ainvoke({"text": "abc"})
        assert "Characters: 3" in result

    @pytest.mark.asyncio
    async def test_top_words(self):
        text = "apple banana apple cherry apple banana apple"
        result = await analyze_text.ainvoke({"text": text})
        assert "Top 10 words" in result
        # "apple" appears 4 times and should be first
        lines = result.splitlines()
        # Find the line with "apple"
        apple_line = [line for line in lines if "apple" in line]
        assert len(apple_line) > 0
        assert "4" in apple_line[0]

    @pytest.mark.asyncio
    async def test_empty_text(self):
        result = await analyze_text.ainvoke({"text": ""})
        assert "empty" in result.lower()


class TestSearchText:
    """Tests for the search_text tool."""

    @pytest.mark.asyncio
    async def test_simple_search(self):
        text = "hello world\nfoo bar\nhello again"
        result = await search_text.ainvoke({"text": text, "pattern": "hello"})
        assert "2 match" in result
        assert "Line 1" in result
        assert "Line 3" in result

    @pytest.mark.asyncio
    async def test_regex_search(self):
        text = "abc 123 def 456"
        result = await search_text.ainvoke({"text": text, "pattern": r"\d+"})
        assert "2 match" in result
        assert "123" in result
        assert "456" in result

    @pytest.mark.asyncio
    async def test_no_matches(self):
        result = await search_text.ainvoke({"text": "hello", "pattern": "xyz"})
        assert "no match" in result.lower()

    @pytest.mark.asyncio
    async def test_invalid_regex(self):
        result = await search_text.ainvoke({"text": "hello", "pattern": "[invalid"})
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_column_number(self):
        result = await search_text.ainvoke({"text": "abcXYZ", "pattern": "XYZ"})
        assert "Col 4" in result
