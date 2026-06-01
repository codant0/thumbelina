"""Tests for thumbelina.llm.factory module."""

from __future__ import annotations

import pytest


class TestCreateProvider:
    """Tests for the create_provider factory function."""

    def test_create_openai_provider(self):
        from thumbelina.llm.factory import create_provider
        from thumbelina.llm.openai import OpenAIProvider

        provider = create_provider("openai", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_create_anthropic_provider(self):
        from thumbelina.llm.factory import create_provider
        from thumbelina.llm.anthropic import AnthropicProvider

        provider = create_provider("anthropic", api_key="test-key")
        assert isinstance(provider, AnthropicProvider)

    def test_create_ollama_provider(self):
        from thumbelina.llm.factory import create_provider
        from thumbelina.llm.ollama import OllamaProvider

        provider = create_provider("ollama")
        assert isinstance(provider, OllamaProvider)

    def test_case_insensitive_provider_name(self):
        from thumbelina.llm.factory import create_provider
        from thumbelina.llm.openai import OpenAIProvider

        provider = create_provider("OpenAI", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider_raises(self):
        from thumbelina.llm.factory import create_provider

        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("nonexistent", api_key="test")

    def test_passes_kwargs_to_provider(self):
        from thumbelina.llm.factory import create_provider
        from thumbelina.llm.openai import OpenAIProvider

        provider = create_provider("openai", api_key="my-key", model="gpt-3.5-turbo")
        assert isinstance(provider, OpenAIProvider)
        assert provider.model == "gpt-3.5-turbo"

    def test_create_with_config_dict(self):
        from thumbelina.llm.factory import create_provider
        from thumbelina.llm.openai import OpenAIProvider

        provider = create_provider("openai", api_key="test-key", model="gpt-4o")
        assert isinstance(provider, OpenAIProvider)

    def test_list_providers(self):
        from thumbelina.llm.factory import list_providers

        providers = list_providers()
        assert "openai" in providers
        assert "anthropic" in providers
        assert "ollama" in providers
