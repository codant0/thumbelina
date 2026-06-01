"""Agent state definition for the LangGraph agent loop."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State schema for the Thumbelina agent.

    Attributes
    ----------
    messages:
        The conversation history. Uses ``add_messages`` as a reducer so that
        new messages are *appended* to the list rather than replacing it.
    """

    messages: Annotated[list[BaseMessage], add_messages]
