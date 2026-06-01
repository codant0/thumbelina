"""Tests for thumbelina.agent.edges module."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage


class TestShouldContinue:
    """Tests for the should_continue conditional edge function."""

    def test_should_continue_exists(self):
        """should_continue should be a callable."""
        from thumbelina.agent.edges import should_continue

        assert callable(should_continue)

    def test_returns_end_when_no_tool_calls(self):
        """should_continue should return END when AI has no tool calls."""
        from thumbelina.agent.edges import should_continue
        from thumbelina.agent.state import AgentState
        from langgraph.graph import END

        state: AgentState = {"messages": [AIMessage(content="Just a response")]}
        result = should_continue(state)

        assert result == END

    def test_returns_continue_when_tool_calls_present(self):
        """should_continue should return 'continue' when AI has tool calls."""
        from thumbelina.agent.edges import should_continue
        from thumbelina.agent.state import AgentState

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "search", "args": {"query": "test"}}],
        )
        state: AgentState = {"messages": [ai_msg]}
        result = should_continue(state)

        assert result == "continue"

    def test_handles_multiple_messages(self):
        """should_continue should check only the last message."""
        from thumbelina.agent.edges import should_continue
        from thumbelina.agent.state import AgentState
        from langgraph.graph import END

        messages = [
            HumanMessage(content="Hi"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "search", "args": {}}],
            ),
            AIMessage(content="Final response"),
        ]
        state: AgentState = {"messages": messages}
        result = should_continue(state)

        assert result == END


class TestEdgeConstants:
    """Tests for edge name constants."""

    def test_continue_constant_exists(self):
        """CONTINUE constant should be defined."""
        from thumbelina.agent.edges import CONTINUE

        assert CONTINUE == "continue"

    def test_end_constant_exists(self):
        """END constant should be defined and match langgraph's END."""
        from thumbelina.agent.edges import END
        from langgraph.graph import END as LangGraphEND

        assert END == LangGraphEND
