"""Dependency injection for the Thumbelina API."""

from __future__ import annotations

from fastapi import HTTPException, Request

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.channels.qq_channel import QQChannel
from thumbelina.channels.wechat_channel import WeChatChannel
from thumbelina.memory.extractor import MemoryExtractor
from thumbelina.memory.service import MemoryService
from thumbelina.repository.feedback_repo import FeedbackRepository
from thumbelina.repository.manager import RepositoryManager
from thumbelina.todo.service import TodoService


def get_repository_manager(request: Request) -> RepositoryManager:
    """Get the RepositoryManager from app.state."""
    return request.app.state.repository_manager


def get_agent(request: Request) -> ThumbelinaAgent:
    """Get the ThumbelinaAgent from app.state."""
    return request.app.state.agent


def get_memory_service(request: Request) -> MemoryService | None:
    """Get the MemoryService from app.state, if available.

    返回 ``None`` 时路由层负责降级为 503;``GET /memory/status`` 例外,
    始终返回 200 以便前端展示"模块未启用"状态。
    """
    return getattr(request.app.state, "memory_service", None)


def get_memory_extractor(request: Request) -> MemoryExtractor | None:
    """Get the MemoryExtractor from app.state, if available.

    供需要重定向 LLM 的热切换路径使用(见 §9.3);agent 自身的
    ``memory_extractor`` 引用由 ``swap_provider`` 同步。
    """
    return getattr(request.app.state, "memory_extractor", None)


def get_feedback_repo(request: Request) -> FeedbackRepository | None:
    """Get the FeedbackRepository from app.state, if available."""
    return getattr(request.app.state, "feedback_repo", None)


def get_todo_service(request: Request) -> TodoService:
    """Get the TodoService from app.state, or 503 if unavailable."""
    service: TodoService | None = getattr(request.app.state, "todo_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="TODO module is not available")
    return service


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
