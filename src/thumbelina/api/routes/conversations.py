"""Conversation API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from thumbelina.api.deps import get_memory_manager
from thumbelina.api.schemas import ConversationDetailSchema, ConversationSchema, MessageSchema
from thumbelina.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conversations"])


class CreateConversationRequest(BaseModel):
    """Request body for creating a new conversation."""

    name: str | None = Field(default=None, description="Optional conversation name")
    pinned: bool = Field(default=False, description="Whether to pin the conversation")


@router.post("/conversations", response_model=ConversationSchema)
async def create_conversation(
    body: CreateConversationRequest | None = None,
    memory: MemoryManager = Depends(get_memory_manager),
) -> ConversationSchema:
    """Create a new conversation."""
    name = body.name if body else None
    pinned = body.pinned if body else False
    conv_id = await memory.create_conversation(name=name, pinned=pinned)
    conv = await memory.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=500, detail="Failed to create conversation")
    return ConversationSchema(**conv)


@router.get("/conversations/search/{query}")
async def search_conversations(
    query: str,
    memory: MemoryManager = Depends(get_memory_manager),
) -> list[dict]:
    """Search messages across all conversations.

    Uses hybrid keyword + semantic search when a vector store
    is configured, falling back to keyword-only search otherwise.
    """
    return await memory.search(query)


@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations(
    memory: MemoryManager = Depends(get_memory_manager),
) -> list[ConversationSchema]:
    """List all conversations."""
    try:
        conversations = await memory.get_conversations()
        logger.debug("Fetched %d conversations", len(conversations))
        return [ConversationSchema(**c) for c in conversations]
    except Exception:
        logger.exception("Failed to list conversations")
        return []


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
        name=conversation.get("name"),
        pinned=conversation.get("pinned", False),
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
