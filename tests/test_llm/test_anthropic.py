"""Tests for thumbelina.llm.anthropic module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from thumbelina.llm.anthropic import AnthropicProvider
from thumbelina.llm.base import ConnectionTestResult, SpeedTestResult


class TestAnthropicProvider:
    """Tests for the Anthropic LLM provider."""

    def test_is_llm_provider(self):
        from thumbelina.llm.anthropic import AnthropicProvider
        from thumbelina.llm.base import LLMProvider

        provider = AnthropicProvider(api_key="test-key")
        assert isinstance(provider, LLMProvider)

    def test_default_model(self):
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")
        assert provider.model == "claude-sonnet-4-20250514"

    def test_custom_model(self):
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key", model="claude-3-haiku-20240307")
        assert provider.model == "claude-3-haiku-20240307"

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = "Hello from Anthropic"

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            result = await provider.chat([{"role": "user", "content": "hi"}])

        assert result == "Hello from Anthropic"

    @pytest.mark.asyncio
    async def test_chat_passes_messages_to_model(self):
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = "ok"

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            await provider.chat(
                [
                    {"role": "system", "content": "behave"},
                    {"role": "user", "content": "hello"},
                ]
            )

            called_messages = mock_model.ainvoke.call_args[0][0]
            assert len(called_messages) == 2

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")

        async def fake_stream(messages):
            for chunk in ["Hello", " from", " Anthropic"]:
                yield MagicMock(content=chunk)

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.astream = fake_stream
            chunks = []
            async for chunk in provider.stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

        assert chunks == ["Hello", " from", " Anthropic"]

    def test_sync_chat_returns_string(self):
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = "sync response"

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            result = provider.chat_sync([{"role": "user", "content": "hi"}])

        assert result == "sync response"


class TestAnthropicUrlNormalization:
    """base_url 双向归一化：SDK 不带 /v1，原生 HTTP 探测带 /v1。"""

    def test_empty_path_gains_v1_for_api_only(self):
        api_url, sdk_base_url = AnthropicProvider._normalize_urls("https://proxy.example.com")
        assert api_url == "https://proxy.example.com/v1"
        assert sdk_base_url == "https://proxy.example.com"

    def test_v1_suffix_stripped_for_sdk(self):
        api_url, sdk_base_url = AnthropicProvider._normalize_urls("https://proxy.example.com/v1")
        assert api_url == "https://proxy.example.com/v1"
        assert sdk_base_url == "https://proxy.example.com"

    def test_trailing_slash_handled(self):
        api_url, sdk_base_url = AnthropicProvider._normalize_urls("https://proxy.example.com/v1/")
        assert api_url == "https://proxy.example.com/v1"
        assert sdk_base_url == "https://proxy.example.com"

    def test_nested_v1_path(self):
        api_url, sdk_base_url = AnthropicProvider._normalize_urls(
            "https://proxy.example.com/api/v1"
        )
        assert api_url == "https://proxy.example.com/api/v1"
        assert sdk_base_url == "https://proxy.example.com/api"

    def test_other_path_kept_verbatim(self):
        api_url, sdk_base_url = AnthropicProvider._normalize_urls(
            "https://proxy.example.com/anthropic"
        )
        assert api_url == "https://proxy.example.com/anthropic"
        assert sdk_base_url == "https://proxy.example.com/anthropic"

    def test_none_defaults_to_official_host(self):
        api_url, sdk_base_url = AnthropicProvider._normalize_urls(None)
        assert api_url == "https://api.anthropic.com/v1"
        assert sdk_base_url == "https://api.anthropic.com"


class TestAnthropicChatModelBaseUrl:
    """chat_model 传给 ChatAnthropic 的 base_url 不能带 /v1。"""

    def test_strips_v1_suffix(self):
        provider = AnthropicProvider(api_key="test-key", base_url="https://proxy.example.com/v1")
        model = provider.chat_model
        assert model.anthropic_api_url == "https://proxy.example.com"

    def test_keeps_host_without_v1(self):
        provider = AnthropicProvider(api_key="test-key", base_url="https://proxy.example.com")
        model = provider.chat_model
        assert model.anthropic_api_url == "https://proxy.example.com"

    def test_no_base_url_uses_sdk_default(self):
        provider = AnthropicProvider(api_key="test-key")
        model = provider.chat_model
        assert model.anthropic_api_url == "https://api.anthropic.com"

    def test_extra_kwargs_still_forwarded(self):
        provider = AnthropicProvider(api_key="test-key", max_tokens=2048)
        model = provider.chat_model
        assert model.max_tokens == 2048


class TestAnthropicListModels:
    @pytest.mark.asyncio
    async def test_list_models_success(self):
        provider = AnthropicProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"id": "claude-sonnet-4-20250514"}, {"id": "claude-3-haiku-20240307"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response
        ) as mock_get:
            models = await provider.list_models(base_url="https://api.anthropic.com")

        assert models == ["claude-sonnet-4-20250514", "claude-3-haiku-20240307"]
        # 原生探测必须打到带 /v1 的地址
        assert mock_get.call_args[0][0] == "https://api.anthropic.com/v1/models"
        assert mock_get.call_args[1]["headers"]["x-api-key"] == "test-key"
        assert mock_get.call_args[1]["headers"]["anthropic-version"] == "2023-06-01"

    @pytest.mark.asyncio
    async def test_list_models_404_returns_empty(self):
        provider = AnthropicProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            models = await provider.list_models(base_url="https://proxy.example.com/v1")

        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_auth_error_returns_empty(self):
        provider = AnthropicProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            models = await provider.list_models()

        assert models == []


class TestAnthropicSpeedTest:
    @pytest.mark.asyncio
    async def test_speed_test_reachable(self):
        provider = AnthropicProvider(api_key="test-key")

        async def _fake_aiter_text():
            yield "event: message_start"
            yield "data: {...}"

        mock_response = MagicMock()
        mock_response.aiter_text = _fake_aiter_text
        mock_response.raise_for_status = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient.stream", return_value=mock_context) as mock_stream:
            result = await provider.speed_test(
                model="claude-sonnet-4-20250514",
                base_url="https://api.anthropic.com",
            )

        assert isinstance(result, SpeedTestResult)
        assert result.reachable is True
        assert isinstance(result.latency_ms, int)
        assert result.total_ms >= result.latency_ms
        assert mock_stream.call_args[0][1] == "https://api.anthropic.com/v1/messages"
        payload = mock_stream.call_args[1]["json"]
        assert payload["max_tokens"] == 1
        assert payload["stream"] is True
        assert payload["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_speed_test_unreachable(self):
        provider = AnthropicProvider(api_key="test-key")

        with patch(
            "httpx.AsyncClient.stream",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await provider.speed_test(
                model="claude-sonnet-4-20250514",
                base_url="https://api.anthropic.com",
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


class TestAnthropicTestConnection:
    @pytest.mark.asyncio
    async def test_accepts_base_url_with_or_without_v1(self):
        """两种 base_url 习惯都必须打到 <host>/v1/messages。"""
        for base_url in ("https://proxy.example.com", "https://proxy.example.com/v1"):
            provider = AnthropicProvider(api_key="test-key")

            mock_models_response = MagicMock()
            mock_models_response.status_code = 400  # 非鉴权失败即可过 Level 2
            mock_models_response.raise_for_status = MagicMock()

            mock_messages_response = MagicMock()
            mock_messages_response.status_code = 200
            mock_messages_response.raise_for_status = MagicMock()

            posted_urls: list[str] = []

            async def _fake_get(*args, **kwargs):
                return mock_models_response

            async def _fake_post(url, *args, **kwargs):
                posted_urls.append(url)
                return mock_messages_response

            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=_fake_get):
                with patch(
                    "httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=_fake_post
                ):
                    with patch("asyncio.open_connection", side_effect=_fake_open_connection):
                        result = await provider.test_connection(base_url=base_url)

            assert isinstance(result, ConnectionTestResult)
            assert result.reachable is True
            assert posted_urls == ["https://proxy.example.com/v1/messages"]
