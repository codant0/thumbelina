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
    with patch("thumbelina.api.routes.chat.create_provider", return_value=provider) as mock_create:
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


@pytest.mark.asyncio
async def test_apply_conversation_role_overrides_agent_role():
    """A conversation role should override the cloned agent's role and prompt."""
    from unittest.mock import AsyncMock, MagicMock

    from thumbelina.api.routes.chat import _apply_conversation_role
    from thumbelina.prompts.roles import get_role_prompt

    agent = MagicMock()
    agent.role = "assistant"
    agent.role_prompt = get_role_prompt("assistant")
    agent.memory_manager = MagicMock()
    agent.memory_manager.get_conversation = AsyncMock(return_value={"id": "c1", "role": "coder"})

    await _apply_conversation_role(agent, "c1")

    assert agent.role == "coder"
    assert agent.role_prompt == get_role_prompt("coder")


@pytest.mark.asyncio
async def test_apply_conversation_role_unknown_role_keeps_default():
    """Unknown conversation roles should be ignored (agent keeps its default)."""
    from unittest.mock import AsyncMock, MagicMock

    from thumbelina.api.routes.chat import _apply_conversation_role
    from thumbelina.prompts.roles import get_role_prompt

    agent = MagicMock()
    agent.role = "assistant"
    agent.role_prompt = get_role_prompt("assistant")
    agent.memory_manager = MagicMock()
    agent.memory_manager.get_conversation = AsyncMock(return_value={"id": "c1", "role": "ghost"})

    await _apply_conversation_role(agent, "c1")

    assert agent.role == "assistant"
    assert agent.role_prompt == get_role_prompt("assistant")


@pytest.mark.asyncio
async def test_apply_conversation_role_no_role_configured():
    """Without a conversation role, the agent's role stays untouched."""
    from unittest.mock import AsyncMock, MagicMock

    from thumbelina.api.routes.chat import _apply_conversation_role

    agent = MagicMock()
    agent.role = "assistant"
    agent.role_prompt = "default prompt"
    agent.memory_manager = MagicMock()
    agent.memory_manager.get_conversation = AsyncMock(return_value={"id": "c1"})

    await _apply_conversation_role(agent, "c1")

    assert agent.role == "assistant"
    assert agent.role_prompt == "default prompt"


@pytest.mark.asyncio
async def test_apply_conversation_role_without_memory():
    """Without a memory manager the helper should be a no-op."""
    from unittest.mock import MagicMock

    from thumbelina.api.routes.chat import _apply_conversation_role

    agent = MagicMock()
    agent.role = "assistant"
    agent.role_prompt = "default prompt"
    agent.memory_manager = None

    await _apply_conversation_role(agent, "c1")

    assert agent.role == "assistant"


class TestResolveContextWindowTokens:
    """按会话的上下文窗口解析链路（T4）。"""

    DEFAULT = 128_000

    @staticmethod
    def _endpoint(context_window=None, api_key="sk-test", endpoint_id="ep-1"):
        from datetime import UTC, datetime

        from thumbelina.llm.endpoint_manager import LLMEndpoint

        now = datetime.now(UTC)
        return LLMEndpoint(
            id=endpoint_id,
            provider="openai",
            name="Test endpoint",
            base_url="https://api.example.com/v1",
            models=["gpt-4o"],
            active_model="gpt-4o",
            api_key=api_key,
            context_window=context_window,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _memory(conv):
        from unittest.mock import AsyncMock, MagicMock

        memory = MagicMock()
        memory.get_conversation = AsyncMock(return_value=conv)
        return memory

    @pytest.mark.asyncio
    async def test_conversation_endpoint_window_wins(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        endpoint_manager = MagicMock()
        endpoint_manager.get_endpoint = AsyncMock(return_value=self._endpoint("32K"))
        endpoint_manager.get_active_endpoint_model = AsyncMock()

        memory = self._memory({"id": "c1", "endpoint_id": "ep-1"})
        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == 32_000
        endpoint_manager.get_endpoint.assert_awaited_once_with("ep-1")
        endpoint_manager.get_active_endpoint_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_conversation_endpoint_without_window_falls_back(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        endpoint_manager = MagicMock()
        endpoint_manager.get_endpoint = AsyncMock(return_value=self._endpoint(None))

        memory = self._memory({"id": "c1", "endpoint_id": "ep-1"})
        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == self.DEFAULT

    @pytest.mark.asyncio
    async def test_unusable_conversation_endpoint_falls_back(self):
        """没有 api key 的端点不可用 → 采用默认窗口。"""
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        endpoint_manager = MagicMock()
        endpoint_manager.get_endpoint = AsyncMock(return_value=self._endpoint("32K", api_key=""))
        endpoint_manager.get_active_endpoint_model = AsyncMock()

        memory = self._memory({"id": "c1", "endpoint_id": "ep-1"})
        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == self.DEFAULT
        # 已绑定但不可用的端点不会回落到全局端点。
        endpoint_manager.get_active_endpoint_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_globally_active_endpoint_window(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        endpoint_manager = MagicMock()
        endpoint_manager.get_active_endpoint_model = AsyncMock(
            return_value=(self._endpoint("64K", endpoint_id="ep-active"), "gpt-4o")
        )

        memory = self._memory({"id": "c1"})
        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == 64_000

    @pytest.mark.asyncio
    async def test_globally_active_endpoint_without_window_falls_back(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        endpoint_manager = MagicMock()
        endpoint_manager.get_active_endpoint_model = AsyncMock(
            return_value=(self._endpoint(None, endpoint_id="ep-active"), "gpt-4o")
        )

        memory = self._memory({"id": "c1"})
        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == self.DEFAULT

    @pytest.mark.asyncio
    async def test_no_endpoints_returns_default(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        endpoint_manager = MagicMock()
        endpoint_manager.get_active_endpoint_model = AsyncMock(return_value=None)

        memory = self._memory({"id": "c1"})
        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == self.DEFAULT

    @pytest.mark.asyncio
    async def test_missing_dependencies_return_default(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        memory = self._memory({"id": "c1"})
        endpoint_manager = MagicMock()
        endpoint_manager.get_active_endpoint_model = AsyncMock()

        assert await resolve_context_window_tokens(None, endpoint_manager, "c1", 999) == 999
        assert await resolve_context_window_tokens(memory, None, "c1", 999) == 999
        assert await resolve_context_window_tokens(memory, endpoint_manager, None, 999) == 999

    @pytest.mark.asyncio
    async def test_lookup_error_returns_default(self):
        from unittest.mock import AsyncMock, MagicMock

        from thumbelina.api.routes.chat import resolve_context_window_tokens

        memory = MagicMock()
        memory.get_conversation = AsyncMock(side_effect=RuntimeError("db down"))
        endpoint_manager = MagicMock()

        tokens = await resolve_context_window_tokens(memory, endpoint_manager, "c1", self.DEFAULT)

        assert tokens == self.DEFAULT


def test_chat_route_passes_default_window_tokens(client):
    """POST /chat 应把解析出的窗口（此处为默认值）转发给 run()。"""
    response = client.post("/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 200

    agent = client.app.state.agent
    assert agent.run.await_args.kwargs["context_window_tokens"] == 128_000
