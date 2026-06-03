"""Tests for thumbelina.main module."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig


def test_health_endpoint():
    from thumbelina.main import create_app

    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )

    # Mock MemoryManager and its repository
    mock_memory = MagicMock()
    mock_memory.repository = MagicMock()
    mock_memory.repository.ping = AsyncMock(return_value=True)
    mock_memory.close = MagicMock()

    with (
        patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=MagicMock()),
    ):
        app = create_app(config)
        with TestClient(app) as client:
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

    with (
        patch("thumbelina.api.app.MemoryManager"),
        patch("thumbelina.api.app.create_provider"),
        patch("thumbelina.api.app.ThumbelinaAgent"),
    ):
        app = create_app(config)
        assert isinstance(app, FastAPI)
