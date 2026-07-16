"""Tests for thumbelina.api.app module."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

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
    """Recursively collect all route paths from a FastAPI app."""
    paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        if hasattr(route, "routes"):
            # Included sub-router — recurse into its child routes
            for child in route.routes:
                if hasattr(child, "path"):
                    paths.add(child.path)
    return paths


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
