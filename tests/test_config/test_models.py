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

    def test_context_window_default(self):
        from thumbelina.config.models import LLMConfig

        cfg = LLMConfig()
        assert cfg.context_window == "128K"
        assert cfg.context_window_tokens == 128_000

    @pytest.mark.parametrize(
        ("raw", "expected_tokens"),
        [
            ("128K", 128_000),
            ("1M", 1_000_000),
            ("128k", 128_000),
            ("2m", 2_000_000),
            ("200000", 200_000),
            (200000, 200_000),
            (" 64K ", 64_000),
        ],
    )
    def test_context_window_parsing(self, raw, expected_tokens):
        from thumbelina.config.models import LLMConfig

        cfg = LLMConfig(context_window=raw)
        assert cfg.context_window_tokens == expected_tokens

    @pytest.mark.parametrize("raw", ["", "abc", "12X", "-5", "0", "1.5M", "K", None])
    def test_context_window_invalid_formats_raise(self, raw):
        from thumbelina.config.models import LLMConfig

        with pytest.raises(Exception):  # Pydantic validation error
            LLMConfig(context_window=raw)


class TestContextWindowParsing:
    """共享 parse_context_window() 辅助函数的测试。"""

    def test_plain_int_passthrough(self):
        from thumbelina.config.models import parse_context_window

        assert parse_context_window(4096) == 4096

    def test_suffixes_are_case_insensitive(self):
        from thumbelina.config.models import parse_context_window

        assert parse_context_window("128K") == 128_000
        assert parse_context_window("128k") == 128_000
        assert parse_context_window("1M") == 1_000_000
        assert parse_context_window("1m") == 1_000_000

    def test_invalid_values_raise(self):
        from thumbelina.config.models import parse_context_window

        for bad in ["", "abc", "12X", "-5", "0K", "1.5M", True, ["128K"]]:
            with pytest.raises(ValueError):
                parse_context_window(bad)


class TestRepositoryConfig:
    """Tests for RepositoryConfig model."""

    def test_default_values(self):
        from thumbelina.config.models import RepositoryConfig

        cfg = RepositoryConfig()
        assert cfg.database_url == "sqlite:///thumbelina.db"

    def test_custom_values(self):
        from thumbelina.config.models import RepositoryConfig

        cfg = RepositoryConfig(database_url="postgresql://localhost/test")
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


class TestContextConfig:
    """ContextConfig / ContextCompressConfig 模型的测试。"""

    def test_default_values(self):
        from thumbelina.config.models import ContextConfig

        cfg = ContextConfig()
        assert cfg.compress.strategy == "summary_recent"
        assert cfg.compress.threshold == 0.8
        assert cfg.compress.recent_turns == 6

    def test_custom_values(self):
        from thumbelina.config.models import ContextConfig

        cfg = ContextConfig.model_validate(
            {"compress": {"strategy": "sliding_window", "threshold": 0.5, "recent_turns": 3}}
        )
        assert cfg.compress.strategy == "sliding_window"
        assert cfg.compress.threshold == 0.5
        assert cfg.compress.recent_turns == 3

    def test_invalid_strategy_raises(self):
        from thumbelina.config.models import ContextConfig

        with pytest.raises(Exception):  # Pydantic validation error
            ContextConfig.model_validate({"compress": {"strategy": "bogus"}})

    def test_threshold_out_of_range_raises(self):
        from thumbelina.config.models import ContextConfig

        with pytest.raises(Exception):  # Pydantic validation error
            ContextConfig.model_validate({"compress": {"threshold": 1.5}})


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_default_values(self):
        from thumbelina.config.models import AppConfig, LLMConfig, LoggingConfig, RepositoryConfig

        cfg = AppConfig()
        assert isinstance(cfg.llm, LLMConfig)
        assert isinstance(cfg.repository, RepositoryConfig)
        assert isinstance(cfg.logging, LoggingConfig)
        assert cfg.llm.provider == "openai"
        assert cfg.repository.database_url == "sqlite:///thumbelina.db"
        assert cfg.logging.level == "INFO"

    def test_nested_config(self):
        from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig

        cfg = AppConfig(
            llm=LLMConfig(provider="anthropic", model="claude-3"),
            repository=RepositoryConfig(database_url="postgresql://localhost/test"),
        )
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "claude-3"
        assert cfg.repository.database_url == "postgresql://localhost/test"

    def test_from_dict(self):
        from thumbelina.config.models import AppConfig

        data = {
            "llm": {"provider": "ollama", "model": "llama3"},
            "repository": {"database_url": "sqlite:///custom.db"},
            "logging": {"level": "DEBUG"},
        }
        cfg = AppConfig.model_validate(data)
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.model == "llama3"
        assert cfg.repository.database_url == "sqlite:///custom.db"
        assert cfg.logging.level == "DEBUG"

    def test_from_dict_partial(self):
        from thumbelina.config.models import AppConfig

        data = {"llm": {"provider": "anthropic"}}
        cfg = AppConfig.model_validate(data)
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "gpt-4o"  # default
        assert cfg.repository.database_url == "sqlite:///thumbelina.db"  # default

    def test_to_dict(self):
        from thumbelina.config.models import AppConfig

        cfg = AppConfig()
        data = cfg.model_dump()
        assert isinstance(data, dict)
        assert "llm" in data
        assert "repository" in data
        assert "logging" in data
        assert data["llm"]["provider"] == "openai"

    def test_legacy_config_without_new_keys_loads(self):
        """早于 context_window/ContextConfig 的配置继续可用。"""
        from thumbelina.config.models import AppConfig

        data = {
            "llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-test"},
            "repository": {"database_url": "sqlite:///thumbelina.db"},
            "logging": {"level": "INFO"},
        }
        cfg = AppConfig.model_validate(data)
        assert cfg.llm.context_window == "128K"  # 默认值
        assert cfg.llm.context_window_tokens == 128_000
        assert cfg.context.compress.strategy == "summary_recent"
        assert cfg.context.compress.threshold == 0.8
        assert cfg.context.compress.recent_turns == 6

    def test_context_keys_parse_from_dict(self):
        from thumbelina.config.models import AppConfig

        data = {
            "llm": {"context_window": "1M"},
            "context": {"compress": {"strategy": "full_summary", "threshold": 0.75}},
        }
        cfg = AppConfig.model_validate(data)
        assert cfg.llm.context_window_tokens == 1_000_000
        assert cfg.context.compress.strategy == "full_summary"
        assert cfg.context.compress.threshold == 0.75
        assert cfg.context.compress.recent_turns == 6  # 默认值保留
