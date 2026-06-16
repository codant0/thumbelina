"""Tests for thumbelina.config.persistence module."""

from __future__ import annotations

import yaml

from thumbelina.config.loader import load_config
from thumbelina.config.models import AppConfig
from thumbelina.config.persistence import save_config


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_and_reload_roundtrip(self, tmp_path):
        """Non-sensitive fields survive a save → load round-trip."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate(
            {
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-3",
                    "api_key": "sk-secret",
                    "base_url": "https://example.com",
                },
            }
        )
        save_config(config, config_file)

        loaded = load_config(config_file)
        assert loaded.llm.provider == "anthropic"
        assert loaded.llm.model == "claude-3"
        assert loaded.llm.base_url == "https://example.com"

    def test_sensitive_fields_not_written(self, tmp_path):
        """api_key, app_secret, bot_token are empty in the saved file."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate(
            {
                "llm": {"api_key": "sk-secret"},
                "channels": {
                    "qq": {"app_secret": "qq-secret"},
                    "wechat": {"bot_token": "wc-token", "webhook_secret": "wh-secret"},
                },
            }
        )
        save_config(config, config_file)

        raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert raw["llm"]["api_key"] == ""
        assert raw["channels"]["qq"]["app_secret"] == ""
        assert raw["channels"]["wechat"]["bot_token"] == ""
        assert raw["channels"]["wechat"]["webhook_secret"] == ""

    def test_channel_fields_written(self, tmp_path):
        """Non-secret channel fields are persisted."""
        config_file = str(tmp_path / "config.yaml")
        config = AppConfig.model_validate(
            {
                "channels": {
                    "qq": {
                        "enabled": True,
                        "app_id": "my-app",
                        "allowed_guilds": ["g1", "g2"],
                    },
                    "wechat": {
                        "enabled": True,
                        "ilink_bot_id": "bot@id",
                    },
                },
            }
        )
        save_config(config, config_file)

        loaded = load_config(config_file)
        assert loaded.channels.qq.enabled is True
        assert loaded.channels.qq.app_id == "my-app"
        assert loaded.channels.qq.allowed_guilds == ["g1", "g2"]
        assert loaded.channels.wechat.ilink_bot_id == "bot@id"

    def test_creates_parent_directory(self, tmp_path):
        """save_config creates intermediate directories."""
        config_file = str(tmp_path / "sub" / "dir" / "config.yaml")
        save_config(AppConfig(), config_file)
        assert (tmp_path / "sub" / "dir" / "config.yaml").exists()

    def test_yaml_is_valid(self, tmp_path):
        """Saved file is valid YAML."""
        config_file = str(tmp_path / "config.yaml")
        save_config(AppConfig(), config_file)
        data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "llm" in data
