"""Tests for thumbelina.config.loader module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import yaml


def _no_discovery():
    """Patch target: disable auto-discovery of thumbelina.yaml."""
    return None


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_default_config(self):
        from thumbelina.config.loader import load_config

        with patch("thumbelina.config.loader._discover_config_file", _no_discovery):
            cfg = load_config()
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"
        assert cfg.logging.level == "INFO"

    def test_load_from_yaml_file(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {
            "llm": {"provider": "anthropic", "model": "claude-3", "api_key": "sk-test"},
            "memory": {"database_url": "postgresql://localhost/test"},
            "logging": {"level": "DEBUG"},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(config_file))
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "claude-3"
        assert cfg.llm.api_key == "sk-test"
        assert cfg.memory.database_url == "postgresql://localhost/test"
        assert cfg.logging.level == "DEBUG"

    def test_load_from_yml_file(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"provider": "ollama"}}
        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(config_file))
        assert cfg.llm.provider == "ollama"

    def test_load_partial_yaml(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"provider": "anthropic"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(config_file))
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "gpt-4o"  # default
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"  # default

    def test_load_nonexistent_file_raises(self):
        from thumbelina.config.loader import load_config

        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_env_override_llm_provider(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"provider": "openai"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        env = {"THUMBELINA_LLM__PROVIDER": "anthropic"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config(str(config_file))
        assert cfg.llm.provider == "anthropic"

    def test_env_override_llm_api_key(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"api_key": ""}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        env = {"THUMBELINA_LLM__API_KEY": "sk-env-key"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config(str(config_file))
        assert cfg.llm.api_key == "sk-env-key"

    def test_env_override_memory_url(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {"memory": {"database_url": "sqlite:///default.db"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        env = {"THUMBELINA_MEMORY__DATABASE_URL": "postgresql://localhost/env"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config(str(config_file))
        assert cfg.memory.database_url == "postgresql://localhost/env"

    def test_env_override_logging_level(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_data = {"logging": {"level": "INFO"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        env = {"THUMBELINA_LOGGING__LEVEL": "WARNING"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config(str(config_file))
        assert cfg.logging.level == "WARNING"

    def test_env_override_without_file(self):
        from thumbelina.config.loader import load_config

        env = {"THUMBELINA_LLM__PROVIDER": "ollama", "THUMBELINA_LLM__MODEL": "llama3"}
        with (
            patch.dict(os.environ, env, clear=False),
            patch("thumbelina.config.loader._discover_config_file", _no_discovery),
        ):
            cfg = load_config()
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.model == "llama3"

    def test_env_api_key_direct(self, tmp_path):
        """Test direct OPENAI_API_KEY environment variable."""
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"api_key": ""}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        env = {"OPENAI_API_KEY": "sk-direct-key"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config(str(config_file))
        assert cfg.llm.api_key == "sk-direct-key"

    def test_env_var_substitution_in_yaml(self, tmp_path):
        """Test ${VAR} syntax in YAML values."""
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"api_key": "${OPENAI_API_KEY}"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        env = {"OPENAI_API_KEY": "sk-substituted"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config(str(config_file))
        assert cfg.llm.api_key == "sk-substituted"

    def test_env_var_substitution_missing_var(self, tmp_path):
        """Test ${VAR} syntax when variable is not set."""
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"api_key": "${MISSING_VAR}"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        # Ensure MISSING_VAR is not set
        env = {k: v for k, v in os.environ.items() if k != "MISSING_VAR"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(str(config_file))
        # Should keep the literal string when env var is missing
        assert cfg.llm.api_key == "${MISSING_VAR}" or cfg.llm.api_key == ""

    def test_load_empty_yaml(self, tmp_path):
        from thumbelina.config.loader import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        cfg = load_config(str(config_file))
        assert cfg.llm.provider == "openai"  # defaults

    def test_load_none_path(self):
        from thumbelina.config.loader import load_config

        with patch("thumbelina.config.loader._discover_config_file", _no_discovery):
            cfg = load_config(None)
        assert cfg.llm.provider == "openai"

    def test_auto_discover_config_file(self, tmp_path, monkeypatch):
        from thumbelina.config.loader import load_config

        config_data = {"llm": {"provider": "ollama", "model": "llama3"}}
        config_file = tmp_path / "thumbelina.yaml"
        config_file.write_text(yaml.dump(config_data))
        monkeypatch.chdir(tmp_path)

        cfg = load_config()
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.model == "llama3"


class TestExampleConfigFile:
    """The shipped example config must not require llm/auth at startup."""

    @staticmethod
    def _example_path():
        from pathlib import Path

        # tests/test_config/test_loader.py -> repo root
        return Path(__file__).resolve().parents[2] / "thumbelina.yaml.example"

    def test_example_has_no_llm_or_auth_sections(self):
        data = yaml.safe_load(self._example_path().read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "llm" not in data
        assert "auth" not in data

    def test_load_example_yields_empty_llm_and_auth(self):
        from thumbelina.config.loader import load_config

        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(str(self._example_path()))

        # llm/auth fall back to code defaults — no boot-time requirement
        assert cfg.llm.api_key == ""
        assert cfg.auth.secret_key == ""
        # role default stays in the code model
        assert cfg.llm.role == "assistant"
        assert cfg.memory.database_url == "sqlite:///thumbelina.db"
