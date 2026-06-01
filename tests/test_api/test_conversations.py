"""Tests for thumbelina.api.routes.conversations module."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client."""
    from thumbelina.api.app import create_app

    app = create_app()
    return TestClient(app)


@pytest.fixture
def conversation_id(client):
    """Create a conversation and return its ID."""
    # First send a chat message to create a conversation
    response = client.post("/api/chat", json={"message": "Hello"})
    data = response.json()
    return data["conversation_id"]


def test_list_conversations_endpoint_exists(client):
    """GET /api/conversations should exist."""
    response = client.get("/api/conversations")
    assert response.status_code == 200


def test_list_conversations_returns_list(client):
    """GET /api/conversations should return a list."""
    response = client.get("/api/conversations")
    data = response.json()
    assert isinstance(data, list)


def test_list_conversations_after_chat(client, conversation_id):
    """GET /api/conversations should include conversations created via chat."""
    response = client.get("/api/conversations")
    data = response.json()
    conv_ids = [c["id"] for c in data]
    assert conversation_id in conv_ids


def test_get_conversation_endpoint_exists(client, conversation_id):
    """GET /api/conversations/{id} should exist."""
    response = client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200


def test_get_conversation_returns_details(client, conversation_id):
    """GET /api/conversations/{id} should return conversation details."""
    response = client.get(f"/api/conversations/{conversation_id}")
    data = response.json()
    assert data["id"] == conversation_id
    assert "messages" in data
    assert "created_at" in data


def test_get_nonexistent_conversation(client):
    """GET /api/conversations/{id} should return 404 for nonexistent conversation."""
    response = client.get("/api/conversations/nonexistent-id")
    assert response.status_code == 404


def test_get_conversation_includes_messages(client, conversation_id):
    """GET /api/conversations/{id} should include messages."""
    response = client.get(f"/api/conversations/{conversation_id}")
    data = response.json()
    messages = data["messages"]
    assert len(messages) >= 1
    # Should have at least the user message
    assert any(m["role"] == "user" for m in messages)


def test_delete_conversation_endpoint_exists(client, conversation_id):
    """DELETE /api/conversations/{id} should exist."""
    response = client.delete(f"/api/conversations/{conversation_id}")
    assert response.status_code in (200, 204)


def test_delete_conversation_removes_it(client, conversation_id):
    """DELETE /api/conversations/{id} should remove the conversation."""
    client.delete(f"/api/conversations/{conversation_id}")
    response = client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 404


def test_delete_nonexistent_conversation(client):
    """DELETE /api/conversations/{id} should return 404 for nonexistent."""
    response = client.delete("/api/conversations/nonexistent-id")
    assert response.status_code == 404
