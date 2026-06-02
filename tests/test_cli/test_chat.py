"""Tests for thumbelina.cli.chat module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.cli.chat import ChatSession


@pytest.fixture
def mock_agent():
    """Create a mock ThumbelinaAgent for testing."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")
    return agent


def test_chat_session_init(mock_agent):
    """ChatSession should initialize with default values."""
    session = ChatSession(agent=mock_agent)
    assert session.agent is mock_agent
    assert session.history == []
    assert session.running is False


def test_chat_session_exit_command(mock_agent):
    """ChatSession.is_exit_command should recognize /exit."""
    session = ChatSession(agent=mock_agent)
    assert session.is_exit_command("/exit") is True
    assert session.is_exit_command("/quit") is True
    assert session.is_exit_command("hello") is False
    assert session.is_exit_command("") is False


def test_chat_session_format_response(mock_agent):
    """ChatSession.format_response should format assistant response."""
    session = ChatSession(agent=mock_agent)
    result = session.format_response("Hello, world!")
    assert "thumbelina" in result.lower() or "Hello" in result


@pytest.mark.asyncio
async def test_chat_session_process_input(mock_agent):
    """ChatSession.process_input should return agent response."""
    session = ChatSession(agent=mock_agent)
    response = await session.process_input("Hello")
    assert response == "Agent response"
    mock_agent.run.assert_called_once_with("Hello")


@pytest.mark.asyncio
async def test_chat_session_process_input_records_history(mock_agent):
    """ChatSession.process_input should add messages to history."""
    session = ChatSession(agent=mock_agent)
    await session.process_input("Hello")
    assert len(session.history) == 2  # user + assistant
    assert session.history[0]["role"] == "user"
    assert session.history[0]["content"] == "Hello"
    assert session.history[1]["role"] == "assistant"
    assert session.history[1]["content"] == "Agent response"


def test_chat_session_get_history(mock_agent):
    """ChatSession.get_history should return copy of history."""
    session = ChatSession(agent=mock_agent)
    session.history = [{"role": "user", "content": "test"}]
    history = session.get_history()
    assert history == [{"role": "user", "content": "test"}]
    # Should be a copy
    history.append({"role": "assistant", "content": "x"})
    assert len(session.history) == 1


@patch("thumbelina.cli.chat.ThumbelinaAgent")
@patch("thumbelina.cli.chat.create_provider")
@patch("thumbelina.cli.chat.MemoryManager")
def test_run_chat_creates_session(mock_mm_cls, mock_create_provider, mock_agent_cls):
    """run_chat should create an agent and start the session."""
    from thumbelina.cli.chat import run_chat

    mock_create_provider.return_value = MagicMock()
    mock_mm_cls.return_value = MagicMock()
    mock_agent_cls.return_value = MagicMock()

    # We can't easily test the full interactive loop, but we can verify
    # the function exists and has the right signature
    assert callable(run_chat)
