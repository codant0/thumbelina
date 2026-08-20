"""Conversation API routes."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from thumbelina.api.deps import get_agent, get_repository_manager
from thumbelina.api.schemas import ConversationDetailSchema, ConversationSchema, MessageSchema
from thumbelina.concurrency import per_conversation_lock
from thumbelina.prompts.roles import list_roles
from thumbelina.repository.manager import RepositoryManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conversations"])


async def _clear_checkpoint(request: Request, conversation_id: str) -> None:
    """丢弃会话的检查点工作区（生命周期联动）。

    删除会话或清空其消息会清空消息日志，因此持久化的 LangGraph
    上下文（``thread_id == conversation_id``）必须一并清除 —— 否则以
    相同 id 重新创建会话会从检查点中复活过期的上下文。

    缺少 saver（降级模式：非 sqlite 数据库或缺少包）是安全的空操作；
    删除失败只记录警告，绝不会破坏主要的 repository 操作。
    """
    saver = getattr(request.app.state, "checkpointer", None)
    if saver is None:
        return
    try:
        await saver.adelete_thread(conversation_id)
    except Exception:
        logger.warning(
            "Failed to clear checkpoint for conversation %s", conversation_id, exc_info=True
        )


class CreateConversationRequest(BaseModel):
    """Request body for creating a new conversation."""

    name: str | None = Field(default=None, description="Optional conversation name")
    pinned: bool = Field(default=False, description="Whether to pin the conversation")


class RenameConversationRequest(BaseModel):
    """Request body for renaming a conversation."""

    name: str = Field(..., description="New conversation name")


class SetConversationEndpointRequest(BaseModel):
    """Request body for per-conversation model selection."""

    endpoint_id: str | None = Field(
        default=None,
        description="ID of a configured LLM endpoint, or null to use the default model",
    )
    model: str | None = Field(
        default=None,
        description=(
            "Specific model within the endpoint's models,"
            " or null to use the endpoint's active model"
        ),
    )


class SetConversationKnowledgeBaseRequest(BaseModel):
    """Request body for binding a knowledge base to a conversation."""

    knowledge_base_id: str | None = Field(
        default=None,
        description="ID of the RAG knowledge base, or null to unbind",
    )


class SetConversationRoleRequest(BaseModel):
    """Request body for setting the agent role of a conversation."""

    role: str | None = Field(
        default=None,
        description="Role name matching a prompts/roles/<role>.md file, or null for the default",
    )


class SetConversationThinkingRequest(BaseModel):
    """Request body for per-conversation thinking-mode settings."""

    enabled: bool = Field(default=False, description="Whether thinking mode is enabled")
    effort: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Thinking intensity level",
    )


class CompressConversationRequest(BaseModel):
    """Request body for manually compressing a conversation's context."""

    context_window_tokens: int | None = Field(
        default=None,
        description=(
            "Optional context window (tokens) to compress down to; when omitted the "
            "conversation's resolved window (endpoint → active → llm.context_window) is used"
        ),
    )


