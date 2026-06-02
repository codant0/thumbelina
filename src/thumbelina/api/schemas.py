"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    message: str = Field(..., min_length=1, description="The user's message")
    conversation_id: str | None = Field(
        default=None, description="Optional conversation ID to continue an existing conversation"
    )


class ChatResponse(BaseModel):
    """Response body for the chat endpoint."""

    response: str = Field(..., description="The assistant's response")
    conversation_id: str = Field(..., description="The conversation ID")


class MessageSchema(BaseModel):
    """Schema for a single message."""

    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class ConversationSchema(BaseModel):
    """Schema for a conversation summary."""

    id: str
    created_at: str
    updated_at: str
    summary: str | None = None


class ConversationDetailSchema(BaseModel):
    """Schema for a conversation with messages."""

    id: str
    created_at: str
    updated_at: str
    summary: str | None = None
    messages: list[MessageSchema]


class WebSocketMessage(BaseModel):
    """Schema for WebSocket incoming messages."""

    message: str = Field(..., min_length=1, description="The user's message")
    conversation_id: str | None = Field(
        default=None,
        description="Optional conversation ID to resume an existing conversation",
    )


class WebSocketResponse(BaseModel):
    """Schema for WebSocket outgoing messages."""

    response: str = Field(..., description="The assistant's response")
    conversation_id: str | None = Field(
        default=None,
        description="The conversation ID for this WebSocket session",
    )
