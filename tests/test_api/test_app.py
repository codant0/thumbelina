"""Tests for thumbelina.api.app module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig


@pytest.fixture
def test_config():
    """Create a test configuration."""
    return AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )


def test_create_app_returns_fastapi(test_config):
    """create_app should return a FastAPI instance."""
    from thumbelina.api.app import create_app

    app = create_app(test_config)
    assert isinstance(app, FastAPI)


def test_app_has_title(test_config):
    """App should have the correct title."""
    from thumbelina.api.app import create_app

    app = create_app(test_config)
    assert app.title == "Thumbelina API"


def test_app_has_version(test_config):
    """App should have a version."""
    from thumbelina.api.app import create_app

    app = create_app(test_config)
    assert app.version == "0.1.0"


def test_health_endpoint(client):
    """GET /health should return status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_cors_allows_all_origins(test_config):
    """CORS middleware should be configured to allow all origins."""
    from thumbelina.api.app import create_app

    app = create_app(test_config)
    # Verify CORS middleware is present
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes


def test_cors_options_request(client):
    """CORS preflight request should succeed."""
    response = client.options(
        "/api/v1/chat",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200


def _collect_paths(app: FastAPI) -> set[str]:
    """Collect all registered route paths via the OpenAPI schema."""
    schema = app.openapi()
    return set(schema.get("paths", {}).keys())


def test_app_includes_chat_router(test_config):
    """App should include the chat router."""
    from thumbelina.api.app import create_app

    app = create_app(test_config)
    # Check that /api/v1/chat route exists
    paths = _collect_paths(app)
    assert "/api/v1/chat" in paths


def test_app_includes_conversations_router(test_config):
    """App should include the conversations router."""
    from thumbelina.api.app import create_app

    app = create_app(test_config)
    paths = _collect_paths(app)
    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}" in paths


class TestBootWithoutLLMAndAuth:
    """llm/auth configuration must not be required at startup."""

    @staticmethod
    def _middleware_classes(app: FastAPI) -> list[type]:
        return [m.cls for m in app.user_middleware]

    def test_create_app_with_minimal_config(self):
        """App starts with default config: no api_key, no auth secret."""
        from thumbelina.api.app import create_app

        config = AppConfig(memory=MemoryConfig(database_url="sqlite:///:memory:"))
        assert config.llm.api_key == ""
        assert config.auth.secret_key == ""

        app = create_app(config)
        assert isinstance(app, FastAPI)

    def test_no_auth_middleware_when_secret_empty(self):
        """Empty secret_key disables the auth middleware."""
        from thumbelina.api.app import _AuthMiddleware, create_app

        config = AppConfig(memory=MemoryConfig(database_url="sqlite:///:memory:"))
        app = create_app(config)
        assert _AuthMiddleware not in self._middleware_classes(app)

    def test_short_secret_key_degrades_gracefully(self):
        """A too-short secret_key disables auth instead of crashing startup."""
        from thumbelina.api.app import _AuthMiddleware, create_app
        from thumbelina.config.models import AuthConfig

        config = AppConfig(
            auth=AuthConfig(secret_key="too-short"),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )
        app = create_app(config)  # must not raise
        assert _AuthMiddleware not in self._middleware_classes(app)

    def test_valid_secret_key_attaches_auth_middleware(self):
        """A valid secret_key attaches the auth middleware."""
        from thumbelina.api.app import _AuthMiddleware, create_app
        from thumbelina.config.models import AuthConfig

        config = AppConfig(
            auth=AuthConfig(secret_key="s" * 48),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )
        app = create_app(config)
        assert _AuthMiddleware in self._middleware_classes(app)

    def test_health_ok_without_llm_credentials(self, mock_agent, mock_memory):
        """Full startup succeeds with empty LLM api_key and no auth secret."""
        from thumbelina.api.app import create_app

        config = AppConfig(
            llm=LLMConfig(api_key=""),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )
        with (
            patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
            patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
            patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
        ):
            app = create_app(config)
            with TestClient(app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_routes_open_when_auth_disabled(self, mock_agent, mock_memory):
        """Protected routes are reachable without a token when auth is off."""
        from thumbelina.api.app import create_app

        config = AppConfig(memory=MemoryConfig(database_url="sqlite:///:memory:"))
        with (
            patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
            patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
            patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
        ):
            app = create_app(config)
            with TestClient(app) as client:
                assert client.get("/api/v1/config").status_code == 200

    def test_unauthenticated_request_rejected_when_auth_enabled(
        self, mock_agent, mock_memory
    ):
        """With a valid secret, non-whitelisted routes require a Bearer token."""
        from thumbelina.api.app import create_app
        from thumbelina.config.models import AuthConfig

        config = AppConfig(
            auth=AuthConfig(secret_key="s" * 48),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )
        with (
            patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
            patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
            patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
        ):
            app = create_app(config)
            with TestClient(app) as client:
                # Whitelisted health endpoint stays open
                assert client.get("/health").status_code == 200
                # Protected route rejects unauthenticated requests
                assert client.get("/api/v1/config").status_code == 401
