"""Tests for web request tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.tools.perception import FetchUrlTool

fetch_url = FetchUrlTool()


@pytest.mark.asyncio
async def test_fetch_url_success():
    mock_response = MagicMock()
    mock_response.text = "hello"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_url.ainvoke({"url": "https://example.com"})
    assert result == "hello"


@pytest.mark.asyncio
async def test_fetch_url_not_installed():
    with patch.dict("sys.modules", {"httpx": None}):
        # httpx 为函数体内惰性导入,屏蔽 sys.modules 即可触发 ImportError 分支
        result = await fetch_url.ainvoke({"url": "https://example.com"})
        assert "not installed" in result
