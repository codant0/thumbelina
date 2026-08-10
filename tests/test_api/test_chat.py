"""Tests for thumbelina.api.routes.chat module."""

from __future__ import annotations

import pytest


def test_chat_endpoint_exists(client):
    """POST /api/v1/chat should exist."""
    response = client.post("/api/v1/chat", json={"message": "hello"})
    # Should not be 404
    assert response.status_code != 404


def test_chat_requires_message_field(client):
    """POST /api/v1/chat should require a message field."""
    response = client.post("/api/v1/chat", json={})
    assert response.status_code == 422


def test_chat_accepts_message(client):
    """POST /api/v1/chat should accept a message and return a response."""
    response = client.post("/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "conversation_id" in data


def test_chat_response_structure(client):
    """POST /api/v1/chat response should have the correct structure."""
    response = client.post("/api/v1/chat", json={"message": "Hello"})
    data = response.json()
    assert isinstance(data["response"], str)
    assert isinstance(data["conversation_id"], str)


def test_chat_with_conversation_id(client):
    """POST /api/v1/chat should accept an optional conversation_id."""
    # First create a conversation
    create_response = client.post("/api/v1/chat", json={"message": "Hello"})
    conversation_id = create_response.json()["conversation_id"]

    # Then continue the conversation
    response = client.post(
        "/api/v1/chat",
        json={"message": "Follow up", "conversation_id": conversation_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == conversation_id


def test_chat_empty_message_rejected(client):
    """POST /api/v1/chat should reject empty messages."""
    response = client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422


def test_thinking_kwargs_openai():
    """OpenAI thinking injection uses reasoning_effort."""
    from thumbelina.api.routes.chat import _thinking_kwargs

    assert _thinking_kwargs("openai", True, "high") == {"reasoning_effort": "high"}
    assert _thinking_kwargs("openai", False, "high") == {}


def test_thinking_kwargs_anthropic():
    """Anthropic thinking injection uses budget_tokens and max_tokens."""
    from thumbelina.api.routes.chat import _thinking_kwargs

    kwargs = _thinking_kwargs("anthropic", True, "low")
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert kwargs["max_tokens"] == 3072


def test_thinking_kwargs_unknown_provider():
    """Providers without thinking support get no extra kwargs."""
    from thumbelina.api.routes.chat import _thinking_kwargs

    assert _thinking_kwargs("ollama", True, "high") == {}


@pytest.mark.asyncio
async def test_apply_endpoint_default_provider_gets_thinking():
    """With no active endpoint, the default provider is rebuilt with thinking kwargs."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from thumbelina.api.routes.chat import _apply_conversation_endpoint

    agent = MagicMock()
    agent.memory_manager = MagicMock()
    agent.memory_manager.get_conversation = AsyncMock(
        return_value={"id": "c1", "thinking_enabled": True, "thinking_effort": "high"}
    )

    endpoint_manager = MagicMock()
    endpoint_manager.get_active_endpoint_model = AsyncMock(return_value=None)

    config = MagicMock()
    config.llm.provider = "openai"
    config.llm.model = "deepseek-chat"
    config.llm.api_key = "sk-test"
    config.llm.base_url = "https://api.deepseek.com/v1"

    request = MagicMock()
    request.app.state.endpoint_manager = endpoint_manager
    request.app.state.config = config

    provider = MagicMock()
    with patch(
        "thumbelina.api.routes.chat.create_provider", return_value=provider
    ) as mock_create:
        await _apply_conversation_endpoint(request, agent, "c1")

    mock_create.assert_called_once_with(
        "openai",
        model="deepseek-chat",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        reasoning_effort="high",
    )
    assert agent.llm is provider.chat_model


@pytest.mark.asyncio
async def test_apply_endpoint_default_provider_no_thinking():
    """Without thinking enabled, the default provider path resets llm to None."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from thumbelina.api.routes.chat import _apply_conversation_endpoint

    agent = MagicMock()
    agent.memory_manager = MagicMock()
    agent.memory_manager.get_conversation = AsyncMock(
        return_value={"id": "c1", "thinking_enabled": False}
    )

    endpoint_manager = MagicMock()
    endpoint_manager.get_active_endpoint_model = AsyncMock(return_value=None)

    request = MagicMock()
    request.app.state.endpoint_manager = endpoint_manager
    request.app.state.config = MagicMock()

    with patch("thumbelina.api.routes.chat.create_provider") as mock_create:
        await _apply_conversation_endpoint(request, agent, "c1")

    mock_create.assert_not_called()
    assert agent.llm is None
