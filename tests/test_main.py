"""Tests for thumbelina.main module."""

from fastapi.testclient import TestClient


def test_health_endpoint():
    from thumbelina.main import create_app

    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_create_app_returns_fastapi():
    from fastapi import FastAPI

    from thumbelina.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)
