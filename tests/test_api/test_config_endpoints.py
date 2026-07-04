from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.api.app import create_app
from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig
from thumbelina.llm.base import SpeedTestResult
from thumbelina.llm.endpoint_manager import EndpointManager, LLMEndpoint


@pytest.fixture
def client():
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    app = create_app(config)
    app.state.endpoint_manager = MagicMock(spec=EndpointManager)
    with TestClient(app) as client:
        yield client


def test_list_endpoints(client):
    client.app.state.endpoint_manager.list_endpoints = AsyncMock(return_value=[])
    response = client.get("/api/v1/config/llm/endpoints")
    assert response.status_code == 200
    assert response.json() == []


def test_create_endpoint(client):
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        api_key_set=True,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager.create_endpoint = AsyncMock(return_value=endpoint)
    response = client.post(
        "/api/v1/config/llm/endpoints",
        json={
            "provider": "openai",
            "name": "Default",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "openai"
    assert "api_key" not in data
    assert data["api_key_set"] is True


@pytest.fixture
def live_client():
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    app = create_app(config)
    with TestClient(app) as client:
        yield client


def test_app_state_has_endpoint_manager(live_client):
    assert hasattr(live_client.app.state, "endpoint_manager")
    assert live_client.app.state.endpoint_manager is not None
