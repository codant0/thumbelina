"""Chat API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.deps import get_agent, get_memory_manager
from thumbelina.api.schemas import ChatRequest, ChatResponse
from thumbelina.memory.manager import MemoryManager

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent: ThumbelinaAgent = Depends(get_agent),
    memory: MemoryManager = Depends(get_memory_manager),
) -> ChatResponse:
    """Send a message and get a response.

    Creates a new conversation if no conversation_id is provided.
    """
    # Create or reuse conversation
    conversation_id = request.conversation_id
    if conversation_id is None:
        conversation_id = await memory.create_conversation()
    else:
        existing = await memory.get_conversation(conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Set the agent's conversation and let it handle persistence
    agent.current_conversation_id = conversation_id
    response_text = await agent.run(request.message)

    return ChatResponse(response=response_text, conversation_id=conversation_id)
