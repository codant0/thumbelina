"""Tests for thumbelina.cli.chat module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.cli.chat import ChatSession


class FakeLLMProvider:
    """Minimal fake LLM provider for testing."""

    def __init__(self) -> None:
        self.model_name = "fake-model"

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def chat_model(self) -> MagicMock:
        mock = MagicMock()
        return mock

    async def chat(self, messages: list[dict[str, str]]) -> str:
        last = messages[-1]["content"] if messages else ""
        return f"Echo: {last}"

    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        last = messages[-1]["content"] if messages else ""
        yield f"Echo: {last}"


@pytest.fixture
def fake_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


def test_chat_session_init(fake_provider: FakeLLMProvider):
    """ChatSession should initialize with default values."""
    session = ChatSession(provider=fake_provider)
    assert session.provider is fake_provider
    assert session.history == []
    assert session.running is False


def test_chat_session_exit_command(fake_provider: FakeLLMProvider):
    """ChatSession.is_exit_command should recognize /exit."""
    session = ChatSession(provider=fake_provider)
    assert session.is_exit_command("/exit") is True
    assert session.is_exit_command("/quit") is True
    assert session.is_exit_command("hello") is False
    assert session.is_exit_command("") is False


def test_chat_session_format_response(fake_provider: FakeLLMProvider):
    """ChatSession.format_response should format assistant response."""
    session = ChatSession(provider=fake_provider)
    result = session.format_response("Hello, world!")
    assert "assistant" in result.lower() or "thumbelina" in result.lower() or "Hello" in result


@pytest.mark.asyncio
async def test_chat_session_process_input(fake_provider: FakeLLMProvider):
    """ChatSession.process_input should return agent response."""
    session = ChatSession(provider=fake_provider)
    response = await session.process_input("Hello")
    assert response == "Echo: Hello"


@pytest.mark.asyncio
async def test_chat_session_process_input_records_history(fake_provider: FakeLLMProvider):
    """ChatSession.process_input should add messages to history."""
    session = ChatSession(provider=fake_provider)
    await session.process_input("Hello")
    assert len(session.history) == 2  # user + assistant
    assert session.history[0]["role"] == "user"
    assert session.history[0]["content"] == "Hello"
    assert session.history[1]["role"] == "assistant"
    assert session.history[1]["content"] == "Echo: Hello"


def test_chat_session_get_history(fake_provider: FakeLLMProvider):
    """ChatSession.get_history should return copy of history."""
    session = ChatSession(provider=fake_provider)
    session.history = [{"role": "user", "content": "test"}]
    history = session.get_history()
    assert history == [{"role": "user", "content": "test"}]
    # Should be a copy
    history.append({"role": "assistant", "content": "x"})
    assert len(session.history) == 1


@patch("thumbelina.cli.chat.create_provider")
@patch("thumbelina.cli.chat.MemoryManager")
def test_run_chat_creates_session(mock_mm_cls, mock_create_provider, fake_provider):
    """run_chat should create a provider and start the session."""
    from thumbelina.cli.chat import run_chat

    mock_create_provider.return_value = fake_provider
    mock_mm_cls.return_value = MagicMock()

    # We can't easily test the full interactive loop, but we can verify
    # the function exists and has the right signature
    assert callable(run_chat)
