"""Tests for thumbelina.api.app module."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_create_app_returns_fastapi():
    """create_app should return a FastAPI instance."""
    from thumbelina.api.app import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_app_has_title():
    """App should have the correct title."""
    from thumbelina.api.app import create_app

    app = create_app()
    assert app.title == "Thumbelina API"


def test_app_has_version():
    """App should have a version."""
    from thumbelina.api.app import create_app

    app = create_app()
    assert app.version == "0.1.0"


def test_health_endpoint():
    """GET /health should return status ok."""
    from thumbelina.api.app import create_app

    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_cors_allows_all_origins():
    """CORS middleware should be configured to allow all origins."""
    from thumbelina.api.app import create_app

    app = create_app()
    # Verify CORS middleware is present
    middleware_classes = [
        m.cls.__name__ for m in app.user_middleware
    ]
    assert "CORSMiddleware" in middleware_classes


def test_cors_options_request():
    """CORS preflight request should succeed."""
    from thumbelina.api.app import create_app

    app = create_app()
    client = TestClient(app)
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200


def test_app_includes_chat_router():
    """App should include the chat router."""
    from thumbelina.api.app import create_app

    app = create_app()
    # Check that /api/chat route exists
    routes = [r.path for r in app.routes]
    assert "/api/chat" in routes


def test_app_includes_conversations_router():
    """App should include the conversations router."""
    from thumbelina.api.app import create_app

    app = create_app()
    routes = [r.path for r in app.routes]
    assert "/api/conversations" in routes
    assert "/api/conversations/{conversation_id}" in routes
