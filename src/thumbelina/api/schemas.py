"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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
    reasoning_content: str | None = None
    attachments: list[dict[str, object]] | None = None
    created_at: str


class ConversationSchema(BaseModel):
    """Schema for a conversation summary."""

    id: str
    name: str | None = None
    pinned: bool = False
    mode: str = "chat"
    workspace: str | None = None
    endpoint_id: str | None = None
    model: str | None = None
    knowledge_base_id: str | None = None
    role: str | None = None
    thinking_enabled: bool = False
    thinking_effort: str = "medium"
    created_at: str
    updated_at: str
    summary: str | None = None


class ConversationDetailSchema(BaseModel):
    """Schema for a conversation with messages."""

    id: str
    name: str | None = None
    pinned: bool = False
    mode: str = "chat"
    workspace: str | None = None
    endpoint_id: str | None = None
    model: str | None = None
    knowledge_base_id: str | None = None
    role: str | None = None
    thinking_enabled: bool = False
    thinking_effort: str = "medium"
    created_at: str
    updated_at: str
    summary: str | None = None
    messages: list[MessageSchema]


# 单轮允许携带的最大附件数(设计 §3.1,与上传端/前端约束一致)
MAX_WS_ATTACHMENTS = 4


class WebSocketMessage(BaseModel):
    """Schema for WebSocket incoming messages."""

    message: str = Field(default="", description="The user's message")
    conversation_id: str | None = Field(
        default=None,
        description="Optional conversation ID to resume an existing conversation",
    )
    attachments: list[dict[str, object]] | None = Field(
        default=None,
        description=(
            "Optional image attachment references ([{id, alt?}], max "
            f"{MAX_WS_ATTACHMENTS} per message)"
        ),
    )

    @model_validator(mode="after")
    def _require_text_or_attachments(self) -> WebSocketMessage:
        """message 文本与 attachments 至少其一非空(设计 §4.1 协议约束)。

        attachments 非空时:最多 ``MAX_WS_ATTACHMENTS`` 张,且每项必须是
        含非空字符串 ``id`` 键的 dict。
        """
        has_text = bool(self.message.strip())
        attachments = self.attachments or []
        if not has_text and not attachments:
            raise ValueError("message text and attachments cannot both be empty")
        if len(attachments) > MAX_WS_ATTACHMENTS:
            raise ValueError(f"At most {MAX_WS_ATTACHMENTS} attachments per message")
        for attachment in attachments:
            attachment_id = attachment.get("id")
            if not isinstance(attachment_id, str) or not attachment_id:
                raise ValueError("Each attachment must contain a non-empty string 'id'")
        return self


class WebSocketResponse(BaseModel):
    """Schema for WebSocket outgoing messages."""

    response: str = Field(..., description="The assistant's response")
    conversation_id: str | None = Field(
        default=None,
        description="The conversation ID for this WebSocket session",
    )
