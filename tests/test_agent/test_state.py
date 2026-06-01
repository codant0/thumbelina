"""Tests for thumbelina.agent.state module."""

from __future__ import annotations

import pytest


class TestAgentState:
    """Tests for the AgentState TypedDict."""

    def test_agent_state_is_typeddict(self):
        """AgentState should be a TypedDict."""
        from thumbelina.agent.state import AgentState
        from typing import TypedDict

        assert isinstance(AgentState, type)
        # Check it has the __annotations__ attribute (TypedDicts do)
        assert hasattr(AgentState, "__annotations__")

    def test_agent_state_has_messages_field(self):
        """AgentState should have a 'messages' field."""
        from thumbelina.agent.state import AgentState

        annotations = AgentState.__annotations__
        assert "messages" in annotations

    def test_messages_field_is_list(self):
        """Messages field should be a list type."""
        from thumbelina.agent.state import AgentState
        from langchain_core.messages import BaseMessage

        annotations = AgentState.__annotations__
        msg_type = annotations["messages"]
        # Should be a list or Annotated[list, ...]
        assert "list" in str(msg_type).lower()

    def test_agent_state_can_be_created(self):
        """Should be able to create an AgentState dict."""
        from thumbelina.agent.state import AgentState
        from langchain_core.messages import HumanMessage

        state: AgentState = {"messages": [HumanMessage(content="hello")]}
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "hello"

    def test_agent_state_starts_empty(self):
        """An empty AgentState should have an empty messages list."""
        from thumbelina.agent.state import AgentState

        state: AgentState = {"messages": []}
        assert state["messages"] == []
