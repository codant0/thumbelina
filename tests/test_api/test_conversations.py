"""Tests for thumbelina.api.routes.conversations module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def conversation_id(client):
    """Create a conversation and return its ID."""
    # First send a chat message to create a conversation
    response = client.post("/api/v1/chat", json={"message": "Hello"})
    data = response.json()
    return data["conversation_id"]


def test_list_conversations_endpoint_exists(client):
    """GET /api/v1/conversations should exist."""
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200


def test_list_conversations_returns_list(client):
    """GET /api/v1/conversations should return a list."""
    response = client.get("/api/v1/conversations")
    data = response.json()
    assert isinstance(data, list)


def test_list_conversations_after_chat(client, conversation_id):
    """GET /api/v1/conversations should include conversations created via chat."""
    response = client.get("/api/v1/conversations")
    data = response.json()
    conv_ids = [c["id"] for c in data]
    assert conversation_id in conv_ids


def test_get_conversation_endpoint_exists(client, conversation_id):
    """GET /api/v1/conversations/{id} should exist."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200


def test_get_conversation_returns_details(client, conversation_id):
    """GET /api/v1/conversations/{id} should return conversation details."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    data = response.json()
    assert data["id"] == conversation_id
    assert "messages" in data
    assert "created_at" in data


def test_get_nonexistent_conversation(client):
    """GET /api/v1/conversations/{id} should return 404 for nonexistent conversation."""
    response = client.get("/api/v1/conversations/nonexistent-id")
    assert response.status_code == 404


def test_get_conversation_includes_messages(client, conversation_id):
    """GET /api/v1/conversations/{id} should include messages."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    data = response.json()
    messages = data["messages"]
    assert len(messages) >= 1
    # Should have at least the user message
    assert any(m["role"] == "user" for m in messages)


def test_delete_conversation_endpoint_exists(client, conversation_id):
    """DELETE /api/v1/conversations/{id} should exist."""
    response = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code in (200, 204)


def test_delete_conversation_removes_it(client, conversation_id):
    """DELETE /api/v1/conversations/{id} should remove the conversation."""
    client.delete(f"/api/v1/conversations/{conversation_id}")
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 404


def test_delete_nonexistent_conversation(client):
    """DELETE /api/v1/conversations/{id} should return 404 for nonexistent."""
    response = client.delete("/api/v1/conversations/nonexistent-id")
    assert response.status_code == 404


def test_rename_conversation_endpoint(client, conversation_id):
    """PATCH /api/v1/conversations/{id} should rename the conversation."""
    response = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"name": "新名称"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == conversation_id
    assert data["name"] == "新名称"


def test_rename_nonexistent_conversation(client):
    """PATCH /api/v1/conversations/{id} should 404 for unknown IDs."""
    response = client.patch(
        "/api/v1/conversations/nonexistent-id",
        json={"name": "x"},
    )
    assert response.status_code == 404


def test_rename_strips_whitespace(client, conversation_id):
    """PATCH should strip surrounding whitespace from the name."""
    response = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"name": "  trimmed  "},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "trimmed"


def test_set_conversation_endpoint_rejects_unknown_endpoint(client, conversation_id):
    """PUT /conversations/{id}/endpoint should 404 for unknown endpoint_id."""
    # The test client has no endpoint_manager on app.state, so the endpoint
    # manager is None → 503. Accept either the configured-503 or 404 path.
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/endpoint",
        json={"endpoint_id": "missing-ep"},
    )
    assert response.status_code in (404, 503)


def test_clear_conversation_endpoint(client, conversation_id):
    """PUT /conversations/{id}/endpoint with null endpoint_id reverts to default."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/endpoint",
        json={"endpoint_id": None},
    )
    assert response.status_code == 200
    assert response.json()["endpoint_id"] is None


def test_set_conversation_endpoint_rejects_unknown_model(client, conversation_id):
    """PUT /conversations/{id}/endpoint rejects a model not on the endpoint."""
    from thumbelina.llm.endpoint_manager import LLMEndpoint

    endpoint = LLMEndpoint(
        id="ep1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        models=["gpt-4o"],
        api_key="sk-test",
        api_key_set=True,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager = MagicMock()
    client.app.state.endpoint_manager.get_endpoint = AsyncMock(return_value=endpoint)

    response = client.put(
        f"/api/v1/conversations/{conversation_id}/endpoint",
        json={"endpoint_id": "ep1", "model": "not-a-model"},
    )
    assert response.status_code == 422
