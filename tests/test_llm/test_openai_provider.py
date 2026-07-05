"""Tests for OpenAIProvider endpoint management methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from thumbelina.llm.base import ConnectionTestResult, SpeedTestResult
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
async def test_list_models_401_returns_empty():
    provider = OpenAIProvider(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(),
        response=mock_response,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        models = await provider.list_models(base_url="https://api.deepseek.com/v1")

    assert models == []


@pytest.mark.asyncio
async def test_list_models_404_returns_empty():
    provider = OpenAIProvider(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found",
        request=MagicMock(),
        response=mock_response,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        models = await provider.list_models(base_url="https://api.deepseek.com/v1")

    assert models == []


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


async def _fake_open_connection(*args, **kwargs):
    reader = MagicMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return reader, writer


@pytest.mark.asyncio
async def test_test_connection_success():
    provider = OpenAIProvider(api_key="test-key")

    mock_models_response = MagicMock()
    mock_models_response.status_code = 200
    mock_models_response.raise_for_status = MagicMock()
    mock_models_response.json.return_value = {"data": [{"id": "gpt-4o"}]}

    mock_chat_response = MagicMock()
    mock_chat_response.status_code = 200
    mock_chat_response.raise_for_status = MagicMock()
    mock_chat_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}

    async def _fake_get(*args, **kwargs):
        return mock_models_response

    async def _fake_post(*args, **kwargs):
        return mock_chat_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=_fake_get):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=_fake_post):
            with patch("asyncio.open_connection", side_effect=_fake_open_connection):
                result = await provider.test_connection(
                    base_url="https://api.openai.com/v1",
                )

    assert isinstance(result, ConnectionTestResult)
    assert result.reachable is True
    assert result.network_reachable is True
    assert result.auth_valid is True
    assert result.service_available is True
    assert result.details is not None
    assert result.details.network.ok is True
    assert result.details.auth.ok is True
    assert result.details.service.ok is True


@pytest.mark.asyncio
async def test_test_connection_auth_failure():
    provider = OpenAIProvider(api_key="test-key")

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(),
        response=mock_response,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        with patch("asyncio.open_connection", side_effect=_fake_open_connection):
            result = await provider.test_connection(
                base_url="https://api.openai.com/v1",
            )

    assert isinstance(result, ConnectionTestResult)
    assert result.reachable is False
    assert result.network_reachable is True
    assert result.auth_valid is False
    assert result.service_available is False
    assert result.details is not None
    assert result.details.auth.error is not None


@pytest.mark.asyncio
async def test_test_connection_network_failure():
    provider = OpenAIProvider(api_key="test-key")

    with patch(
        "asyncio.open_connection",
        side_effect=OSError("Connection refused"),
    ):
        result = await provider.test_connection(
            base_url="https://api.openai.com/v1",
        )

    assert isinstance(result, ConnectionTestResult)
    assert result.reachable is False
    assert result.network_reachable is False
    assert result.details is not None
    assert result.details.network.error is not None
    assert "Connection refused" in result.details.network.error
