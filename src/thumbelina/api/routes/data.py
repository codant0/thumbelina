"""Data export, deletion, and feedback API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from thumbelina.api.deps import get_feedback_repo, get_memory_manager, get_user_profiler
from thumbelina.memory.feedback_repo import Feedback, FeedbackRepository
from thumbelina.memory.manager import MemoryManager
from thumbelina.memory.profiler import UserProfiler

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
    memory: MemoryManager = Depends(get_memory_manager),
) -> dict:
    """Export all user data as JSON."""
    conversations = await memory.get_all_conversations_with_messages()
    return {"conversations": conversations}


@router.delete("/data/all")
async def delete_all_data(
    confirm: bool = False,
    memory: MemoryManager = Depends(get_memory_manager),
) -> dict:
    """Delete all user data.

    Requires ``?confirm=true`` query parameter to prevent accidental deletion.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm deletion of all data.",
        )
    conversations = await memory.get_conversations()
    for conv in conversations:
        await memory.delete_conversation(conv["id"])
    return {"deleted": len(conversations)}


@router.get("/user/profile")
async def get_user_profile(
    user_id: str = "default",
    profiler: UserProfiler | None = Depends(get_user_profiler),
) -> dict:
    """Get user profile and preferences."""
    if profiler is None:
        raise HTTPException(
            status_code=503,
            detail="User profiler is not configured",
        )

    profile = await profiler.profile_repo.get_profile(user_id)
    if profile is None:
        # Return a default empty profile rather than 404
        return {
            "profile": None,
            "preferences": [],
            "context": None,
        }

    preferences = await profiler.profile_repo.get_preferences(user_id)
    context = await profiler.get_user_context(user_id)

    return {
        "profile": profile,
        "preferences": preferences,
        "context": context,
    }


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
