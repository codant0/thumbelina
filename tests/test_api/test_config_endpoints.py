from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.api.app import create_app
from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig
from thumbelina.llm.base import ConnectionTestDetails, ConnectionTestResult, ConnectionTestStep
from thumbelina.llm.endpoint_manager import EndpointManager, LLMEndpoint
from thumbelina.llm.preset_manager import PresetManager
from thumbelina.llm.preset_models import LLMPresetResponse


@pytest.fixture
def client():
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    app = create_app(config)
    app.state.endpoint_manager = MagicMock(spec=EndpointManager)
    app.state.preset_manager = MagicMock(spec=PresetManager)
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


def test_create_endpoint_response_includes_context_window(client):
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        api_key_set=True,
        context_window="128K",
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
            "context_window": "128K",
        },
    )
    assert response.status_code == 201
    assert response.json()["context_window"] == "128K"

    # 没有该字段的历史端点会把它序列化为 null。
    legacy = LLMEndpoint(
        id="e2",
        provider="openai",
        name="Legacy",
        base_url="https://api.openai.com/v1",
        api_key_set=False,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager.list_endpoints = AsyncMock(return_value=[legacy])
    response = client.get("/api/v1/config/llm/endpoints")
    assert response.status_code == 200
    assert response.json()[0]["context_window"] is None


def test_create_endpoint_rejects_invalid_context_window(client):
    client.app.state.endpoint_manager.create_endpoint = AsyncMock()
    response = client.post(
        "/api/v1/config/llm/endpoints",
        json={
            "provider": "openai",
            "name": "Default",
            "base_url": "https://api.openai.com/v1",
            "context_window": "12X",
        },
    )
    assert response.status_code == 422
    client.app.state.endpoint_manager.create_endpoint.assert_not_awaited()


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


def test_list_models_returns_empty_list(client):
    """Test that endpoints returning empty model lists produce 200."""
    client.app.state.endpoint_manager.list_endpoints = AsyncMock(return_value=[])
    mock_provider = MagicMock()
    mock_provider.list_models = AsyncMock(return_value=[])

    with patch("thumbelina.api.routes.config.create_provider", return_value=mock_provider):
        response = client.get(
            "/api/v1/config/llm/models",
            params={
                "provider": "openai",
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["base_url"] == "https://api.deepseek.com"
    assert data["models"] == []


def test_test_connection_arbitrary_params(client):
    """Test POST /config/llm/test-connection with arbitrary params."""
    mock_provider = MagicMock()
    mock_provider.test_connection = AsyncMock(
        return_value=ConnectionTestResult(
            reachable=True,
            network_reachable=True,
            auth_valid=True,
            service_available=True,
            latency_ms=123,
            details=ConnectionTestDetails(
                network=ConnectionTestStep(ok=True, latency_ms=10),
                auth=ConnectionTestStep(ok=True, latency_ms=20),
                service=ConnectionTestStep(ok=True, latency_ms=123),
            ),
        )
    )

    with patch("thumbelina.api.routes.config.create_provider", return_value=mock_provider):
        response = client.post(
            "/api/v1/config/llm/test-connection",
            json={
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["reachable"] is True
    assert data["network_reachable"] is True
    assert data["auth_valid"] is True
    assert data["service_available"] is True
    assert data["details"]["network"]["ok"] is True


def test_test_connection_endpoint_not_found(client):
    """Test POST /config/llm/endpoints/{id}/test-connection returns 404."""
    client.app.state.endpoint_manager.test_connection = AsyncMock(return_value=None)
    response = client.post("/api/v1/config/llm/endpoints/missing/test-connection")
    assert response.status_code == 404


def test_activate_endpoint_model(client):
    """POST /config/llm/endpoints/{id}/activate activates a specific model."""
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        models=["gpt-4o", "gpt-4o-mini"],
        api_key="sk-test",
        api_key_set=True,
        is_default=True,
        active_model="gpt-4o-mini",
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager.activate_model = AsyncMock(return_value=endpoint)
    # Avoid hitting the real runtime hot-swap in this unit test.
    runtime_manager = MagicMock()
    runtime_manager.swap_llm_provider = AsyncMock()
    client.app.state.runtime_config_manager = runtime_manager
    agent = MagicMock()
    agent.llm_provider = MagicMock()
    client.app.state.agent = agent
    client.app.state.conversation_namer = None

    response = client.post(
        "/api/v1/config/llm/endpoints/e1/activate",
        json={"model": "gpt-4o-mini"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["models"] == ["gpt-4o", "gpt-4o-mini"]
    assert data["active_model"] == "gpt-4o-mini"
    assert data["is_default"] is True
    client.app.state.endpoint_manager.activate_model.assert_awaited_once_with("e1", "gpt-4o-mini")


def test_activate_endpoint_model_rejects_unknown(client):
    """Activating a model not in the endpoint's list returns 422."""
    client.app.state.endpoint_manager.activate_model = AsyncMock(side_effect=ValueError("nope"))
    response = client.post(
        "/api/v1/config/llm/endpoints/e1/activate",
        json={"model": "not-a-model"},
    )
    assert response.status_code == 422


def test_test_connection_saved_endpoint(client):
    """Test POST /config/llm/endpoints/{id}/test-connection with saved endpoint."""
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        api_key_set=True,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager.get_endpoint = AsyncMock(return_value=endpoint)
    client.app.state.endpoint_manager.test_connection = AsyncMock(
        return_value=ConnectionTestResult(
            reachable=False,
            network_reachable=True,
            auth_valid=False,
            service_available=False,
            error="HTTP 401",
            details=ConnectionTestDetails(
                network=ConnectionTestStep(ok=True, latency_ms=10),
                auth=ConnectionTestStep(ok=False, latency_ms=20, error="HTTP 401"),
                service=ConnectionTestStep(ok=False),
            ),
        )
    )

    response = client.post("/api/v1/config/llm/endpoints/e1/test-connection")

    assert response.status_code == 200
    data = response.json()
    assert data["endpoint_id"] == "e1"
    assert data["reachable"] is False
    assert data["details"]["auth"]["ok"] is False


def _sample_preset_response(preset_id: str = "p1") -> LLMPresetResponse:
    from datetime import UTC, datetime

    return LLMPresetResponse(
        id=preset_id,
        name="OpenAI Default",
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key_set=True,
        model="gpt-4o",
        extra_params={},
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_list_presets(client):
    client.app.state.preset_manager.list_presets = AsyncMock(
        return_value=[_sample_preset_response("p1")]
    )
    response = client.get("/api/v1/config/llm/presets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "p1"
    assert "api_key" not in data[0]


def test_create_preset(client):
    client.app.state.preset_manager.create_preset = AsyncMock(
        return_value=_sample_preset_response("p2")
    )
    response = client.post(
        "/api/v1/config/llm/presets",
        json={
            "name": "OpenAI Default",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4o",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "p2"
    assert "api_key" not in data
    assert data["api_key_set"] is True


def test_get_preset(client):
    client.app.state.preset_manager.get_preset = AsyncMock(
        return_value=_sample_preset_response("p1")
    )
    response = client.get("/api/v1/config/llm/presets/p1")
    assert response.status_code == 200
    assert response.json()["id"] == "p1"


def test_get_preset_not_found(client):
    client.app.state.preset_manager.get_preset = AsyncMock(return_value=None)
    response = client.get("/api/v1/config/llm/presets/missing")
    assert response.status_code == 404


def test_update_preset(client):
    client.app.state.preset_manager.update_preset = AsyncMock(
        return_value=_sample_preset_response("p1")
    )
    response = client.put(
        "/api/v1/config/llm/presets/p1",
        json={"name": "Updated"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "p1"


def test_delete_preset(client):
    client.app.state.preset_manager.delete_preset = AsyncMock(return_value=True)
    response = client.delete("/api/v1/config/llm/presets/p1")
    assert response.status_code == 204


def test_delete_preset_not_found(client):
    client.app.state.preset_manager.delete_preset = AsyncMock(return_value=False)
    response = client.delete("/api/v1/config/llm/presets/missing")
    assert response.status_code == 404


def test_activate_preset(client):
    from thumbelina.llm.preset_models import LLMPresetActivateResponse

    client.app.state.preset_manager.activate_preset = AsyncMock(
        return_value=LLMPresetActivateResponse(
            status="ok",
            preset_id="p1",
            preset_name="OpenAI Default",
            provider="openai",
            model="gpt-4o",
        )
    )
    response = client.post("/api/v1/config/llm/presets/p1/activate")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["preset_id"] == "p1"
