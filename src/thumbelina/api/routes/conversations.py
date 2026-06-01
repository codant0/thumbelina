"""Conversation API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from thumbelina.api.deps import get_memory_manager
from thumbelina.api.schemas import ConversationDetailSchema, ConversationSchema, MessageSchema

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations() -> list[ConversationSchema]:
    """List all conversations.

    Returns
    -------
    list[ConversationSchema]
        List of conversation summaries.
    """
    memory = get_memory_manager()
    conversations = await memory.get_conversations()
    return [ConversationSchema(**c) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailSchema)
async def get_conversation(conversation_id: str) -> ConversationDetailSchema:
    """Get a conversation with its messages.

    Parameters
    ----------
    conversation_id:
        The ID of the conversation to retrieve.

    Returns
    -------
    ConversationDetailSchema
        The conversation details including messages.

    Raises
    ------
    HTTPException
        If the conversation is not found.
    """
    memory = get_memory_manager()
    conversation = await memory.get_conversation(conversation_id)

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await memory.get_messages(conversation_id)
    message_schemas = [MessageSchema(**m) for m in messages]

    return ConversationDetailSchema(
        id=conversation["id"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        messages=message_schemas,
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    """Delete a conversation.

    Parameters
    ----------
    conversation_id:
        The ID of the conversation to delete.

    Returns
    -------
    dict[str, bool]
        Confirmation of deletion.

    Raises
    ------
    HTTPException
        If the conversation is not found.
    """
    memory = get_memory_manager()
    deleted = await memory.delete_conversation(conversation_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"deleted": True}
