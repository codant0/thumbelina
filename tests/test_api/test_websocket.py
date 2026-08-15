"""Tests for thumbelina.api.websocket module."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect


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


def test_websocket_streams_reasoning_chunks(client):
    """Reasoning events should be forwarded with chunk_type='reasoning'."""

    async def _stream(*args, **kwargs):
        yield {"type": "reasoning", "text": "Let me think..."}
        yield {"type": "content", "text": "Final answer"}

    client.app.state.agent.stream = _stream

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        messages = _collect_ws_messages(ws)

        reasoning = [m for m in messages if m.get("chunk_type") == "reasoning"]
        content = [m for m in messages if "chunk" in m and m.get("chunk_type") != "reasoning"]
        assert [m["chunk"] for m in reasoning] == ["Let me think..."]
        assert [m["chunk"] for m in content] == ["Final answer"]
        assert any(m.get("done") for m in messages)


def test_websocket_wechat_conversation_forwards_only_reply(client):
    """When chatting in the WeChat conversation, only the agent's reply is
    forwarded to WeChat (iLink bot sends as the bot, so the user's web-side
    question would be indistinguishable from a bot reply)."""
    app = client.app
    wechat_channel = MagicMock()
    wechat_channel.send_message = AsyncMock()
    wechat_channel._last_wechat_user_id = "wxid_friend"
    wechat_channel._last_context_token = "tok-123"
    app.state.wechat_channel = wechat_channel
    wechat_conv_id = "wechat-conv-1"
    app.state.wechat_conversation_id = wechat_conv_id

    # Give the shared agent a memory manager that knows about the WeChat conv.
    mm = MagicMock()
    mm.get_conversation = AsyncMock(
        return_value={"id": wechat_conv_id, "name": "微信Clawbot", "pinned": True}
    )
    app.state.agent.memory_manager = mm
    app.state.agent.current_conversation_id = wechat_conv_id
    app.state.agent.clone.return_value = app.state.agent
    # Non-streaming so the response comes back as a single payload
    app.state.config.llm.streaming_enabled = False

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello from web", "conversation_id": wechat_conv_id})
        messages = _collect_ws_messages(ws)
        assert any(m.get("response") == "Agent response" for m in messages)

    # Only the reply should be forwarded to WeChat, not the user's question
    sent_texts = [call.args[1] for call in wechat_channel.send_message.call_args_list]
    assert sent_texts == ["Agent response"]
    assert wechat_channel.send_message.call_count == 1
    assert wechat_channel.send_message.call_args.kwargs.get("context_token") == "tok-123"


def test_websocket_passes_context_window_to_stream(client):
    """The streaming path should receive the resolved context window."""
    recorded = {}

    async def _stream(message, context_window_tokens=None):
        recorded["message"] = message
        recorded["window"] = context_window_tokens
        yield {"type": "content", "text": "ok"}

    client.app.state.agent.stream = _stream

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        messages = _collect_ws_messages(ws)

    assert recorded["message"] == "Hello"
    # No endpoints configured in the fixture → llm.context_window default (128K).
    assert recorded["window"] == 128_000
    assert any(m.get("done") for m in messages)


def test_websocket_passes_context_window_to_run_when_not_streaming(client):
    """The non-streaming path should receive the resolved context window."""
    client.app.state.config.llm.streaming_enabled = False

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        _collect_ws_messages(ws)

    run_kwargs = client.app.state.agent.run.await_args.kwargs
    assert run_kwargs["context_window_tokens"] == 128_000


@pytest.mark.asyncio
async def test_conversation_lock_is_shared_and_does_not_leak():
    """One conversation maps to one lock; entries die once unreferenced."""
    from thumbelina.api import websocket as ws

    lock_a = await ws._conversation_lock_for("cid-a")
    lock_a2 = await ws._conversation_lock_for("cid-a")
    lock_b = await ws._conversation_lock_for("cid-b")
    assert lock_a is lock_a2
    assert lock_a is not lock_b

    del lock_a, lock_a2, lock_b
    # No turn holds any lock anymore, so the weak registry drops the entries.
    assert "cid-a" not in ws._conversation_locks
    assert "cid-b" not in ws._conversation_locks


@pytest.mark.asyncio
async def test_per_conversation_lock_none_cid_passes_through():
    """cid=None (no conversation) must not allocate any lock."""
    from thumbelina.api import websocket as ws

    async with ws._per_conversation_lock(None):
        pass
    assert len(ws._conversation_locks) == 0


@pytest.mark.asyncio
async def test_websocket_serializes_same_conversation_turns():
    """Two connections targeting one conversation must run turns sequentially."""
    from thumbelina.api import websocket as ws

    order = []
    gate = asyncio.Event()
    first_started = asyncio.Event()

    async def _stream(message, context_window_tokens=None):
        order.append(("start", message))
        if message == "first":
            first_started.set()
            await gate.wait()
        order.append(("end", message))
        yield {"type": "content", "text": "ok"}

    agent = SimpleNamespace()
    agent.clone = lambda: agent
    agent.memory_manager = None
    agent.current_conversation_id = None
    agent.stream = _stream

    state = SimpleNamespace(
        agent=agent,
        config=SimpleNamespace(
            llm=SimpleNamespace(streaming_enabled=True, context_window_tokens=128_000)
        ),
    )

    class FakeWS:
        def __init__(self, message: str) -> None:
            self.app = SimpleNamespace(state=state)
            self.sent: list[dict] = []
            self._message: str | None = message

        async def accept(self) -> None:
            pass

        async def receive_text(self) -> str:
            if self._message is None:
                raise WebSocketDisconnect()
            message, self._message = self._message, None
            return json.dumps({"message": message, "conversation_id": "cid-lock"})

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    first = asyncio.create_task(ws.websocket_chat(FakeWS("first")))
    await first_started.wait()
    second = asyncio.create_task(ws.websocket_chat(FakeWS("second")))
    # The second turn must be parked on the conversation lock.
    await asyncio.sleep(0.05)
    assert order == [("start", "first")]
    gate.set()
    await asyncio.gather(first, second)
    assert order == [
        ("start", "first"),
        ("end", "first"),
        ("start", "second"),
        ("end", "second"),
    ]
