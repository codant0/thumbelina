"""Tests for thumbelina.config.loader YAML import functionality."""

from __future__ import annotations

import json
import yaml

import pytest

from thumbelina.config.loader import import_yaml_to_db, load_config_from_db
from thumbelina.config.models import AppConfig


class TestImportYamlToDb:
    """Tests for import_yaml_to_db function."""

    def test_import_basic_config(self, tmp_path):
        """Import basic YAML config to database."""
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "anthropic",
                "model": "claude-3",
            },
            "channels": {
                "qq": {
                    "enabled": True,
                    "app_id": "my-app",
                },
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        count = import_yaml_to_db(str(config_file), db_url)

        assert count >= 2  # At least provider and model

        # Verify values were imported
        from thumbelina.config.config_repo import ConfigRepository

        repo = ConfigRepository(db_url)
        try:
            provider = repo._get_sync("llm.provider")
            assert provider == json.dumps("anthropic")

            model = repo._get_sync("llm.model")
            assert model == json.dumps("claude-3")

            enabled = repo._get_sync("channels.qq.enabled")
            assert enabled == json.dumps(True)

            app_id = repo._get_sync("channels.qq.app_id")
            assert app_id == json.dumps("my-app")
        finally:
            repo.close()

    def test_import_skips_sensitive_fields(self, tmp_path):
        """Sensitive fields are not imported to database."""
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "sk-secret",
            },
            "channels": {
                "qq": {
                    "app_secret": "qq-secret",
                },
                "wechat": {
                    "bot_token": "wc-token",
                    "webhook_secret": "wh-secret",
                },
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        import_yaml_to_db(str(config_file), db_url)

        from thumbelina.config.config_repo import ConfigRepository

        repo = ConfigRepository(db_url)
        try:
            # Non-sensitive should be imported
            provider = repo._get_sync("llm.provider")
            assert provider == json.dumps("openai")

            # Sensitive should NOT be imported
            api_key = repo._get_sync("llm.api_key")
            assert api_key is None

            app_secret = repo._get_sync("channels.qq.app_secret")
            assert app_secret is None

            bot_token = repo._get_sync("channels.wechat.bot_token")
            assert bot_token is None

            webhook_secret = repo._get_sync("channels.wechat.webhook_secret")
            assert webhook_secret is None
        finally:
            repo.close()

    def test_import_no_config_file(self, tmp_path):
        """Import with non-existent config file returns 0."""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        count = import_yaml_to_db("/nonexistent/path/config.yaml", db_url)
        assert count == 0

    def test_import_empty_config(self, tmp_path):
        """Import empty config file returns 0."""
        config_file = tmp_path / "thumbelina.yaml"
        config_file.write_text("", encoding="utf-8")

        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        count = import_yaml_to_db(str(config_file), db_url)
        assert count == 0


class TestLoadConfigFromDb:
    """Tests for load_config_from_db function."""

    def test_load_with_db_overrides(self, tmp_path):
        """Load config with database overrides."""
        # Create base config
        base_config = AppConfig.model_validate(
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o",
                },
            }
        )

        # Create database with overrides
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        from thumbelina.config.config_repo import ConfigRepository

        repo = ConfigRepository(db_url)
        try:
            repo._set_sync("llm.provider", json.dumps("anthropic"), "llm")
            repo._set_sync("llm.model", json.dumps("claude-3"), "llm")
        finally:
            repo.close()

        # Load config with overrides
        config = load_config_from_db(db_url, base_config)

        # Database overrides should be applied
        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-3"

    def test_load_without_db_overrides(self, tmp_path):
        """Load config without database overrides returns base config."""
        base_config = AppConfig.model_validate(
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o",
                },
            }
        )

        db_url = f"sqlite:///{tmp_path / 'test.db'}"

        # Load config without overrides
        config = load_config_from_db(db_url, base_config)

        # Should return base config unchanged
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"

    def test_load_with_empty_db(self, tmp_path):
        """Load config with empty database returns base config."""
        base_config = AppConfig.model_validate(
            {
                "llm": {
                    "provider": "openai",
                },
            }
        )

        db_url = f"sqlite:///{tmp_path / 'test.db'}"

        # Load config with empty database
        config = load_config_from_db(db_url, base_config)

        # Should return base config unchanged
        assert config.llm.provider == "openai"
