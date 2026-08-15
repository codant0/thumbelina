"""WebSocket handler for real-time chat."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from weakref import WeakValueDictionary

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes.chat import (
    _apply_conversation_endpoint,
    _apply_conversation_role,
    resolve_context_window_tokens,
)
from thumbelina.api.schemas import WebSocketMessage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# WebSocket message size limit (1MB)
MAX_MESSAGE_SIZE = 1024 * 1024

# Connected chat WebSocket clients (used for cross-channel message broadcast)
_chat_ws_clients: set[WebSocket] = set()

# 按会话加锁，串行化跨连接的轮次。多个 WebSocket 连接（以及 HTTP
# chat 路由）可能同时指向同一会话；同一线程的 LangGraph 检查点更新
# 绝不能交错，因此每轮都持有该会话的锁。条目是弱引用：锁只在至少
# 有一轮持有它时存活，因此会话在连接关闭后绝不会泄漏锁。
_conversation_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_conversation_locks_guard = asyncio.Lock()


async def _conversation_lock_for(cid: str) -> asyncio.Lock:
    """返回 *cid* 的共享锁，首次使用时创建。"""
    async with _conversation_locks_guard:
        lock = _conversation_locks.get(cid)
        if lock is None:
            lock = asyncio.Lock()
            _conversation_locks[cid] = lock
        return lock


@asynccontextmanager
async def _per_conversation_lock(cid: str | None) -> AsyncIterator[None]:
    """跨连接串行化单个会话的轮次。

    ``cid=None``（无会话、临时 thread id —— 没有可冲突的对象）时
    立即 yield。锁在退出时释放；一旦没有轮次持有它，
    注册表条目即因弱引用而消亡。
    """
    if cid is None:
        yield
        return
    lock = await _conversation_lock_for(cid)
    async with lock:
        yield


async def broadcast_chat_message(message: dict[str, Any]) -> None:
    """Broadcast a message to all connected chat WebSocket clients.

    Used by channel integrations (e.g. WeChat) to push incoming messages
    to the frontend in real-time.
    """
    failed: list[WebSocket] = []
    for ws in _chat_ws_clients:
        try:
            await ws.send_json(message)
        except Exception:
            failed.append(ws)
    for ws in failed:
        _chat_ws_clients.discard(ws)
    if _chat_ws_clients:
        logger.debug("Broadcast to %d client(s): %s", len(_chat_ws_clients), list(message.keys()))


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat.

    Accepts JSON messages with a ``message`` field and responds with
    a JSON object containing a ``response`` field.

    Each WebSocket connection gets its own isolated agent clone so that
    concurrent connections do not interfere with each other.
    """
    await websocket.accept()
    _chat_ws_clients.add(websocket)
    logger.debug("WebSocket client connected (total: %d)", len(_chat_ws_clients))

    shared_agent: ThumbelinaAgent = websocket.app.state.agent

    # Clone the agent per connection to isolate conversation state
    agent = shared_agent.clone()

    # Conversation is created lazily on first message, not on connect.
    default_conversation_id: str | None = None

    try:
        while True:
            raw_text = await websocket.receive_text()

            if len(raw_text.encode("utf-8")) > MAX_MESSAGE_SIZE:
                await websocket.send_json({"error": "Message too large"})
                continue

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            # Handle conversation switch (no message payload)
            if "switch_conversation" in data:
                new_cid = data["switch_conversation"]
                if new_cid and agent.memory_manager:
                    existing = await agent.memory_manager.get_conversation(new_cid)
                    if existing is None:
                        await websocket.send_json({"error": f"Conversation not found: {new_cid}"})
                        continue
                default_conversation_id = new_cid
                await websocket.send_json(
                    {
                        "conversation_switched": True,
                        "conversation_id": new_cid,
                    }
                )
                continue

            # Validate incoming message via Pydantic schema
            try:
                parsed = WebSocketMessage.model_validate(data)
            except ValidationError:
                await websocket.send_json({"error": "Invalid message format"})
                continue

            if not parsed.message.strip():
                await websocket.send_json({"error": "Empty message"})
                continue

            # Use client-supplied conversation_id, or fall back to default.
            cid = parsed.conversation_id or default_conversation_id
            if not cid and agent.memory_manager:
                cid = await agent.memory_manager.create_conversation()
                default_conversation_id = cid
                await websocket.send_json({"conversation_created": cid})
            if cid and agent.memory_manager:
                existing = await agent.memory_manager.get_conversation(cid)
                if existing is None:
                    await websocket.send_json({"error": f"Conversation not found: {cid}"})
                    continue
            # 按会话跨连接串行化轮次：多个 WebSocket 连接可能指向
            # 同一会话，同一线程的检查点更新绝不能交错。
            # cid=None（无 memory manager）直接放行。
            async with _per_conversation_lock(cid):
                if cid:
                    agent.current_conversation_id = cid
                    # Apply per-conversation model selection when configured
                    await _apply_conversation_endpoint(websocket, agent, cid)
                    # Apply per-conversation role override when configured
                    await _apply_conversation_role(agent, cid)

                # 解析会话的上下文窗口（会话端点 → 全局活跃端点 →
                # llm.context_window），供压缩阶段使用。会话没有端点或
                # 未配置窗口时回退到默认窗口。
                window_tokens = await resolve_context_window_tokens(
                    agent.memory_manager,
                    getattr(websocket.app.state, "endpoint_manager", None),
                    cid,
                    websocket.app.state.config.llm.context_window_tokens,
                )

                # Check if this is the WeChat conversation using the cached ID
                wechat_cid = getattr(websocket.app.state, "wechat_conversation_id", None)
                is_wechat_conversation = cid and wechat_cid and cid == wechat_cid

                if is_wechat_conversation:
                    wechat_channel = getattr(websocket.app.state, "wechat_channel", None)
                    if wechat_channel is not None:
                        try:
                            # Apply the conversation's endpoint to the WeChat channel agent
                            await _apply_conversation_endpoint(
                                websocket, wechat_channel._agent, cid
                            )
                        except Exception as exc:
                            logger.warning("Failed to apply WeChat endpoint: %s", exc)

                # Use streaming for frontend, regardless of WeChat binding
                try:
                    streaming = websocket.app.state.config.llm.streaming_enabled
                    full_response = ""
                    if streaming:
                        try:
                            async for event in agent.stream(
                                parsed.message, context_window_tokens=window_tokens
                            ):
                                text = event["text"]
                                if event["type"] == "reasoning":
                                    await websocket.send_json(
                                        {
                                            "chunk": text,
                                            "chunk_type": "reasoning",
                                            "conversation_id": cid,
                                        }
                                    )
                                else:
                                    full_response += text
                                    await websocket.send_json(
                                        {"chunk": text, "conversation_id": cid}
                                    )
                        except Exception:
                            # Fallback to non-streaming if streaming fails
                            full_response = await agent.run(
                                parsed.message, context_window_tokens=window_tokens
                            )
                            await websocket.send_json(
                                {"response": full_response, "conversation_id": cid}
                            )
                    else:
                        full_response = await agent.run(
                            parsed.message, context_window_tokens=window_tokens
                        )
                        await websocket.send_json(
                            {"response": full_response, "conversation_id": cid}
                        )

                    await websocket.send_json(
                        {
                            "done": True,
                            "conversation_id": cid,
                            "streaming_mode": streaming,
                        }
                    )

                    # Sync to WeChat if this is a WeChat conversation
                    if is_wechat_conversation and full_response:
                        wechat_channel = getattr(websocket.app.state, "wechat_channel", None)
                        if wechat_channel is not None:
                            logger.info("Sending frontend message response to WeChat")
                            try:
                                last_wechat_user = getattr(
                                    wechat_channel, "_last_wechat_user_id", None
                                )
                                last_context_token = getattr(
                                    wechat_channel, "_last_context_token", ""
                                )

                                if last_wechat_user:
                                    await wechat_channel.send_message(
                                        last_wechat_user,
                                        full_response,
                                        context_token=last_context_token,
                                    )
                                    logger.info("Sent response to WeChat user %s", last_wechat_user)
                                else:
                                    logger.warning(
                                        "No WeChat user ID available to send response to"
                                    )
                            except Exception as send_exc:
                                logger.warning("Failed to send response to WeChat: %s", send_exc)

                except Exception as exc:
                    await websocket.send_json({"error": str(exc), "conversation_id": cid})

    except WebSocketDisconnect:
        pass
    finally:
        _chat_ws_clients.discard(websocket)
        logger.debug("WebSocket client disconnected (total: %d)", len(_chat_ws_clients))
