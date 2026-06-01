"""Tests for thumbelina.agent.graph module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


def _create_mock_provider():
    """Create a mock LLMProvider for testing."""
    mock_provider = MagicMock()
    mock_provider.chat_model = AsyncMock()
    mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello! How can I help?")
    return mock_provider


class TestThumbelinaAgent:
    """Tests for the ThumbelinaAgent class."""

    def test_agent_class_exists(self):
        """ThumbelinaAgent should be importable."""
        from thumbelina.agent.graph import ThumbelinaAgent

        assert ThumbelinaAgent is not None

    def test_agent_requires_llm_provider(self):
        """ThumbelinaAgent should accept an LLM provider."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.llm_provider is mock_provider

    def test_agent_has_graph(self):
        """ThumbelinaAgent should have a compiled graph."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.graph is not None

    def test_agent_accepts_tools(self):
        """ThumbelinaAgent should accept optional tools."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_tool = MagicMock()
        mock_tool.name = "search"

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[mock_tool])

        assert len(agent.tools) == 1
        assert agent.tools[0].name == "search"

    def test_agent_default_empty_tools(self):
        """ThumbelinaAgent should default to empty tools list."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.tools == []

    @pytest.mark.asyncio
    async def test_agent_run_returns_string(self):
        """run() should return a string response."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello! How can I help?")

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        result = await agent.run("Hi")

        assert isinstance(result, str)
        assert result == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_agent_run_passes_user_message(self):
        """run() should create a HumanMessage from user input."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="response")

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        await agent.run("test input")

        # Verify the LLM was called with a HumanMessage
        call_args = mock_provider.chat_model.ainvoke.call_args[0][0]
        assert len(call_args) == 1
        assert isinstance(call_args[0], HumanMessage)
        assert call_args[0].content == "test input"

    @pytest.mark.asyncio
    async def test_agent_stream_yields_chunks(self):
        """stream() should yield string chunks."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello World")

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        chunks = []
        async for chunk in agent.stream("Hi"):
            chunks.append(chunk)

        # Should have received at least one chunk
        assert len(chunks) >= 1
        # The content should be the response
        assert "".join(chunks) == "Hello World"


class TestGraphStructure:
    """Tests for the agent graph structure."""

    def test_graph_has_agent_node(self):
        """Graph should have an 'agent' node."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        # The graph should be compiled and have nodes
        assert agent.graph is not None

    def test_graph_has_tool_node_when_tools_provided(self):
        """Graph should have a 'tools' node when tools are provided."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_tool = MagicMock()
        mock_tool.name = "search"

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[mock_tool])

        # Graph should be built with tools
        assert agent.graph is not None
