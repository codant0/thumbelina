"""Conversation API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from thumbelina.api.deps import get_memory_manager
from thumbelina.api.schemas import ConversationDetailSchema, ConversationSchema, MessageSchema
from thumbelina.memory.manager import MemoryManager

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations(
    memory: MemoryManager = Depends(get_memory_manager),
) -> list[ConversationSchema]:
    """List all conversations."""
    conversations = await memory.get_conversations()
    return [ConversationSchema(**c) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailSchema)
async def get_conversation(
    conversation_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
) -> ConversationDetailSchema:
    """Get a conversation with its messages."""
    conversation = await memory.get_conversation(conversation_id)

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await memory.get_messages(conversation_id)
    message_schemas = [MessageSchema(**m) for m in messages]

    return ConversationDetailSchema(
        id=conversation["id"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        summary=conversation.get("summary"),
        messages=message_schemas,
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
) -> dict[str, bool]:
    """Delete a conversation."""
    deleted = await memory.delete_conversation(conversation_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"deleted": True}
