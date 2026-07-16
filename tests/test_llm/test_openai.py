"""Tests for thumbelina.llm.openai module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOpenAIProvider:
    """Tests for the OpenAI LLM provider."""

    def test_is_llm_provider(self):
        from thumbelina.llm.base import LLMProvider
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")
        assert isinstance(provider, LLMProvider)

    def test_default_model(self):
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")
        assert provider.model == "gpt-4o"

    def test_custom_model(self):
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key", model="gpt-3.5-turbo")
        assert provider.model == "gpt-3.5-turbo"

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = "Hello from OpenAI"

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            result = await provider.chat([{"role": "user", "content": "hi"}])

        assert result == "Hello from OpenAI"

    @pytest.mark.asyncio
    async def test_chat_passes_messages_to_model(self):
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")

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
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")

        async def fake_stream(messages):
            for chunk in ["Hello", " from", " OpenAI"]:
                yield MagicMock(content=chunk)

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.astream = fake_stream
            chunks = []
            async for chunk in provider.stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

        assert chunks == ["Hello", " from", " OpenAI"]

    def test_sync_chat_returns_string(self):
        from thumbelina.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = "sync response"

        with patch.object(provider, "_chat_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            result = provider.chat_sync([{"role": "user", "content": "hi"}])

        assert result == "sync response"
