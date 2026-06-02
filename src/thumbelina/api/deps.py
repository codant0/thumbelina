"""Dependency injection for the Thumbelina API."""

from __future__ import annotations

from fastapi import Request

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.memory.manager import MemoryManager


def get_memory_manager(request: Request) -> MemoryManager:
    """Get the MemoryManager from app.state."""
    return request.app.state.memory_manager


def get_agent(request: Request) -> ThumbelinaAgent:
    """Get the ThumbelinaAgent from app.state."""
    return request.app.state.agent
