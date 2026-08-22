"""Shared fixtures for API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig


@pytest.fixture
def mock_agent():
    """Create a mock ThumbelinaAgent."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")

    async def _stream(*args, **kwargs):
        yield {"type": "content", "text": "Agent response"}

    agent.stream = _stream
    agent.current_conversation_id = None
    agent.repository_manager = None
    # clone() returns a new mock (repository_manager=None is safe for clone)
    agent.clone.return_value = agent
    return agent


@pytest.fixture
def mock_repository():
    """Create a mock RepositoryManager."""
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

    async def set_conversation_model(conv_id: str, model) -> bool:
        if conv_id in conversations:
            conversations[conv_id]["model"] = model
            return True
        return False

    async def set_conversation_knowledge_base(conv_id: str, knowledge_base_id) -> bool:
        if conv_id in conversations:
            conversations[conv_id]["knowledge_base_id"] = knowledge_base_id
            return True
        return False

    async def set_conversation_role(conv_id: str, role) -> bool:
        if conv_id in conversations:
            conversations[conv_id]["role"] = role
            return True
        return False

    async def set_conversation_thinking(conv_id: str, enabled: bool, effort: str) -> bool:
        if conv_id in conversations:
            conversations[conv_id]["thinking_enabled"] = enabled
            conversations[conv_id]["thinking_effort"] = effort
            return True
        return False

    async def clear_messages(conv_id: str) -> bool:
        if conv_id in conversations:
            messages.clear()
            conversations[conv_id]["summary"] = None
            return True
        return False

    async def create_conversation(
        name=None, pinned=False, mode="chat", workspace=None, role=None
    ):
        """Record a new conversation; ids increment per fixture instance."""
        conv_id = f"test-conv-id-{len(conversations) + 1}"
        conversations[conv_id] = {
            "id": conv_id,
            "name": name,
            "pinned": pinned,
            "mode": mode,
            "workspace": workspace,
            "role": role,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
            "summary": None,
        }
        return conv_id

    async def get_conversations(mode=None):
        convs = list(conversations.values())
        if mode is not None:
            convs = [c for c in convs if c.get("mode", "chat") == mode]
        return convs

    repository = MagicMock()
    repository.create_conversation = AsyncMock(side_effect=create_conversation)
    repository.get_conversation = AsyncMock(side_effect=get_conversation)
    repository.get_conversations = AsyncMock(side_effect=get_conversations)
    repository.get_messages = AsyncMock(side_effect=get_messages)
    repository.delete_conversation = AsyncMock(side_effect=delete_conversation)
    repository.clear_messages = AsyncMock(side_effect=clear_messages)
    repository.add_message = AsyncMock()
    repository.close = MagicMock()

    # Per-conversation rename / endpoint selection (mutate in-memory dict)
    repository.rename_conversation = AsyncMock(side_effect=rename_conversation)
    repository.set_conversation_endpoint = AsyncMock(side_effect=set_conversation_endpoint)
    repository.set_conversation_model = AsyncMock(side_effect=set_conversation_model)
    repository.set_conversation_knowledge_base = AsyncMock(
        side_effect=set_conversation_knowledge_base
    )
    repository.set_conversation_role = AsyncMock(side_effect=set_conversation_role)
    repository.set_conversation_thinking = AsyncMock(side_effect=set_conversation_thinking)

    # Mock repository with ping method
    repository.conversation_repository = MagicMock()
    repository.conversation_repository.ping = AsyncMock(return_value=True)

    return repository


@pytest.fixture
def client(mock_agent, mock_repository):
    """Create a test client with mocked dependencies."""
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
    )

    with (
        patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
    ):
        from thumbelina.api.app import create_app

        app = create_app(config)
        with TestClient(app) as client:
            yield client
