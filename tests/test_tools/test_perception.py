"""感知工具迁移后行为回归: 名称、schema、错误文案不变。"""
from __future__ import annotations

import pytest

from thumbelina.tools import perception as p
from thumbelina.tools.base import ToolCategory


@pytest.mark.asyncio
async def test_read_file_missing(tmp_path):
    t = p.ReadFileTool()
    assert await t._arun(path=str(tmp_path / "nope")) == f"Error: File not found: {tmp_path / 'nope'}"


@pytest.mark.asyncio
async def test_read_file_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    assert await p.ReadFileTool()._arun(path=str(f)) == "hello"


@pytest.mark.asyncio
async def test_list_directory(tmp_path):
    (tmp_path / "x").write_text("1", encoding="utf-8")
    assert "[f] x" in await p.ListDirectoryTool()._arun(path=str(tmp_path))


@pytest.mark.asyncio
async def test_search_files_hit(tmp_path):
    (tmp_path / "a.txt").write_text("needle here", encoding="utf-8")
    result = await p.SearchFilesTool()._arun(pattern="needle", path=str(tmp_path))
    assert "a.txt:1: needle here" in result


@pytest.mark.asyncio
async def test_parse_json_invalid():
    assert (await p.ParseJsonTool()._arun(text="{bad")).startswith("Error: Invalid JSON")


@pytest.mark.asyncio
async def test_analyze_text_counts():
    out = await p.AnalyzeTextTool()._arun(text="aa bb aa")
    assert "Words: 3" in out


@pytest.mark.asyncio
async def test_search_text_matches():
    out = await p.SearchTextTool()._arun(text="a\nbb", pattern="b+")
    assert "Found 1 match" in out


@pytest.mark.asyncio
async def test_parse_csv_columns():
    out = await p.ParseCsvTool()._arun(text="h1,h2\n1,2\n")
    assert "Columns (2): h1, h2" in out


@pytest.mark.asyncio
async def test_fetch_url_error(monkeypatch):
    import httpx

    def _fail(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", _fail)
    out = await p.FetchUrlTool()._arun(url="http://x")
    assert out.startswith("Error")


def test_categories():
    assert p.ReadFileTool().category == ToolCategory.PERCEPTION


def test_perception_tools_names():
    names = {t.name for t in p.perception_tools()}
    assert names == {
        "read_file", "list_directory", "search_files", "fetch_url",
        "parse_json", "parse_csv", "analyze_text", "search_text",
    }
    # web_search 受 config 门控,默认不在列表中
    assert "web_search" not in names


@pytest.mark.asyncio
async def test_read_file_ainvoke_lifecycle(tmp_path):
    """经 langchain ainvoke 入口走完整生命周期(security_review→_execute→self_verify)。"""
    f = tmp_path / "life.txt"
    f.write_text("via ainvoke", encoding="utf-8")
    out = await p.ReadFileTool().ainvoke({"path": str(f)})
    assert out == "via ainvoke"
