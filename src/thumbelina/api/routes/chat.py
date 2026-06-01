"""Chat API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from thumbelina.api.deps import get_memory_manager
from thumbelina.api.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message and get a response.

    Creates a new conversation if no conversation_id is provided.

    Parameters
    ----------
    request:
        The chat request containing the user's message.

    Returns
    -------
    ChatResponse
        The assistant's response and conversation ID.
    """
    memory = get_memory_manager()

    # Create or reuse conversation
    conversation_id = request.conversation_id
    if conversation_id is None:
        conversation_id = await memory.create_conversation()
    else:
        # Verify conversation exists
        existing = await memory.get_conversation(conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Persist user message
    await memory.add_message(
        conversation_id=conversation_id,
        role="user",
        content=request.message,
    )

    # Generate a simple echo response (agent integration can be added later)
    response_text = f"Received: {request.message}"

    # Persist assistant message
    await memory.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content=response_text,
    )

    return ChatResponse(response=response_text, conversation_id=conversation_id)
