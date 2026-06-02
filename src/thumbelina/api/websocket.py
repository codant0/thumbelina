"""WebSocket handler for real-time chat."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.memory.manager import MemoryManager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat.

    Accepts JSON messages with a ``message`` field and responds with
    a JSON object containing a ``response`` field.
    """
    await websocket.accept()
    memory: MemoryManager = websocket.app.state.memory_manager
    agent: ThumbelinaAgent = websocket.app.state.agent

    # Create a conversation for this WebSocket session
    conversation_id = await memory.create_conversation()
    agent.current_conversation_id = conversation_id

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")

            if not message:
                await websocket.send_json({"error": "Empty message"})
                continue

            response_text = await agent.run(message)
            await websocket.send_json({"response": response_text})

    except WebSocketDisconnect:
        pass
