"""Tests for thumbelina.llm.ollama module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOllamaProvider:
    """Tests for the Ollama LLM provider."""

    def test_is_llm_provider(self):
        from thumbelina.llm.base import LLMProvider
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()
        assert isinstance(provider, LLMProvider)

    def test_default_model(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()
        assert provider.model == "llama3"

    def test_custom_model(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider(model="mistral")
        assert provider.model == "mistral"

    def test_default_base_url(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()
        assert provider.base_url == "http://localhost:11434"

    def test_custom_base_url(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider(base_url="http://gpu-server:11434")
        assert provider.base_url == "http://gpu-server:11434"

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()

        mock_response = MagicMock()
        mock_response.content = "Hello from Ollama"

        with patch.object(provider, "_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            result = await provider.chat([{"role": "user", "content": "hi"}])

        assert result == "Hello from Ollama"

    @pytest.mark.asyncio
    async def test_chat_passes_messages_to_model(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()

        mock_response = MagicMock()
        mock_response.content = "ok"

        with patch.object(provider, "_model") as mock_model:
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
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()

        async def fake_stream(messages):
            for chunk in ["Hello", " from", " Ollama"]:
                yield MagicMock(content=chunk)

        with patch.object(provider, "_model") as mock_model:
            mock_model.astream = fake_stream
            chunks = []
            async for chunk in provider.stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

        assert chunks == ["Hello", " from", " Ollama"]

    def test_sync_chat_returns_string(self):
        from thumbelina.llm.ollama import OllamaProvider

        provider = OllamaProvider()

        mock_response = MagicMock()
        mock_response.content = "sync response"

        with patch.object(provider, "_model") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            result = provider.chat_sync([{"role": "user", "content": "hi"}])

        assert result == "sync response"
