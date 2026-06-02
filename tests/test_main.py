"""Tests for thumbelina.main module."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig


def test_health_endpoint():
    from thumbelina.main import create_app

    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    app = create_app(config)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_create_app_returns_fastapi():
    from thumbelina.main import create_app

    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    app = create_app(config)
    assert isinstance(app, FastAPI)
