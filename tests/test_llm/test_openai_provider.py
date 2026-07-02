"""Tests for OpenAIProvider endpoint management methods."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from thumbelina.llm.base import SpeedTestResult
from thumbelina.llm.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_lists_models():
    provider = OpenAIProvider(api_key="test-key")
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}]}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        models = await provider.list_models(base_url="https://api.openai.com/v1")

    assert models == ["gpt-4o", "gpt-3.5-turbo"]


@pytest.mark.asyncio
async def test_openai_provider_speed_test_reachable():
    provider = OpenAIProvider(api_key="test-key")

    async def _fake_aiter_text():
        yield "{"
        yield "}"

    mock_response = MagicMock()
    mock_response.aiter_text = _fake_aiter_text
    mock_response.raise_for_status = AsyncMock()

    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient.stream", return_value=mock_context):
        result = await provider.speed_test(
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )

    assert isinstance(result, SpeedTestResult)
    assert result.reachable is True
    assert isinstance(result.latency_ms, int)
    assert isinstance(result.total_ms, int)
    assert result.total_ms >= result.latency_ms


@pytest.mark.asyncio
async def test_openai_provider_speed_test_unreachable():
    provider = OpenAIProvider(api_key="test-key")

    with patch(
        "httpx.AsyncClient.stream",
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = await provider.speed_test(
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )

    assert isinstance(result, SpeedTestResult)
    assert result.reachable is False
    assert result.error is not None
    assert "Connection refused" in result.error
