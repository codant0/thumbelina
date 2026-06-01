"""Tests for thumbelina.api.websocket module."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client."""
    from thumbelina.api.app import create_app

    app = create_app()
    return TestClient(app)


def test_websocket_endpoint_exists(client):
    """WS /ws/chat should accept connections."""
    with client.websocket_connect("/ws/chat") as ws:
        # Connection should be established
        assert ws is not None


def test_websocket_receives_response(client):
    """WS /ws/chat should respond to messages."""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        data = ws.receive_json()
        assert "response" in data


def test_websocket_multiple_messages(client):
    """WS /ws/chat should handle multiple messages."""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        data1 = ws.receive_json()
        assert "response" in data1

        ws.send_json({"message": "How are you?"})
        data2 = ws.receive_json()
        assert "response" in data2


def test_websocket_json_response_structure(client):
    """WS /ws/chat response should have correct JSON structure."""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        data = ws.receive_json()
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0
