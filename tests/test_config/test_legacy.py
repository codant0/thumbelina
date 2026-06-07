"""Tests for thumbelina.config legacy compatibility."""

import os
from unittest.mock import patch


def _no_discovery():
    """Patch target: disable auto-discovery of thumbelina.yaml."""
    return None


class TestLegacyConfig:
    """Tests for legacy config compatibility."""

    def test_load_config_returns_app_config(self):
        from thumbelina.config import AppConfig, load_config

        with patch("thumbelina.config.loader._discover_config_file", _no_discovery):
            cfg = load_config()
        assert isinstance(cfg, AppConfig)

    def test_load_config_default_values(self):
        from thumbelina.config import load_config

        with patch("thumbelina.config.loader._discover_config_file", _no_discovery):
            cfg = load_config()
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"
        assert cfg.logging.level == "INFO"

    def test_load_config_from_env(self):
        from thumbelina.config import load_config

        env = {
            "THUMBELINA_LLM__PROVIDER": "anthropic",
            "THUMBELINA_LLM__MODEL": "claude-3",
            "THUMBELINA_MEMORY__DATABASE_URL": "sqlite:///custom.db",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch("thumbelina.config.loader._discover_config_file", _no_discovery),
        ):
            cfg = load_config()
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "claude-3"
        assert cfg.memory.database_url == "sqlite:///custom.db"

    def test_load_config_from_env_defaults_when_unset(self):
        from thumbelina.config import load_config

        # Ensure no THUMBELINA_ vars are set
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("THUMBELINA_")}
        with (
            patch.dict(os.environ, clean_env, clear=True),
            patch("thumbelina.config.loader._discover_config_file", _no_discovery),
        ):
            cfg = load_config()
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"
