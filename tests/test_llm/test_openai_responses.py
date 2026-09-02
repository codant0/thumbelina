"""Tests for the OpenAI Responses API provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_openai import ChatOpenAI

from thumbelina.llm.base import ConnectionTestResult, SpeedTestResult
from thumbelina.llm.factory import create_provider
from thumbelina.llm.openai import OpenAIProvider
from thumbelina.llm.openai_responses import OpenAIResponsesProvider


class TestOpenAIResponsesBasics:
    def test_is_openai_provider_subclass(self):
        provider = OpenAIResponsesProvider(api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_factory_registration(self):
        provider = create_provider("openai-responses", api_key="test-key")
        assert isinstance(provider, OpenAIResponsesProvider)
        assert create_provider("OpenAI-Responses", api_key="k", model="gpt-5-pro").model == (
            "gpt-5-pro"
        )


class TestOpenAIResponsesChatModel:
    def test_uses_responses_api(self):
        provider = OpenAIResponsesProvider(api_key="test-key", base_url="https://api.openai.com/v1")
        model = provider.chat_model
        assert isinstance(model, ChatOpenAI)
        assert model.use_responses_api is True
        assert model.openai_api_base == "https://api.openai.com/v1"

    def test_no_minimax_extra_body(self):
        """MiniMax 私有 reasoning_split 不透传到 Responses 通道。"""
        provider = OpenAIResponsesProvider(api_key="test-key", base_url="https://api.openai.com/v1")
        assert not provider.chat_model.extra_body

    def test_reasoning_effort_forwarded(self):
        provider = OpenAIResponsesProvider(api_key="test-key", reasoning_effort="high")
        assert provider.chat_model.reasoning_effort == "high"

    def test_kwargs_passthrough(self):
        provider = OpenAIResponsesProvider(api_key="test-key", max_retries=3)
        assert provider.chat_model.max_retries == 3


class TestOpenAIResponsesProbe:
    @pytest.mark.asyncio
    async def test_probe_chat_hits_responses_path(self):
        provider = OpenAIResponsesProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            resp = await provider._probe_chat(
                "https://api.openai.com/v1", {"Authorization": "Bearer k"}, "gpt-5-pro"
            )

        assert resp is mock_response
        assert mock_post.call_args[0][0] == "https://api.openai.com/v1/responses"
        assert mock_post.call_args[1]["json"] == {
            "model": "gpt-5-pro",
            "input": "hi",
            "max_output_tokens": 1,
            "stream": False,
        }

    @pytest.mark.asyncio
    async def test_probe_chat_404_raises_actionable_hint(self):
        provider = OpenAIResponsesProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RuntimeError, match="Responses API"):
                await provider._probe_chat(
                    "https://api.openai.com/v1", {"Authorization": "Bearer k"}, "gpt-5-pro"
                )

    @pytest.mark.asyncio
    async def test_probe_chat_405_raises_actionable_hint(self):
        provider = OpenAIResponsesProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 405

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RuntimeError, match="Chat Completions"):
                await provider._probe_chat(
                    "https://api.openai.com/v1", {"Authorization": "Bearer k"}, "gpt-5-pro"
                )


async def _fake_open_connection(*args, **kwargs):
    reader = MagicMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return reader, writer


class TestOpenAIResponsesTestConnection:
    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        provider = OpenAIResponsesProvider(api_key="test-key")

        mock_models_response = MagicMock()
        mock_models_response.status_code = 200
        mock_models_response.raise_for_status = MagicMock()
        mock_models_response.json.return_value = {"data": [{"id": "gpt-5-pro"}]}

        mock_probe_response = MagicMock()
        mock_probe_response.status_code = 200
        mock_probe_response.raise_for_status = MagicMock()

        async def _fake_get(*args, **kwargs):
            return mock_models_response

        async def _fake_post(*args, **kwargs):
            return mock_probe_response

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

    @pytest.mark.asyncio
    async def test_test_connection_reports_missing_responses_endpoint(self):
        """端点只支持 chat/completions 时，给出可操作的错误提示。"""
        provider = OpenAIResponsesProvider(api_key="test-key")

        mock_models_response = MagicMock()
        mock_models_response.status_code = 200
        mock_models_response.raise_for_status = MagicMock()
        mock_models_response.json.return_value = {"data": [{"id": "gpt-4o"}]}

        mock_404_response = MagicMock()
        mock_404_response.status_code = 404

        async def _fake_get(*args, **kwargs):
            return mock_models_response

        async def _fake_post(*args, **kwargs):
            return mock_404_response

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=_fake_get):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=_fake_post):
                with patch("asyncio.open_connection", side_effect=_fake_open_connection):
                    result = await provider.test_connection(
                        base_url="https://proxy.example.com/v1",
                        model="gpt-4o",
                    )

        assert isinstance(result, ConnectionTestResult)
        assert result.reachable is False
        assert result.service_available is False
        assert result.error is not None
        assert "Responses API" in result.error

    @pytest.mark.asyncio
    async def test_test_connection_auth_failure(self):
        provider = OpenAIResponsesProvider(api_key="test-key")

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


class TestOpenAIResponsesSpeedTest:
    @pytest.mark.asyncio
    async def test_speed_test_reachable(self):
        provider = OpenAIResponsesProvider(api_key="test-key")

        async def _fake_aiter_text():
            yield "event: response.created"
            yield "data: {...}"

        mock_response = MagicMock()
        mock_response.aiter_text = _fake_aiter_text
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient.stream", return_value=mock_context) as mock_stream:
            result = await provider.speed_test(
                model="gpt-5-pro",
                base_url="https://api.openai.com/v1",
            )

        assert isinstance(result, SpeedTestResult)
        assert result.reachable is True
        assert isinstance(result.latency_ms, int)
        assert result.total_ms >= result.latency_ms
        assert mock_stream.call_args[0][1] == "https://api.openai.com/v1/responses"
        assert mock_stream.call_args[1]["json"]["max_output_tokens"] == 1
        assert mock_stream.call_args[1]["json"]["stream"] is True

    @pytest.mark.asyncio
    async def test_speed_test_unreachable(self):
        provider = OpenAIResponsesProvider(api_key="test-key")

        with patch(
            "httpx.AsyncClient.stream",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await provider.speed_test(
                model="gpt-5-pro",
                base_url="https://api.openai.com/v1",
            )

        assert isinstance(result, SpeedTestResult)
        assert result.reachable is False
        assert result.error is not None
        assert "Connection refused" in result.error
