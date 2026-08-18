"""Data export, deletion, and feedback API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from thumbelina.api.deps import (
    get_feedback_repo,
    get_memory_service,
    get_repository_manager,
)
from thumbelina.api.routes.conversations import _clear_checkpoint
from thumbelina.concurrency import per_conversation_lock
from thumbelina.memory.service import MemoryService
from thumbelina.repository.feedback_repo import Feedback, FeedbackRepository
from thumbelina.repository.manager import RepositoryManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data"])


# -- Feedback request/response models --


class FeedbackCreateRequest(BaseModel):
    """Request body for submitting feedback."""

    conversation_id: str = Field(..., min_length=1)
    message_index: int = Field(..., ge=0)
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None
    skill_id: str | None = None


class FeedbackResponse(BaseModel):
    """Serialized feedback record."""

    id: str
    conversation_id: str
    message_index: int
    rating: int
    comment: str | None
    skill_id: str | None
    created_at: str


def _feedback_to_response(fb: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=fb.id,
        conversation_id=fb.conversation_id,
        message_index=fb.message_index,
        rating=fb.rating,
        comment=fb.comment,
        skill_id=fb.skill_id,
        created_at=(
            fb.created_at.isoformat() if hasattr(fb.created_at, "isoformat") else str(fb.created_at)
        ),
    )


@router.get("/data/export")
async def export_data(
    repository: RepositoryManager = Depends(get_repository_manager),
    memory_service: MemoryService | None = Depends(get_memory_service),
) -> dict:
    """Export all user data as JSON.

    纳入 Markdown 分层记忆(§9.5):memory_service 可用时返回
    ``{"entries": [...], "index": ...}``,否则空占位。
    """
    conversations = await repository.get_all_conversations_with_messages()
    if memory_service is not None:
        try:
            memory_data = await memory_service.export_all()
        except Exception:
            memory_data = {"entries": [], "index": ""}
    else:
        memory_data = {"entries": [], "index": ""}
    return {"conversations": conversations, "memory": memory_data}


@router.delete("/data/all")
async def delete_all_data(
    request: Request,
    confirm: bool = False,
    repository: RepositoryManager = Depends(get_repository_manager),
    memory_service: MemoryService | None = Depends(get_memory_service),
) -> dict:
    """Delete all user data.

    Requires ``?confirm=true`` query parameter to prevent accidental deletion.
    删完对话后顺带清空 Markdown 记忆(§9.5)。
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm deletion of all data.",
        )
    conversations = await repository.get_conversations()
    for conv in conversations:
        cid = conv["id"]
        # 与单条删除路由一致：同时清除 LangGraph 检查点线程，避免线程
        # 无界增长，也避免以相同 id 重建的会话复活旧上下文。持同一把
        # per-conversation 锁，防止在途轮次的最终写入复活线程。
        async with per_conversation_lock(cid):
            await repository.delete_conversation(cid)
            await _clear_checkpoint(request, cid)
    deleted_memory = 0
    if memory_service is not None:
        try:
            # clear_all 重建空 index.md;返回前统计被删条目数便于回执。
            before = await memory_service.list_entries()
            deleted_memory = len(before)
            await memory_service.clear_all()
        except Exception:
            # 记忆清理失败不阻断主删除流程,仅记日志
            logger.warning("Memory clear_all during data wipe failed", exc_info=True)
    return {"deleted": len(conversations), "memory_deleted": deleted_memory}


# -- Feedback endpoints --


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackCreateRequest,
    repo: FeedbackRepository | None = Depends(get_feedback_repo),
) -> FeedbackResponse:
    """Submit feedback for a conversation message or skill."""
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail="Feedback system is not configured",
        )
    feedback = Feedback(
        conversation_id=body.conversation_id,
        message_index=body.message_index,
        rating=body.rating,
        comment=body.comment,
        skill_id=body.skill_id,
    )
    saved = await repo.save(feedback)
    return _feedback_to_response(saved)


@router.get("/feedback")
async def list_feedback(
    conversation_id: str | None = None,
    skill_id: str | None = None,
    repo: FeedbackRepository | None = Depends(get_feedback_repo),
) -> list[FeedbackResponse]:
    """List feedback with optional filters."""
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail="Feedback system is not configured",
        )
    if conversation_id:
        items = await repo.list_by_conversation(conversation_id)
    elif skill_id:
        items = await repo.list_by_skill(skill_id)
    else:
        items = await repo.list_all()
    return [_feedback_to_response(fb) for fb in items]


@router.get("/feedback/stats")
async def feedback_stats(
    skill_id: str | None = None,
    repo: FeedbackRepository | None = Depends(get_feedback_repo),
) -> dict:
    """Get average rating statistics, optionally filtered by skill."""
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail="Feedback system is not configured",
        )
    return await repo.get_average_rating(skill_id=skill_id)
