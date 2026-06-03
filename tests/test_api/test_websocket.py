"""Tests for thumbelina.api.websocket module."""

from __future__ import annotations


def _collect_ws_messages(ws, max_messages: int = 10) -> list[dict]:
    """Collect JSON messages from a WebSocket until 'done' or max reached."""
    messages = []
    for _ in range(max_messages):
        data = ws.receive_json()
        messages.append(data)
        if data.get("done"):
            break
    return messages


def test_websocket_endpoint_exists(client):
    """WS /ws/chat should accept connections."""
    with client.websocket_connect("/ws/chat") as ws:
        assert ws is not None


def test_websocket_receives_streaming_response(client):
    """WS /ws/chat should stream chunks followed by done marker."""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        messages = _collect_ws_messages(ws)

        # Should have at least one chunk and a done marker
        chunks = [m for m in messages if "chunk" in m]
        done = [m for m in messages if m.get("done")]
        assert len(chunks) > 0
        assert len(done) == 1


def test_websocket_multiple_messages(client):
    """WS /ws/chat should handle multiple messages."""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        msgs1 = _collect_ws_messages(ws)
        assert any(m.get("done") for m in msgs1)

        ws.send_json({"message": "How are you?"})
        msgs2 = _collect_ws_messages(ws)
        assert any(m.get("done") for m in msgs2)


def test_websocket_json_response_structure(client):
    """WS /ws/chat streaming response should have correct structure."""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        messages = _collect_ws_messages(ws)

        chunks = [m for m in messages if "chunk" in m]
        assert len(chunks) > 0
        assert isinstance(chunks[0]["chunk"], str)

        done = [m for m in messages if m.get("done")]
        assert len(done) == 1
