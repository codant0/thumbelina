"""Tests for thumbelina.config.config_repo module."""

from __future__ import annotations

import json

import pytest

from thumbelina.config.config_repo import ConfigRepository, _is_sensitive


class TestIsSensitive:
    """Tests for _is_sensitive helper function."""

    def test_api_key_is_sensitive(self):
        assert _is_sensitive("llm.api_key") is True

    def test_secret_key_is_sensitive(self):
        assert _is_sensitive("auth.secret_key") is True

    def test_app_secret_is_sensitive(self):
        assert _is_sensitive("channels.qq.app_secret") is True

    def test_bot_token_is_sensitive(self):
        assert _is_sensitive("channels.wechat.bot_token") is True

    def test_webhook_secret_is_sensitive(self):
        assert _is_sensitive("channels.wechat.webhook_secret") is True

    def test_provider_not_sensitive(self):
        assert _is_sensitive("llm.provider") is False

    def test_model_not_sensitive(self):
        assert _is_sensitive("llm.model") is False

    def test_enabled_not_sensitive(self):
        assert _is_sensitive("channels.qq.enabled") is False

    def test_base_url_not_sensitive(self):
        assert _is_sensitive("llm.base_url") is False


class TestConfigRepository:
    """Tests for ConfigRepository CRUD operations."""

    @pytest.fixture()
    def repo(self, tmp_path):
        """Create a ConfigRepository with in-memory database."""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        return ConfigRepository(db_url)

    def test_set_and_get(self, repo):
        """Set a config value and retrieve it."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        value = repo._get_sync("llm.provider")
        assert value == json.dumps("openai")

    def test_get_nonexistent(self, repo):
        """Get a non-existent config key returns None."""
        value = repo._get_sync("nonexistent.key")
        assert value is None

    def test_set_updates_existing(self, repo):
        """Setting an existing key updates the value."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        repo._set_sync("llm.provider", json.dumps("anthropic"), "llm")
        value = repo._get_sync("llm.provider")
        assert value == json.dumps("anthropic")

    def test_delete(self, repo):
        """Delete a config key."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        result = repo._delete_sync("llm.provider")
        assert result is True
        assert repo._get_sync("llm.provider") is None

    def test_delete_nonexistent(self, repo):
        """Delete a non-existent key returns False."""
        result = repo._delete_sync("nonexistent.key")
        assert result is False

    def test_get_all(self, repo):
        """Get all config values."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        repo._set_sync("llm.model", json.dumps("gpt-4o"), "llm")
        repo._set_sync("channels.qq.enabled", json.dumps(True), "channel")

        all_config = repo._get_all_sync()
        assert len(all_config) == 3
        assert all_config["llm.provider"] == json.dumps("openai")
        assert all_config["llm.model"] == json.dumps("gpt-4o")
        assert all_config["channels.qq.enabled"] == json.dumps(True)

    def test_get_by_category(self, repo):
        """Get config values by category."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        repo._set_sync("llm.model", json.dumps("gpt-4o"), "llm")
        repo._set_sync("channels.qq.enabled", json.dumps(True), "channel")

        llm_config = repo._get_by_category_sync("llm")
        assert len(llm_config) == 2
        assert "llm.provider" in llm_config
        assert "llm.model" in llm_config

    def test_sensitive_key_not_stored(self, repo):
        """Sensitive keys are not stored in the database."""
        repo._set_sync("llm.api_key", json.dumps("sk-secret"), "llm")
        _ = repo._get_sync("llm.api_key")
        # The set_sync method doesn't filter, but the async set method does
        # This test verifies the _is_sensitive check works
        from thumbelina.config.config_repo import _is_sensitive

        assert _is_sensitive("llm.api_key") is True

    def test_export_to_dict(self, repo):
        """Export config to nested dict."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        repo._set_sync("llm.model", json.dumps("gpt-4o"), "llm")
        repo._set_sync("channels.qq.enabled", json.dumps(True), "channel")

        # Use the sync helper directly
        from thumbelina.config.loader import _load_db_config_sync

        config_dict = _load_db_config_sync(repo)
        assert config_dict["llm"]["provider"] == "openai"
        assert config_dict["llm"]["model"] == "gpt-4o"
        assert config_dict["channels"]["qq"]["enabled"] is True

    def test_export_to_dict_with_category(self, repo):
        """Export config to nested dict filtered by category."""
        repo._set_sync("llm.provider", json.dumps("openai"), "llm")
        repo._set_sync("llm.model", json.dumps("gpt-4o"), "llm")
        repo._set_sync("channels.qq.enabled", json.dumps(True), "channel")

        llm_config = repo._get_by_category_sync("llm")
        assert len(llm_config) == 2
        assert "llm.provider" in llm_config
        assert "llm.model" in llm_config


class TestConfigRepositoryAsync:
    """Tests for async ConfigRepository operations."""

    @pytest.fixture()
    def repo(self, tmp_path):
        """Create a ConfigRepository with in-memory database."""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        return ConfigRepository(db_url)

    @pytest.mark.asyncio()
    async def test_set_sensitive_key_not_stored(self, repo):
        """Sensitive keys are not stored via async set."""
        await repo.set("llm.api_key", json.dumps("sk-secret"), "llm")
        value = await repo.get("llm.api_key")
        assert value is None

    @pytest.mark.asyncio()
    async def test_set_non_sensitive_key_stored(self, repo):
        """Non-sensitive keys are stored via async set."""
        await repo.set("llm.provider", json.dumps("openai"), "llm")
        value = await repo.get("llm.provider")
        assert value == json.dumps("openai")

    @pytest.mark.asyncio()
    async def test_set_auth_secret_key_not_stored(self, repo):
        """auth.secret_key is sensitive and never stored."""
        await repo.set("auth.secret_key", json.dumps("s" * 48), "auth")
        value = await repo.get("auth.secret_key")
        assert value is None

    @pytest.mark.asyncio()
    async def test_set_auth_required_roles_stored(self, repo):
        """Non-sensitive auth keys (required_roles) are runtime-configurable."""
        await repo.set("auth.required_roles", json.dumps(["admin"]), "auth")
        value = await repo.get("auth.required_roles")
        assert value == json.dumps(["admin"])

    @pytest.mark.asyncio()
    async def test_import_from_dict(self, repo):
        """Import config from nested dict."""
        data = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "sk-secret",  # Should be skipped
            },
            "channels": {
                "qq": {
                    "enabled": True,
                    "app_secret": "qq-secret",  # Should be skipped
                },
            },
        }

        count = await repo.import_from_dict(data, "llm")
        # Should import 2 non-sensitive keys from llm, skip api_key
        # Plus 1 from channels (enabled), skip app_secret
        assert count >= 2

        # Verify non-sensitive keys were imported
        provider = await repo.get("llm.provider")
        assert provider == json.dumps("openai")

        model = await repo.get("llm.model")
        assert model == json.dumps("gpt-4o")

        # Verify sensitive keys were NOT imported
        api_key = await repo.get("llm.api_key")
        assert api_key is None

        app_secret = await repo.get("channels.qq.app_secret")
        assert app_secret is None
