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

    # Give the shared agent a repository manager that knows about the WeChat conv.
    mm = MagicMock()
    mm.get_conversation = AsyncMock(
        return_value={"id": wechat_conv_id, "name": "微信Clawbot", "pinned": True}
    )
    app.state.agent.repository_manager = mm
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
    """流式路径应接收到解析出的上下文窗口。"""
    recorded = {}

    async def _stream(message, context_window_tokens=None, attachments=None):
        recorded["message"] = message
        recorded["window"] = context_window_tokens
        yield {"type": "content", "text": "ok"}

    client.app.state.agent.stream = _stream

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        messages = _collect_ws_messages(ws)

    assert recorded["message"] == "Hello"
    # fixture 中未配置端点 → 使用 llm.context_window 默认值（128K）。
    assert recorded["window"] == 128_000
    assert any(m.get("done") for m in messages)


def test_websocket_passes_context_window_to_run_when_not_streaming(client):
    """非流式路径应接收到解析出的上下文窗口。"""
    client.app.state.config.llm.streaming_enabled = False

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        _collect_ws_messages(ws)

    run_kwargs = client.app.state.agent.run.await_args.kwargs
    assert run_kwargs["context_window_tokens"] == 128_000


@pytest.mark.asyncio
async def test_conversation_lock_is_shared_and_does_not_leak():
    """一个会话对应一把锁；条目在被解除引用后消亡。"""
    from thumbelina.concurrency import _conversation_locks, conversation_lock_for

    lock_a = await conversation_lock_for("cid-a")
    lock_a2 = await conversation_lock_for("cid-a")
    lock_b = await conversation_lock_for("cid-b")
    assert lock_a is lock_a2
    assert lock_a is not lock_b

    del lock_a, lock_a2, lock_b
    # 不再有任何轮次持有锁，因此弱引用注册表丢弃了这些条目。
    assert "cid-a" not in _conversation_locks
    assert "cid-b" not in _conversation_locks


@pytest.mark.asyncio
async def test_per_conversation_lock_none_cid_passes_through():
    """cid=None（无会话）时绝不能分配任何锁。"""
    from thumbelina.concurrency import _conversation_locks, per_conversation_lock

    async with per_conversation_lock(None):
        pass
    assert len(_conversation_locks) == 0


@pytest.mark.asyncio
async def test_websocket_serializes_same_conversation_turns():
    """指向同一会话的两个连接必须串行执行各轮。

    生成现在跑在独立任务中，连接保持打开（与真实前端一致）；两个连接
    指向同一会话时，第二个必须停在 per-conversation 锁上等待第一个
    结束。第一个连接在完成后才断开。
    """
    from thumbelina.api import websocket as ws

    order = []
    gate = asyncio.Event()
    first_started = asyncio.Event()

    async def _stream(message, context_window_tokens=None, attachments=None):
        order.append(("start", message))
        if message == "first":
            first_started.set()
            await gate.wait()
        order.append(("end", message))
        yield {"type": "content", "text": "ok"}

    agent = SimpleNamespace()
    agent.clone = lambda: agent
    agent.repository_manager = None
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
            self.disconnect = asyncio.Event()

        async def accept(self) -> None:
            pass

        async def receive_text(self) -> str:
            # 先投递一条消息，然后保持连接打开，直到被要求断开。
            if self._message is not None:
                message, self._message = self._message, None
                return json.dumps({"message": message, "conversation_id": "cid-lock"})
            await self.disconnect.wait()
            raise WebSocketDisconnect()

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    first_ws = FakeWS("first")
    second_ws = FakeWS("second")
    first = asyncio.create_task(ws.websocket_chat(first_ws))
    await first_started.wait()
    second = asyncio.create_task(ws.websocket_chat(second_ws))
    # 第二个轮次必须停在会话锁上等待。
    await asyncio.sleep(0.05)
    assert order == [("start", "first")]
    gate.set()
    # 等两个轮次都完成。
    for _ in range(200):
        if len(order) >= 4:
            break
        await asyncio.sleep(0.01)
    # 断开两个连接，让 websocket_chat 协程退出。
    first_ws.disconnect.set()
    second_ws.disconnect.set()
    await asyncio.gather(first, second)
    assert order == [
        ("start", "first"),
        ("end", "first"),
        ("start", "second"),
        ("end", "second"),
    ]


def test_websocket_stop_without_running_task(client):
    """stop 消息在没有进行中任务时应幂等返回 stopped。"""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"stop": True})
        msg = ws.receive_json()
        assert msg.get("stopped") is True
        assert "conversation_id" in msg


def test_websocket_stop_cancels_inflight_generation(client):
    """流式进行中收到 stop 应取消生成并返回 stopped。"""
    import asyncio as _asyncio

    async def _stream(message, context_window_tokens=None, attachments=None):
        yield {"type": "content", "text": "partial"}
        # 保持生成进行中，等待 stop 打断。
        await _asyncio.sleep(30)

    client.app.state.agent.stream = _stream

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hello"})
        # 先读到第一块 partial，确认生成已在进行中。
        chunk = ws.receive_json()
        assert chunk.get("chunk") == "partial"

        # 发送 stop，应取消进行中的生成。
        ws.send_json({"stop": True, "conversation_id": "test-conv-id"})
        stopped = ws.receive_json()
        assert stopped.get("stopped") is True
        assert stopped.get("conversation_id") == "test-conv-id"


def test_websocket_recovers_after_stop(client):
    """被 stop 打断后连接应能继续处理下一条普通消息。"""
    import asyncio as _asyncio

    async def _stream(message, context_window_tokens=None, attachments=None):
        if message == "first":
            yield {"type": "content", "text": "partial"}
            await _asyncio.sleep(30)
        yield {"type": "content", "text": "second reply"}

    client.app.state.agent.stream = _stream

    with client.websocket_connect("/ws/chat") as ws:
        # 第一条消息启动生成后立即 stop。
        ws.send_json({"message": "first"})
        chunk = ws.receive_json()
        assert chunk.get("chunk") == "partial"
        ws.send_json({"stop": True})
        stopped = ws.receive_json()
        assert stopped.get("stopped") is True

        # 第二条普通消息应正常处理并收到 done。
        ws.send_json({"message": "second"})
        msgs = _collect_ws_messages(ws)
        assert any(m.get("chunk") == "second reply" for m in msgs)
        assert any(m.get("done") for m in msgs)
