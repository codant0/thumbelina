"""WebSocket handler for real-time chat."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from thumbelina.api.deps import get_memory_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat.

    Accepts JSON messages with a ``message`` field and responds with
    a JSON object containing a ``response`` field.

    Parameters
    ----------
    websocket:
        The WebSocket connection.
    """
    await websocket.accept()
    memory = get_memory_manager()

    # Create a conversation for this WebSocket session
    conversation_id = await memory.create_conversation()

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            message = data.get("message", "")

            if not message:
                await websocket.send_json({"error": "Empty message"})
                continue

            # Persist user message
            await memory.add_message(
                conversation_id=conversation_id,
                role="user",
                content=message,
            )

            # Generate response (simple echo for now; agent integration later)
            response_text = f"Received: {message}"

            # Persist assistant message
            await memory.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=response_text,
            )

            # Send response to client
            await websocket.send_json({"response": response_text})

    except WebSocketDisconnect:
        # Client disconnected; nothing to clean up
        pass
