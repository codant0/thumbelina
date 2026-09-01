"""Tests for OpenAIProvider endpoint management methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_openai import ChatOpenAI

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
async def test_test_connection_default_model_400_falls_back_to_listed_model():
    provider = OpenAIProvider(api_key="test-key")

    mock_models_response = MagicMock()
    mock_models_response.status_code = 200
    mock_models_response.raise_for_status = MagicMock()
    mock_models_response.json.return_value = {"data": [{"id": "mimo-model"}]}

    bad_chat_response = MagicMock()
    bad_chat_response.status_code = 400
    bad_chat_response.text = '{"error":{"message":"model not found"}}'
    bad_chat_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400 Bad Request",
        request=MagicMock(),
        response=bad_chat_response,
    )

    good_chat_response = MagicMock()
    good_chat_response.status_code = 200
    good_chat_response.raise_for_status = MagicMock()
    good_chat_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}

    calls = []

    async def _fake_get(*args, **kwargs):
        return mock_models_response

    async def _fake_post(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return bad_chat_response
        return good_chat_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=_fake_get):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=_fake_post):
            with patch("asyncio.open_connection", side_effect=_fake_open_connection):
                result = await provider.test_connection(
                    base_url="https://token-plan-cn.xiaomimimo.com/v1",
                )

    assert isinstance(result, ConnectionTestResult)
    assert result.reachable is True
    assert result.network_reachable is True
    assert result.auth_valid is True
    assert result.service_available is True


@pytest.mark.asyncio
async def test_test_connection_includes_response_body_on_400():
    provider = OpenAIProvider(api_key="test-key")

    mock_models_response = MagicMock()
    mock_models_response.status_code = 200
    mock_models_response.raise_for_status = MagicMock()
    mock_models_response.json.return_value = {"data": []}

    bad_chat_response = MagicMock()
    bad_chat_response.status_code = 400
    bad_chat_response.text = '{"error":{"message":"invalid model"}}'
    bad_chat_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400 Bad Request",
        request=MagicMock(),
        response=bad_chat_response,
    )

    async def _fake_get(*args, **kwargs):
        return mock_models_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=_fake_get):
        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bad_chat_response
        ):
            with patch("asyncio.open_connection", side_effect=_fake_open_connection):
                result = await provider.test_connection(
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o",
                )

    assert isinstance(result, ConnectionTestResult)
    assert result.reachable is False
    assert result.service_available is False
    assert result.error is not None
    assert "invalid model" in result.error


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


def test_chat_model_preserves_reasoning_content_deltas():
    """OpenAI-compatible reasoning deltas must survive chunk conversion."""
    from langchain_core.messages import AIMessageChunk

    provider = OpenAIProvider(api_key="test-key", model="deepseek-chat")
    model = provider.chat_model

    raw_chunk = {
        "id": "cmpl-1",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Let me think step by step...",
                },
                "finish_reason": None,
            }
        ],
    }
    generation = model._convert_chunk_to_generation_chunk(raw_chunk, AIMessageChunk, None)
    assert generation is not None
    assert generation.message.additional_kwargs["reasoning_content"] == (
        "Let me think step by step..."
    )


def test_chat_model_plain_chunks_unchanged():
    """Regular content deltas should pass through untouched."""
    from langchain_core.messages import AIMessageChunk

    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    model = provider.chat_model

    raw_chunk = {
        "id": "cmpl-2",
        "object": "chat.completion.chunk",
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "content": "Hello"}, "finish_reason": None}
        ],
    }
    generation = model._convert_chunk_to_generation_chunk(raw_chunk, AIMessageChunk, None)
    assert generation is not None
    assert generation.message.content == "Hello"
    assert "reasoning_content" not in generation.message.additional_kwargs


def test_chat_model_forces_stream_usage_for_custom_base_url():
    """自定义 base_url 时流式必须请求 usage(否则 KV 缓存字段拿不到)。"""
    provider = OpenAIProvider(
        api_key="test-key", model="deepseek-chat", base_url="https://api.deepseek.com/v1"
    )
    model = provider.chat_model
    assert isinstance(model, ChatOpenAI)
    assert model.stream_usage is True


def test_chat_model_stream_usage_can_be_overridden():
    provider = OpenAIProvider(
        api_key="test-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        stream_usage=False,
    )
    assert provider.chat_model.stream_usage is False


def test_chat_model_defaults_reasoning_split_extra_body():
    """默认透传 reasoning_split=true(MiniMax 思考流拆分到 reasoning_details)。"""
    provider = OpenAIProvider(
        api_key="test-key", model="deepseek-chat", base_url="https://api.deepseek.com/v1"
    )
    model = provider.chat_model
    assert isinstance(model, ChatOpenAI)
    assert model.extra_body == {"reasoning_split": True}


def test_chat_model_extra_body_can_be_overridden():
    provider = OpenAIProvider(
        api_key="test-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        extra_body={"reasoning_split": False},
    )
    assert provider.chat_model.extra_body == {"reasoning_split": False}


def test_chat_model_preserves_raw_usage_in_response_metadata():
    """独立 usage 尾块(choices 为空)必须把原始 usage 透传到 response_metadata。

    langchain-openai 只保留归一化 usage_metadata,DeepSeek 的
    prompt_cache_hit_tokens 等字段会被丢弃;子类需透传原始 usage。
    """
    from langchain_core.messages import AIMessageChunk

    provider = OpenAIProvider(api_key="test-key", model="deepseek-chat")
    model = provider.chat_model

    raw_chunk = {
        "id": "cmpl-3",
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 45,
            "prompt_cache_hit_tokens": 900,
            "prompt_cache_miss_tokens": 300,
        },
    }
    generation = model._convert_chunk_to_generation_chunk(raw_chunk, AIMessageChunk, None)
    assert generation is not None
    token_usage = generation.message.response_metadata["token_usage"]
    assert token_usage["prompt_cache_hit_tokens"] == 900
    assert token_usage["prompt_cache_miss_tokens"] == 300
