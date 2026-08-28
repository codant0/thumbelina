"""Tests for the web_search tool (Tavily / DuckDuckGo backends)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from thumbelina.config.models import WebSearchConfig
from thumbelina.tools.perception import (
    _search_duckduckgo,
    _search_tavily,
    make_web_search_tool,
)


def _config(provider: str = "tavily", api_key: str = "", enabled: bool = True) -> WebSearchConfig:
    return WebSearchConfig(provider=provider, api_key=api_key, enabled=enabled)  # type: ignore[arg-type]


def test_tool_name_is_web_search():
    tool = make_web_search_tool(_config())
    assert tool.name == "web_search"
    assert "query" in tool.args


@pytest.mark.asyncio
async def test_disabled_returns_message():
    tool = make_web_search_tool(_config(enabled=False))
    result = await tool.ainvoke({"query": "hello"})
    assert "disabled" in result


@pytest.mark.asyncio
async def test_tavily_without_key_returns_hint():
    tool = make_web_search_tool(_config(provider="tavily", api_key=""))
    result = await tool.ainvoke({"query": "hello"})
    assert "API key" in result


@pytest.mark.asyncio
async def test_tavily_uses_configured_key():
    tool = make_web_search_tool(_config(provider="tavily", api_key="cfg-key"))
    with patch(
        "thumbelina.tools.perception._search_tavily",
        return_value="ok",
    ) as mock_search:
        result = await tool.ainvoke({"query": "hello"})
    mock_search.assert_called_once_with("hello", "cfg-key")
    assert result == "ok"


@pytest.mark.asyncio
async def test_tavily_error_is_returned_gracefully():
    tool = make_web_search_tool(_config(provider="tavily", api_key="key"))
    with patch(
        "thumbelina.tools.perception._search_tavily",
        side_effect=RuntimeError("boom"),
    ):
        result = await tool.ainvoke({"query": "hello"})
    assert "Error searching Tavily" in result


@pytest.mark.asyncio
async def test_duckduckgo_dispatches():
    tool = make_web_search_tool(_config(provider="duckduckgo"))
    with patch(
        "thumbelina.tools.perception._search_duckduckgo",
        return_value="ddg ok",
    ) as mock_search:
        result = await tool.ainvoke({"query": "hello"})
    mock_search.assert_called_once_with("hello")
    assert result == "ddg ok"


@patch("httpx.post")
def test_search_tavily_formats_results(mock_post):
    mock_post.return_value.raise_for_status = lambda: None
    mock_post.return_value.json.return_value = {
        "answer": "A short answer.",
        "results": [
            {"title": "T1", "url": "https://ex.com/1", "content": "c1"},
            {"title": "T2", "url": "https://ex.com/2", "content": "c2"},
        ],
    }
    text = _search_tavily("q", "key")
    assert "A short answer." in text
    assert "T1" in text
    assert "https://ex.com/1" in text
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["api_key"] == "key"
    assert kwargs["json"]["query"] == "q"


@patch("httpx.post")
def test_search_tavily_empty(mock_post):
    mock_post.return_value.raise_for_status = lambda: None
    mock_post.return_value.json.return_value = {"results": []}
    assert _search_tavily("q", "key") == "No results found."


def test_search_duckduckgo_missing_dependency():
    with patch.dict("sys.modules", {"ddgs": None}):
        assert "not installed" in _search_duckduckgo("q")


def test_search_duckduckgo_formats_results():
    import types

    class FakeDDG:
        def __init__(self, *_a, **_k):
            pass

        def text(self, query, max_results):
            def gen():
                yield {"title": "D1", "href": "https://ddg.com/1", "body": "b1"}
                yield {"title": "D2", "url": "https://ddg.com/2", "body": "b2"}

            return gen()

    fake_module = types.ModuleType("ddgs")
    fake_module.DDGS = FakeDDG
    with patch.dict("sys.modules", {"ddgs": fake_module}):
        text = _search_duckduckgo("q")
    assert "D1" in text
    assert "https://ddg.com/1" in text
    assert "b2" in text
