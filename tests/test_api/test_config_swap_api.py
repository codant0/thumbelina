"""Tests for the runtime config swap API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig
from thumbelina.llm.endpoint_manager import EndpointManager, LLMEndpoint


@pytest.fixture()
def client():
    """Create a TestClient with mocked runtime config manager."""
    from thumbelina.api.app import create_app

    config = AppConfig.model_validate(
        {
            "llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-test"},
            "channels": {
                "qq": {"enabled": False},
                "wechat": {"enabled": False},
            },
        }
    )
    app = create_app(config)

    # Inject mock runtime manager
    mock_manager = MagicMock()
    mock_manager.swap_llm_provider = AsyncMock()
    mock_manager.swap_channel = AsyncMock(return_value=True)
    mock_manager._persist_to_db = AsyncMock()
    app.state.runtime_config_manager = mock_manager

    # Inject mock agent
    mock_agent = MagicMock()
    mock_agent.skill_engine = MagicMock()
    mock_agent.composition_engine = MagicMock()
    mock_agent.subagent_manager = MagicMock()
    app.state.agent = mock_agent
    app.state.skill_engine = mock_agent.skill_engine
    app.state.composition_engine = mock_agent.composition_engine
    app.state.subagent_manager = mock_agent.subagent_manager

    return TestClient(app)


class TestGetConfigExtended:
    """Tests for GET /config with sensitive field indicators."""

    def test_api_key_set_true(self, client):
        """api_key_set is true when key is non-empty."""
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        assert resp.json()["api_key_set"] is True

    def test_api_key_set_false(self):
        """api_key_set is false when key is empty."""
        from thumbelina.api.app import create_app

        config = AppConfig.model_validate({"llm": {"api_key": ""}})
        app = create_app(config)
        resp = TestClient(app).get("/api/v1/config")
        assert resp.json()["api_key_set"] is False

    def test_channel_secret_set_fields(self, client):
        """Channel responses include app_secret_set and bot_token_set."""
        resp = client.get("/api/v1/config")
        data = resp.json()
        assert "app_secret_set" in data["channels"]["qq"]
        assert "bot_token_set" in data["channels"]["wechat"]


class TestPutLLMConfig:
    """Tests for PUT /config/llm."""

    def test_swap_llm_success(self, client):
        """Successful LLM swap returns 200 with new config."""
        resp = client.put(
            "/api/v1/config/llm",
            json={
                "provider": "anthropic",
                "model": "claude-3",
                "api_key": "sk-new",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["provider"] == "anthropic"
        assert data["model"] == "claude-3"

    def test_swap_llm_with_base_url(self, client):
        """base_url is passed through."""
        resp = client.put(
            "/api/v1/config/llm",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "base_url": "https://proxy.example.com/v1",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["base_url"] == "https://proxy.example.com/v1"

    def test_swap_llm_missing_provider(self, client):
        """Missing provider returns 422."""
        resp = client.put("/api/v1/config/llm", json={"model": "x"})
        assert resp.status_code == 422

    def test_swap_llm_empty_provider(self, client):
        """Empty provider returns 422."""
        resp = client.put("/api/v1/config/llm", json={"provider": "", "model": "x"})
        assert resp.status_code == 422

    def test_swap_llm_invalid_provider_returns_422(self, client):
        """Invalid provider name returns 422 with error detail."""
        client.app.state.runtime_config_manager.swap_llm_provider = AsyncMock(
            side_effect=ValueError("Unknown provider: 'bad'")
        )
        resp = client.put(
            "/api/v1/config/llm",
            json={"provider": "bad", "model": "x"},
        )
        assert resp.status_code == 422
        assert "Unknown provider" in resp.json()["detail"]

    def test_swap_llm_with_endpoint_id(self, client):
        endpoint = LLMEndpoint(
            id="e1",
            provider="openai",
            name="Default",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            api_key_set=True,
            created_at="2026-07-02T00:00:00Z",
            updated_at="2026-07-02T00:00:00Z",
        )
        client.app.state.endpoint_manager = MagicMock(spec=EndpointManager)
        client.app.state.endpoint_manager.get_endpoint = AsyncMock(return_value=endpoint)
        response = client.put(
            "/api/v1/config/llm",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "endpoint_id": "e1",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["base_url"] == "https://api.openai.com/v1"


class TestPutChannelConfig:
    """Tests for PUT /config/channels/{name}."""

    def test_swap_qq_channel(self, client):
        """PUT /config/channels/qq with valid data returns 200."""
        resp = client.put(
            "/api/v1/config/channels/qq",
            json={"enabled": True, "app_id": "test-id"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["channel"] == "qq"
        assert data["enabled"] is True
        assert data["connected"] is True

    def test_swap_wechat_channel(self, client):
        """PUT /config/channels/wechat with valid data returns 200."""
        resp = client.put(
            "/api/v1/config/channels/wechat",
            json={"enabled": True, "bot_token": "tok-test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel"] == "wechat"

    def test_swap_unknown_channel_returns_400(self, client):
        """Unknown channel name returns 400."""
        resp = client.put(
            "/api/v1/config/channels/telegram",
            json={"enabled": True},
        )
        assert resp.status_code == 400

    def test_swap_channel_failure_returns_422(self, client):
        """Channel start failure returns 422."""
        client.app.state.runtime_config_manager.swap_channel = AsyncMock(
            side_effect=RuntimeError("Connection refused")
        )
        resp = client.put(
            "/api/v1/config/channels/qq",
            json={"enabled": True},
        )
        assert resp.status_code == 422
        assert "Connection refused" in resp.json()["detail"]

    def test_disable_channel(self, client):
        """Disabling a channel returns connected=False."""
        client.app.state.runtime_config_manager.swap_channel = AsyncMock(return_value=False)
        resp = client.put(
            "/api/v1/config/channels/qq",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["connected"] is False


class TestPostConfigStillWorks:
    """Verify POST /config still handles streaming/rate_limit toggles."""

    def test_post_streaming_toggle(self, client):
        resp = client.post(
            "/api/v1/config",
            json={"llm": {"streaming_enabled": False}},
        )
        assert resp.status_code == 200

    def test_post_auth_required_roles(self, client):
        """auth.required_roles is hot-reloadable and persisted to the DB."""
        resp = client.post(
            "/api/v1/config",
            json={"auth": {"required_roles": ["admin", "ops"]}},
        )
        assert resp.status_code == 200
        config = client.app.state.config
        assert config.auth.required_roles == ["admin", "ops"]
        client.app.state.runtime_config_manager._persist_to_db.assert_any_await(
            "auth", "auth.required_roles", ["admin", "ops"]
        )


class TestGetConfigExport:
    """Tests for GET /config/export."""

    def test_export_config_success(self, client):
        """Export config returns database contents."""
        # Mock the config_repo
        mock_repo = MagicMock()
        mock_repo.export_to_dict = AsyncMock(return_value={"llm": {"provider": "openai"}})
        client.app.state.config_repo = mock_repo

        resp = client.get("/api/v1/config/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm"]["provider"] == "openai"

    def test_export_config_with_category(self, client):
        """Export config with category filter."""
        mock_repo = MagicMock()
        mock_repo.export_to_dict = AsyncMock(return_value={"llm": {"provider": "openai"}})
        client.app.state.config_repo = mock_repo

        resp = client.get("/api/v1/config/export?category=llm")
        assert resp.status_code == 200
        mock_repo.export_to_dict.assert_called_once_with("llm")

    def test_export_config_no_repo(self, client):
        """Export config returns 503 when config_repo is not available."""
        # Remove config_repo from app state
        if hasattr(client.app.state, "config_repo"):
            delattr(client.app.state, "config_repo")

        resp = client.get("/api/v1/config/export")
        assert resp.status_code == 503


class TestPostConfigReload:
    """Tests for POST /config/reload."""

    def test_reload_config_success(self, client):
        """Reload config returns success."""
        # Add load_from_database as AsyncMock to the mock manager
        client.app.state.runtime_config_manager.load_from_database = AsyncMock()

        resp = client.post("/api/v1/config/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_reload_config_calls_load_from_database(self, client):
        """Reload config calls load_from_database on the manager."""
        client.app.state.runtime_config_manager.load_from_database = AsyncMock()

        resp = client.post("/api/v1/config/reload")
        assert resp.status_code == 200
        client.app.state.runtime_config_manager.load_from_database.assert_called_once()
