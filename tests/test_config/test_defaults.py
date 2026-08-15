"""Tests for thumbelina.config.defaults module."""

from __future__ import annotations


class TestDefaults:
    """Tests for default configuration."""

    def test_default_config_dict(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG, dict)
        # llm is intentionally absent — defaults come from AppConfig / LLMConfig
        assert "llm" not in DEFAULT_CONFIG
        assert "repository" in DEFAULT_CONFIG
        assert "logging" in DEFAULT_CONFIG

    def test_default_repository_config(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        repo = DEFAULT_CONFIG["repository"]
        assert repo["database_url"] == "sqlite:///thumbelina.db"

    def test_default_logging_config(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        logging = DEFAULT_CONFIG["logging"]
        assert logging["level"] == "INFO"

    def test_get_default_config(self):
        from thumbelina.config.defaults import get_default_config

        cfg = get_default_config()
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"
        assert cfg.llm.api_key == ""
        assert cfg.repository.database_url == "sqlite:///thumbelina.db"
        assert cfg.logging.level == "INFO"
