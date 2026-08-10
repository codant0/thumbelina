"""WebSocket handler for real-time chat."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes.chat import _apply_conversation_endpoint
from thumbelina.api.schemas import WebSocketMessage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# WebSocket message size limit (1MB)
MAX_MESSAGE_SIZE = 1024 * 1024

# Connected chat WebSocket clients (used for cross-channel message broadcast)
_chat_ws_clients: set[WebSocket] = set()


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
            if cid:
                agent.current_conversation_id = cid
                # Apply per-conversation model selection when configured
                await _apply_conversation_endpoint(websocket, agent, cid)

            # Check if this is the WeChat conversation using the cached ID
            wechat_cid = getattr(websocket.app.state, "wechat_conversation_id", None)
            is_wechat_conversation = cid and wechat_cid and cid == wechat_cid

            if is_wechat_conversation:
                wechat_channel = getattr(websocket.app.state, "wechat_channel", None)
                if wechat_channel is not None:
                    try:
                        # Apply the conversation's endpoint to the WeChat channel agent
                        await _apply_conversation_endpoint(websocket, wechat_channel._agent, cid)
                    except Exception as exc:
                        logger.warning("Failed to apply WeChat endpoint: %s", exc)

            # Use streaming for frontend, regardless of WeChat binding
            try:
                streaming = websocket.app.state.config.llm.streaming_enabled
                full_response = ""
                if streaming:
                    try:
                        async for event in agent.stream(parsed.message):
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
                        full_response = await agent.run(parsed.message)
                        await websocket.send_json(
                            {"response": full_response, "conversation_id": cid}
                        )
                else:
                    full_response = await agent.run(parsed.message)
                    await websocket.send_json({"response": full_response, "conversation_id": cid})

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
                            last_wechat_user = getattr(wechat_channel, "_last_wechat_user_id", None)
                            last_context_token = getattr(wechat_channel, "_last_context_token", "")

                            if last_wechat_user:
                                await wechat_channel.send_message(
                                    last_wechat_user,
                                    full_response,
                                    context_token=last_context_token,
                                )
                                logger.info("Sent response to WeChat user %s", last_wechat_user)
                            else:
                                logger.warning("No WeChat user ID available to send response to")
                        except Exception as send_exc:
                            logger.warning("Failed to send response to WeChat: %s", send_exc)

            except Exception as exc:
                await websocket.send_json({"error": str(exc), "conversation_id": cid})

    except WebSocketDisconnect:
        pass
    finally:
        _chat_ws_clients.discard(websocket)
        logger.debug("WebSocket client disconnected (total: %d)", len(_chat_ws_clients))
