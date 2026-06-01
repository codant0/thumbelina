"""Tests for thumbelina.api.routes.chat module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with a mocked agent."""
    from thumbelina.api.app import create_app

    app = create_app()
    return TestClient(app)


def test_chat_endpoint_exists(client):
    """POST /api/chat should exist."""
    response = client.post("/api/chat", json={"message": "hello"})
    # Should not be 404
    assert response.status_code != 404


def test_chat_requires_message_field(client):
    """POST /api/chat should require a message field."""
    response = client.post("/api/chat", json={})
    assert response.status_code == 422


def test_chat_accepts_message(client):
    """POST /api/chat should accept a message and return a response."""
    response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "conversation_id" in data


def test_chat_response_structure(client):
    """POST /api/chat response should have the correct structure."""
    response = client.post("/api/chat", json={"message": "Hello"})
    data = response.json()
    assert isinstance(data["response"], str)
    assert isinstance(data["conversation_id"], str)


def test_chat_with_conversation_id(client):
    """POST /api/chat should accept an optional conversation_id."""
    # First create a conversation
    create_response = client.post("/api/chat", json={"message": "Hello"})
    conversation_id = create_response.json()["conversation_id"]

    # Then continue the conversation
    response = client.post(
        "/api/chat",
        json={"message": "Follow up", "conversation_id": conversation_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == conversation_id


def test_chat_empty_message_rejected(client):
    """POST /api/chat should reject empty messages."""
    response = client.post("/api/chat", json={"message": ""})
    assert response.status_code == 422
