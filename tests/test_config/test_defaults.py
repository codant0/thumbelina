"""Tests for thumbelina.config.defaults module."""

from __future__ import annotations


class TestDefaults:
    """Tests for default configuration."""

    def test_default_config_dict(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG, dict)
        assert "llm" in DEFAULT_CONFIG
        assert "memory" in DEFAULT_CONFIG
        assert "logging" in DEFAULT_CONFIG

    def test_default_llm_config(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        llm = DEFAULT_CONFIG["llm"]
        assert llm["provider"] == "openai"
        assert llm["model"] == "gpt-4o"

    def test_default_memory_config(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        memory = DEFAULT_CONFIG["memory"]
        assert memory["database_url"] == "sqlite:///thumbelina.db"

    def test_default_logging_config(self):
        from thumbelina.config.defaults import DEFAULT_CONFIG

        logging = DEFAULT_CONFIG["logging"]
        assert logging["level"] == "INFO"

    def test_get_default_config(self):
        from thumbelina.config.defaults import get_default_config

        cfg = get_default_config()
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"
        assert cfg.logging.level == "INFO"
