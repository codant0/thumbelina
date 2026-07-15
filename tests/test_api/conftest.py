"""Shared fixtures for API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig


@pytest.fixture
def mock_agent():
    """Create a mock ThumbelinaAgent."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")

    async def _stream(*args, **kwargs):
        yield "Agent response"

    agent.stream = _stream
    agent.current_conversation_id = None
    agent.memory_manager = None
    # clone() returns a new mock (memory_manager=None is safe for clone)
    agent.clone.return_value = agent
    return agent


@pytest.fixture
def mock_memory():
    """Create a mock MemoryManager."""
    conv = {
        "id": "test-conv-id",
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
        "summary": None,
    }
    conversations = {"test-conv-id": conv}
    messages = [
        {
            "id": "msg-1",
            "conversation_id": "test-conv-id",
            "role": "user",
            "content": "Hello",
            "created_at": "2026-01-01",
        },
    ]

    async def get_conversation(conv_id: str):
        return conversations.get(conv_id)

    async def get_messages(conv_id: str):
        if conv_id in conversations:
            return messages
        return []

    async def delete_conversation(conv_id: str):
        if conv_id in conversations:
            del conversations[conv_id]
            return True
        return False

    async def rename_conversation(conv_id: str, name: str) -> bool:
        if conv_id in conversations:
            conversations[conv_id]["name"] = name or None
            return True
        return False

    async def set_conversation_endpoint(conv_id: str, endpoint_id) -> bool:
        if conv_id in conversations:
            conversations[conv_id]["endpoint_id"] = endpoint_id
            return True
        return False

    memory = MagicMock()
    memory.create_conversation = AsyncMock(return_value="test-conv-id")
    memory.get_conversation = AsyncMock(side_effect=get_conversation)
    memory.get_conversations = AsyncMock(return_value=[conv])
    memory.get_messages = AsyncMock(side_effect=get_messages)
    memory.delete_conversation = AsyncMock(side_effect=delete_conversation)
    memory.add_message = AsyncMock()
    memory.close = MagicMock()

    # Per-conversation rename / endpoint selection (mutate in-memory dict)
    memory.rename_conversation = AsyncMock(side_effect=rename_conversation)
    memory.set_conversation_endpoint = AsyncMock(side_effect=set_conversation_endpoint)

    # Mock repository with ping method
    memory.repository = MagicMock()
    memory.repository.ping = AsyncMock(return_value=True)

    return memory


@pytest.fixture
def client(mock_agent, mock_memory):
    """Create a test client with mocked dependencies."""
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )

    with (
        patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
    ):
        from thumbelina.api.app import create_app

        app = create_app(config)
        with TestClient(app) as client:
            yield client
