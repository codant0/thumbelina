"""Tests for thumbelina.api.routes.conversations module."""

from __future__ import annotations

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