@router.post("/conversations", response_model=ConversationSchema)
async def create_conversation(
    body: CreateConversationRequest | None = None,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Create a new conversation."""
    name = body.name if body else None
    pinned = body.pinned if body else False
    conv_id = await repository.create_conversation(name=name, pinned=pinned)
    conv = await repository.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=500, detail="Failed to create conversation")
    return ConversationSchema(**conv)


@router.get("/conversations/search/{query}")
async def search_conversations(
    query: str,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> list[dict]:
    """Search messages across all conversations.

    Uses hybrid keyword + semantic search when a vector store
    is configured, falling back to keyword-only search otherwise.
    """
    return await repository.search(query)


@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations(
    repository: RepositoryManager = Depends(get_repository_manager),
) -> list[ConversationSchema]:
    """List all conversations."""
    try:
        conversations = await repository.get_conversations()
        logger.debug("Fetched %d conversations", len(conversations))
        return [ConversationSchema(**c) for c in conversations]
    except Exception:
        logger.exception("Failed to list conversations")
        return []


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailSchema)
async def get_conversation(
    conversation_id: str,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationDetailSchema:
    """Get a conversation with its messages."""
    conversation = await repository.get_conversation(conversation_id)

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await repository.get_messages(conversation_id)
    message_schemas = [MessageSchema(**m) for m in messages]

    return ConversationDetailSchema(
        id=conversation["id"],
        name=conversation.get("name"),
        pinned=conversation.get("pinned", False),
        endpoint_id=conversation.get("endpoint_id"),
        model=conversation.get("model"),
        knowledge_base_id=conversation.get("knowledge_base_id"),
        role=conversation.get("role"),
        thinking_enabled=conversation.get("thinking_enabled", False),
        thinking_effort=conversation.get("thinking_effort", "medium"),
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        summary=conversation.get("summary"),
        messages=message_schemas,
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationSchema)
async def rename_conversation(
    conversation_id: str,
    body: RenameConversationRequest,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Rename a conversation.

    The name is stripped of surrounding whitespace. An empty name clears the
    conversation's custom title so it can be auto-named again.
    """
    name = body.name.strip()
    ok = await repository.rename_conversation(conversation_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSchema(**conv)


@router.put(
    "/conversations/{conversation_id}/endpoint",
    response_model=ConversationSchema,
)
async def set_conversation_endpoint(
    conversation_id: str,
    body: SetConversationEndpointRequest,
    request: Request,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Set the LLM endpoint (model) used for a conversation.

    ``endpoint_id`` must reference an endpoint saved in Settings, or be
    ``null`` to revert the conversation to the default model.
    """
    if body.endpoint_id is not None:
        endpoint_manager = getattr(request.app.state, "endpoint_manager", None)
        if endpoint_manager is None:
            raise HTTPException(status_code=503, detail="Endpoint manager not available")
        endpoint = await endpoint_manager.get_endpoint(body.endpoint_id)
        if endpoint is None:
            raise HTTPException(status_code=404, detail="Endpoint not found")
        if body.model is not None and body.model not in endpoint.models:
            raise HTTPException(
                status_code=422,
                detail=f"Model '{body.model}' is not configured on this endpoint",
            )

    ok = await repository.set_conversation_endpoint(conversation_id, body.endpoint_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Persist the per-conversation model. When clearing the endpoint, also
    # clear the model so a stale name doesn't linger.
    await repository.set_conversation_model(
        conversation_id, body.model if body.endpoint_id else None
    )
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSchema(**conv)


@router.put(
    "/conversations/{conversation_id}/knowledge-base",
    response_model=ConversationSchema,
)
async def set_conversation_knowledge_base(
    conversation_id: str,
    body: SetConversationKnowledgeBaseRequest,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Bind (or unbind) a RAG knowledge base to a conversation.

    ``knowledge_base_id`` must reference an existing knowledge base, or be
    ``null`` to unbind the conversation from any knowledge base.
    """
    ok = await repository.set_conversation_knowledge_base(conversation_id, body.knowledge_base_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSchema(**conv)


@router.put(
    "/conversations/{conversation_id}/role",
    response_model=ConversationSchema,
)
async def set_conversation_role(
    conversation_id: str,
    body: SetConversationRoleRequest,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Set the agent persona role used for a conversation.

    ``role`` must match a ``prompts/roles/<role>.md`` file, or be ``null``
    to revert the conversation to the global default role.
    """
    if body.role is not None and body.role not in list_roles():
        raise HTTPException(status_code=422, detail=f"Unknown role: '{body.role}'")
    ok = await repository.set_conversation_role(conversation_id, body.role)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSchema(**conv)


@router.put(
    "/conversations/{conversation_id}/thinking",
    response_model=ConversationSchema,
)
async def set_conversation_thinking(
    conversation_id: str,
    body: SetConversationThinkingRequest,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Set thinking-mode (on/off + intensity) for a conversation."""
    ok = await repository.set_conversation_thinking(conversation_id, body.enabled, body.effort)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSchema(**conv)


@router.post("/conversations/{conversation_id}/compress")
async def compress_conversation(
    conversation_id: str,
    request: Request,
    body: CompressConversationRequest | None = None,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, Any]:
    """手动压缩指定会话的 LangGraph 检查点历史。

    无条件调用压缩器（不等阈值），并把压缩后的序列经 ``add_messages``
    更新写回检查点。会话可能被 HTTP ``/chat`` 或 WebSocket 并发访问，
    因此持同一把 per-conversation 锁串行化，避免与在途轮次交错。
    """
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    agent = get_agent(request)
    window_tokens = body.context_window_tokens if body is not None else None

    async with per_conversation_lock(conversation_id):
        return await agent.compress_conversation(
            conversation_id, context_window_tokens=window_tokens
        )


@router.delete("/conversations/{conversation_id}/messages")
async def clear_conversation_messages(
    conversation_id: str,
    request: Request,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, bool]:
    """Clear all messages of a conversation, keeping the conversation itself.

    Used by the frontend "clear context" action.
    """
    # 持同一把 per-conversation 锁：避免清空消息时与在途轮次交错，
    # 也避免 in-flight 轮次的最终写入复活即将被清除的检查点。
    async with per_conversation_lock(conversation_id):
        cleared = await repository.clear_messages(conversation_id)

        if not cleared:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # LangGraph 检查点保存着与 LLM 上下文相同的历史；丢弃它，
        # 让清空后的会话以全新的上下文工作区重新开始。
        await _clear_checkpoint(request, conversation_id)

    return {"cleared": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, bool]:
    """Delete a conversation."""
    # 持同一把 per-conversation 锁：避免与在途轮次交错，防止轮次的
    # 最终写入复活即将被删除的检查点线程。
    async with per_conversation_lock(conversation_id):
        deleted = await repository.delete_conversation(conversation_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 移除会话的检查点线程，避免以相同 id 重新创建的会话
        # 复活旧上下文。
        await _clear_checkpoint(request, conversation_id)

    return {"deleted": True}
