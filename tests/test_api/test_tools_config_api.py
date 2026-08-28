"""Tests for the tools configuration API (GET/PUT /config/tools*)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from thumbelina.api.app import create_app
from thumbelina.config.models import AppConfig


def _make_client(config: AppConfig) -> TestClient:
    app = create_app(config)
    mock_manager = MagicMock()
    mock_manager._persist_to_db = AsyncMock()
    app.state.runtime_config_manager = mock_manager
    return TestClient(app)


@pytest.fixture()
def client() -> TestClient:
    config = AppConfig.model_validate(
        {
            "llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-test"},
            "tools": {"web_search": {"provider": "tavily", "api_key": ""}},
        }
    )
    return _make_client(config)


class TestGetToolsConfig:
    def test_defaults(self, client):
        resp = client.get("/api/v1/config/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["web_search"]["provider"] == "tavily"
        assert data["web_search"]["enabled"] is True
        assert data["web_search"]["api_key_set"] is False
        # secret must never be returned
        assert "api_key" not in data["web_search"]

    def test_api_key_set_indicator(self):
        cfg = AppConfig.model_validate(
            {"tools": {"web_search": {"provider": "tavily", "api_key": "secret"}}}
        )
        resp = TestClient(create_app(cfg)).get("/api/v1/config/tools")
        data = resp.json()
        assert data["web_search"]["api_key_set"] is True
        assert "api_key" not in data["web_search"]


class TestPutToolsWebSearch:
    def test_change_provider(self, client):
        resp = client.put(
            "/api/v1/config/tools/web_search",
            json={"provider": "duckduckgo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["web_search"]["provider"] == "duckduckgo"
        # live config object updated in place (hot-swap source of truth)
        assert client.app.state.config.tools.web_search.provider == "duckduckgo"
        client.app.state.runtime_config_manager._persist_to_db.assert_any_await(
            "tools", "tools.web_search.provider", "duckduckgo"
        )

    def test_toggle_enabled(self, client):
        resp = client.put(
            "/api/v1/config/tools/web_search",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["web_search"]["enabled"] is False
        assert client.app.state.config.tools.web_search.enabled is False

    def test_set_api_key(self, client):
        resp = client.put(
            "/api/v1/config/tools/web_search",
            json={"api_key": "tvly-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["web_search"]["api_key_set"] is True
        assert client.app.state.config.tools.web_search.api_key == "tvly-secret"
        # api_key is exempted for this tool and now persisted to the DB
        client.app.state.runtime_config_manager._persist_to_db.assert_any_await(
            "tools", "tools.web_search.api_key", "tvly-secret"
        )

    def test_clear_api_key(self):
        cfg = AppConfig.model_validate(
            {"tools": {"web_search": {"provider": "tavily", "api_key": "old"}}}
        )
        client = _make_client(cfg)
        resp = client.put("/api/v1/config/tools/web_search", json={"api_key": ""})
        assert resp.status_code == 200
        assert resp.json()["web_search"]["api_key_set"] is False
        assert cfg.tools.web_search.api_key == ""

    def test_invalid_provider_rejected(self, client):
        resp = client.put(
            "/api/v1/config/tools/web_search",
            json={"provider": "google"},
        )
        assert resp.status_code == 422
