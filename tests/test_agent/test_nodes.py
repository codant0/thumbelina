"""Tests for thumbelina.agent.nodes module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage


class TestCallModelNode:
    """Tests for the call_model node function."""

    def test_call_model_exists(self):
        """call_model should be a callable."""
        from thumbelina.agent.nodes import call_model

        assert callable(call_model)

    @pytest.mark.asyncio
    async def test_call_model_returns_state_with_messages(self):
        """call_model should return state with the AI response appended."""
        from thumbelina.agent.nodes import call_model
        from thumbelina.agent.state import AgentState

        mock_response = AIMessage(content="Hello! How can I help?")
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        state: AgentState = {"messages": [HumanMessage(content="Hi")]}
        result = await call_model(state, mock_llm)

        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_call_model_passes_messages_to_llm(self):
        """call_model should pass all messages to the LLM."""
        from thumbelina.agent.nodes import call_model
        from thumbelina.agent.state import AgentState

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="response")

        messages = [
            HumanMessage(content="Hi"),
            AIMessage(content="Hello"),
            HumanMessage(content="How are you?"),
        ]
        state: AgentState = {"messages": messages}
        await call_model(state, mock_llm)

        mock_llm.ainvoke.assert_called_once_with(messages)


class TestToolNode:
    """Tests for the tool_node function."""

    def test_tool_node_exists(self):
        """tool_node should be a callable."""
        from thumbelina.agent.nodes import tool_node

        assert callable(tool_node)

    @pytest.mark.asyncio
    async def test_tool_node_processes_tool_calls(self):
        """tool_node should execute tool calls and return tool messages."""
        from langchain_core.messages import ToolMessage

        from thumbelina.agent.nodes import tool_node
        from thumbelina.agent.state import AgentState

        # Create a mock tool with async ainvoke
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.ainvoke = AsyncMock(return_value="search results")

        # Create an AI message with a tool call
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "search", "args": {"query": "test"}}],
        )

        state: AgentState = {"messages": [ai_msg]}
        result = await tool_node(state, [mock_tool])

        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ToolMessage)
        assert result["messages"][0].content == "search results"

    @pytest.mark.asyncio
    async def test_tool_node_handles_no_tool_calls(self):
        """tool_node should return empty messages when no tool calls exist."""
        from thumbelina.agent.nodes import tool_node
        from thumbelina.agent.state import AgentState

        state: AgentState = {"messages": [AIMessage(content="Just a response")]}
        result = await tool_node(state, [])

        assert "messages" in result
        assert result["messages"] == []
