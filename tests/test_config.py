"""Tests for thumbelina.config module."""

import os
from unittest.mock import patch


class TestAppConfig:
    """Tests for the AppConfig dataclass."""

    def test_default_values(self):
        from thumbelina.config import AppConfig

        cfg = AppConfig()
        assert cfg.app_name == "thumbelina"
        assert cfg.debug is False
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.db_url == "sqlite:///thumbelina.db"

    def test_custom_values(self):
        from thumbelina.config import AppConfig

        cfg = AppConfig(app_name="test", debug=True, port=9000)
        assert cfg.app_name == "test"
        assert cfg.debug is True
        assert cfg.port == 9000

    def test_from_env_reads_environment(self):
        from thumbelina.config import AppConfig

        env = {
            "THUMBELINA_APP_NAME": "envapp",
            "THUMBELINA_DEBUG": "true",
            "THUMBELINA_HOST": "127.0.0.1",
            "THUMBELINA_PORT": "3000",
            "THUMBELINA_DB_URL": "sqlite:///custom.db",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = AppConfig.from_env()
        assert cfg.app_name == "envapp"
        assert cfg.debug is True
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 3000
        assert cfg.db_url == "sqlite:///custom.db"

    def test_from_env_defaults_when_unset(self):
        from thumbelina.config import AppConfig

        # Ensure no THUMBELINA_ vars are set
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("THUMBELINA_")}
        with patch.dict(os.environ, clean_env, clear=True):
            cfg = AppConfig.from_env()
        assert cfg.app_name == "thumbelina"
        assert cfg.debug is False
