"""Dependency injection for the Thumbelina API."""

from __future__ import annotations

from fastapi import HTTPException, Request

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.channels.qq_channel import QQChannel
from thumbelina.channels.wechat_channel import WeChatChannel
from thumbelina.memory.feedback_repo import FeedbackRepository
from thumbelina.memory.manager import MemoryManager
from thumbelina.memory.profiler import UserProfiler


def get_memory_manager(request: Request) -> MemoryManager:
    """Get the MemoryManager from app.state."""
    return request.app.state.memory_manager


def get_agent(request: Request) -> ThumbelinaAgent:
    """Get the ThumbelinaAgent from app.state."""
    return request.app.state.agent


def get_user_profiler(request: Request) -> UserProfiler | None:
    """Get the UserProfiler from app.state, if available."""
    return getattr(request.app.state, "user_profiler", None)


def get_feedback_repo(request: Request) -> FeedbackRepository | None:
    """Get the FeedbackRepository from app.state, if available."""
    return getattr(request.app.state, "feedback_repo", None)


def get_wechat_channel(request: Request) -> WeChatChannel:
    """Get the WeChatChannel from app.state.

    Raises 404 if the WeChat channel is not initialized.
    """
    channel = getattr(request.app.state, "wechat_channel", None)
    if channel is None:
        raise HTTPException(
            status_code=404,
            detail="WeChat channel is not enabled or not initialized",
        )
    return channel


def get_qq_channel(request: Request) -> QQChannel:
    """Get the QQChannel from app.state.

    Raises 404 if the QQ channel is not initialized.
    """
    channel = getattr(request.app.state, "qq_channel", None)
    if channel is None:
        raise HTTPException(
            status_code=404,
            detail="QQ channel is not enabled or not initialized",
        )
    return channel
