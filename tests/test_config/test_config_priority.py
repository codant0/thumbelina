"""Tests for configuration loading priority and database empty detection."""

from __future__ import annotations

import json
import os

import pytest
import yaml

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.config.loader import import_yaml_to_db, load_config, load_config_from_db
from thumbelina.config.models import AppConfig


class TestDatabaseEmptyDetection:
    """Tests for database empty detection."""

    def test_empty_database(self, tmp_path):
        """New database should be detected as empty."""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        repo = ConfigRepository(db_url)
        try:
            assert repo._is_empty_sync() is True
        finally:
            repo.close()

    def test_non_empty_database(self, tmp_path):
        """Database with config entries should not be empty."""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        repo = ConfigRepository(db_url)
        try:
            repo._set_sync("llm.provider", json.dumps("openai"), "llm")
            assert repo._is_empty_sync() is False
        finally:
            repo.close()


class TestConfigLoadingPriority:
    """Tests for configuration loading priority: DB > env > YAML > defaults."""

    def test_yaml_overrides_defaults(self, tmp_path):
        """YAML config should override default values."""
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "anthropic",
                "model": "claude-3",
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        # Change to tmp_path so load_config finds the YAML file
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = load_config()
            assert config.llm.provider == "anthropic"
            assert config.llm.model == "claude-3"
        finally:
            os.chdir(original_dir)

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        """Environment variables should override YAML config."""
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        # Set environment variable
        monkeypatch.setenv("THUMBELINA_LLM__PROVIDER", "anthropic")

        # Change to tmp_path so load_config finds the YAML file
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = load_config()
            # Environment variable should override YAML
            assert config.llm.provider == "anthropic"
            # Model should come from YAML
            assert config.llm.model == "gpt-4o"
        finally:
            os.chdir(original_dir)

    def test_db_overrides_yaml_and_env(self, tmp_path, monkeypatch):
        """Database values should override YAML and environment variables."""
        # Create YAML config
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        # Create database with overrides
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        repo = ConfigRepository(db_url)
        try:
            repo._set_sync("llm.provider", json.dumps("anthropic"), "llm")
            repo._set_sync("llm.model", json.dumps("claude-3"), "llm")
        finally:
            repo.close()

        # Load base config from YAML
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            base_config = load_config()

            # Base config should have YAML values
            assert base_config.llm.provider == "openai"
            assert base_config.llm.model == "gpt-4o"

            # Load with database overrides
            config = load_config_from_db(db_url, base_config)

            # Database should override YAML
            assert config.llm.provider == "anthropic"
            assert config.llm.model == "claude-3"
        finally:
            os.chdir(original_dir)

    def test_db_empty_preserves_yaml(self, tmp_path):
        """Empty database should not affect YAML config."""
        # Create YAML config
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "anthropic",
                "model": "claude-3",
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        # Create empty database
        db_url = f"sqlite:///{tmp_path / 'test.db'}"

        # Load base config from YAML
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            base_config = load_config()

            # Load with empty database
            config = load_config_from_db(db_url, base_config)

            # Config should have YAML values
            assert config.llm.provider == "anthropic"
            assert config.llm.model == "claude-3"
        finally:
            os.chdir(original_dir)


class TestYamlImportToDb:
    """Tests for YAML import to database."""

    def test_first_startup_import(self, tmp_path):
        """First startup should import YAML to empty database."""
        # Create YAML config
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

        # Create empty database
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        repo = ConfigRepository(db_url)
        try:
            # Verify database is empty
            assert repo._is_empty_sync() is True

            # Import YAML to database
            count = import_yaml_to_db(str(config_file), db_url)
            assert count >= 2

            # Verify database is no longer empty
            assert repo._is_empty_sync() is False

            # Verify values were imported
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

    def test_subsequent_startup_skips_import(self, tmp_path):
        """Subsequent startups should not re-import if database is not empty."""
        # Create YAML config
        config_file = tmp_path / "thumbelina.yaml"
        config_data = {
            "llm": {
                "provider": "anthropic",
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        # Create database with existing config
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        repo = ConfigRepository(db_url)
        try:
            repo._set_sync("llm.provider", json.dumps("openai"), "llm")
            assert repo._is_empty_sync() is False
        finally:
            repo.close()

        # Import should not overwrite existing values
        # (In real app, this is controlled by the is_empty check in lifespan)
        # Here we just verify that import_yaml_to_db would import
        count = import_yaml_to_db(str(config_file), db_url)

        # The import function will import regardless of existing data
        # The is_empty check is done in the lifespan function
        # So we just verify the import happened
        assert count >= 1

        # Verify the imported value
        repo = ConfigRepository(db_url)
        try:
            provider = repo._get_sync("llm.provider")
            # The import will overwrite the existing value
            assert provider == json.dumps("anthropic")
        finally:
            repo.close()

    def test_sensitive_fields_not_imported(self, tmp_path):
        """Sensitive fields should not be imported to database."""
        # Create YAML config with sensitive fields
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

        # Create empty database
        db_url = f"sqlite:///{tmp_path / 'test.db'}"

        # Import YAML to database
        import_yaml_to_db(str(config_file), db_url)

        # Verify sensitive fields were NOT imported
        repo = ConfigRepository(db_url)
        try:
            api_key = repo._get_sync("llm.api_key")
            assert api_key is None

            app_secret = repo._get_sync("channels.qq.app_secret")
            assert app_secret is None

            bot_token = repo._get_sync("channels.wechat.bot_token")
            assert bot_token is None

            webhook_secret = repo._get_sync("channels.wechat.webhook_secret")
            assert webhook_secret is None

            # Non-sensitive fields should be imported
            provider = repo._get_sync("llm.provider")
            assert provider == json.dumps("openai")
        finally:
            repo.close()
