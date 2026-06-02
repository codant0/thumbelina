"""WebSocket handler for real-time chat."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.schemas import WebSocketMessage

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat.

    Accepts JSON messages with a ``message`` field and responds with
    a JSON object containing a ``response`` field.

    Each WebSocket connection gets its own isolated agent clone so that
    concurrent connections do not interfere with each other.
    """
    await websocket.accept()
    shared_agent: ThumbelinaAgent = websocket.app.state.agent

    # Clone the agent per connection to isolate conversation state
    agent = shared_agent.clone()

    # Create a default conversation for this WebSocket session
    default_conversation_id: str | None = (
        await agent.memory_manager.create_conversation()
        if agent.memory_manager
        else None
    )

    try:
        while True:
            data = await websocket.receive_json()

            # Validate incoming message via Pydantic schema
            try:
                parsed = WebSocketMessage.model_validate(data)
            except ValidationError:
                await websocket.send_json({"error": "Invalid message format"})
                continue

            if not parsed.message.strip():
                await websocket.send_json({"error": "Empty message"})
                continue

            # Use client-supplied conversation_id, or fall back to default
            cid = parsed.conversation_id or default_conversation_id
            if cid:
                agent.current_conversation_id = cid

            response_text = await agent.run(parsed.message)
            await websocket.send_json({
                "response": response_text,
                "conversation_id": cid,
            })

    except WebSocketDisconnect:
        pass
