"""Tests for thumbelina.config.models module."""

from __future__ import annotations

import pytest


class TestLLMConfig:
    """Tests for LLMConfig model."""

    def test_default_values(self):
        from thumbelina.config.models import LLMConfig

        cfg = LLMConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o"
        assert cfg.api_key == ""

    def test_custom_values(self):
        from thumbelina.config.models import LLMConfig

        cfg = LLMConfig(provider="anthropic", model="claude-3", api_key="sk-test")
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-3"
        assert cfg.api_key == "sk-test"

    def test_invalid_provider_raises(self):
        from thumbelina.config.models import LLMConfig

        with pytest.raises(Exception):  # Pydantic validation error
            LLMConfig(provider="")


class TestMemoryConfig:
    """Tests for MemoryConfig model."""

    def test_default_values(self):
        from thumbelina.config.models import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.database_url == "sqlite:///thumbelina.db"

    def test_custom_values(self):
        from thumbelina.config.models import MemoryConfig

        cfg = MemoryConfig(database_url="postgresql://localhost/test")
        assert cfg.database_url == "postgresql://localhost/test"


class TestLoggingConfig:
    """Tests for LoggingConfig model."""

    def test_default_values(self):
        from thumbelina.config.models import LoggingConfig

        cfg = LoggingConfig()
        assert cfg.level == "INFO"

    def test_custom_values(self):
        from thumbelina.config.models import LoggingConfig

        cfg = LoggingConfig(level="DEBUG")
        assert cfg.level == "DEBUG"

    def test_invalid_level_raises(self):
        from thumbelina.config.models import LoggingConfig

        with pytest.raises(Exception):  # Pydantic validation error
            LoggingConfig(level="INVALID")


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_default_values(self):
        from thumbelina.config.models import AppConfig, LLMConfig, LoggingConfig, MemoryConfig

        cfg = AppConfig()
        assert isinstance(cfg.llm, LLMConfig)
        assert isinstance(cfg.memory, MemoryConfig)
        assert isinstance(cfg.logging, LoggingConfig)
        assert cfg.llm.provider == "openai"
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"
        assert cfg.logging.level == "INFO"

    def test_nested_config(self):
        from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig

        cfg = AppConfig(
            llm=LLMConfig(provider="anthropic", model="claude-3"),
            memory=MemoryConfig(database_url="postgresql://localhost/test"),
        )
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "claude-3"
        assert cfg.memory.database_url == "postgresql://localhost/test"

    def test_from_dict(self):
        from thumbelina.config.models import AppConfig

        data = {
            "llm": {"provider": "ollama", "model": "llama3"},
            "memory": {"database_url": "sqlite:///custom.db"},
            "logging": {"level": "DEBUG"},
        }
        cfg = AppConfig.model_validate(data)
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.model == "llama3"
        assert cfg.memory.database_url == "sqlite:///custom.db"
        assert cfg.logging.level == "DEBUG"

    def test_from_dict_partial(self):
        from thumbelina.config.models import AppConfig

        data = {"llm": {"provider": "anthropic"}}
        cfg = AppConfig.model_validate(data)
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "gpt-4o"  # default
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"  # default

    def test_to_dict(self):
        from thumbelina.config.models import AppConfig

        cfg = AppConfig()
        data = cfg.model_dump()
        assert isinstance(data, dict)
        assert "llm" in data
        assert "memory" in data
        assert "logging" in data
        assert data["llm"]["provider"] == "openai"
