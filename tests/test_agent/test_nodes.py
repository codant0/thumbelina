"""Tests for thumbelina.agent.nodes module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool


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

    @pytest.mark.asyncio
    async def test_tool_node_returns_error_for_unknown_tool(self):
        """Unknown tool names should yield an error ToolMessage, not be skipped."""
        from langchain_core.messages import ToolMessage

        from thumbelina.agent.nodes import tool_node
        from thumbelina.agent.state import AgentState

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "missing", "args": {}}],
        )

        state: AgentState = {"messages": [ai_msg]}
        result = await tool_node(state, [])

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert msg.tool_call_id == "call_1"
        assert "Unknown tool" in msg.content

    @pytest.mark.asyncio
    async def test_tool_node_returns_error_when_tool_raises(self):
        """Tool execution errors should be returned as a ToolMessage."""
        from langchain_core.messages import ToolMessage

        from thumbelina.agent.nodes import tool_node
        from thumbelina.agent.state import AgentState

        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.ainvoke = AsyncMock(side_effect=ValueError("boom"))

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "search", "args": {"query": "x"}}],
        )

        state: AgentState = {"messages": [ai_msg]}
        result = await tool_node(state, [mock_tool])

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert msg.tool_call_id == "call_1"
        assert "boom" in msg.content


@tool
def _ok_tool(dummy: str = "") -> str:
    """always returns ok"""
    return "ok result"


@tool
def _boom_tool(dummy: str = "") -> str:
    """always raises"""
    raise RuntimeError("boom")


def _state_with(tool_call: dict):
    return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}


class TestToolNodeEventCallback:
    """tool_node 的 on_tool_event 回调(工具可见性特性,Task 1)。"""

    async def test_success_event_payload(self):
        from thumbelina.agent.nodes import tool_node

        events = []

        async def cb(info):
            events.append(info)

        await tool_node(
            _state_with({"name": "_ok_tool", "args": {}, "id": "c1"}),
            [_ok_tool],
            on_tool_event=cb,
        )
        assert len(events) == 1
        assert events[0]["call_id"] == "c1"
        assert events[0]["is_error"] is False
        assert events[0]["content"] == "ok result"
        assert isinstance(events[0]["duration_ms"], int) and events[0]["duration_ms"] >= 0

    async def test_exception_event_is_error(self):
        from thumbelina.agent.nodes import tool_node

        events = []

        async def cb(info):
            events.append(info)

        result = await tool_node(
            _state_with({"name": "_boom_tool", "args": {}, "id": "c2"}),
            [_boom_tool],
            on_tool_event=cb,
        )
        assert events[0]["is_error"] is True
        assert "boom" in events[0]["content"]
        assert result["messages"][0].content.startswith("Error executing tool")

    async def test_unknown_tool_event_is_error(self):
        from thumbelina.agent.nodes import tool_node

        events = []

        async def cb(info):
            events.append(info)

        await tool_node(
            _state_with({"name": "nope", "args": {}, "id": "c3"}),
            [_ok_tool],
            on_tool_event=cb,
        )
        assert events[0]["is_error"] is True
        assert events[0]["content"] == "Error: Unknown tool 'nope'"

    async def test_callback_exception_does_not_break_execution(self):
        from thumbelina.agent.nodes import tool_node

        async def cb(info):
            raise ValueError("callback exploded")

        result = await tool_node(
            _state_with({"name": "_ok_tool", "args": {}, "id": "c4"}),
            [_ok_tool],
            on_tool_event=cb,
        )
        assert result["messages"][0].content == "ok result"

    async def test_no_callback_default_unchanged(self):
        from thumbelina.agent.nodes import tool_node

        result = await tool_node(
            _state_with({"name": "_ok_tool", "args": {}, "id": "c5"}), [_ok_tool]
        )
        assert result["messages"][0].content == "ok result"
