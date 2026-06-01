"""Conditional edges for the LangGraph agent loop."""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.graph import END

from thumbelina.agent.state import AgentState

# Edge name constants
CONTINUE = "continue"


def should_continue(state: AgentState) -> str:
    """Determine whether the agent should continue with tool calls or end.

    Parameters
    ----------
    state:
        Current agent state containing the message history.

    Returns
    -------
    str
        ``"continue"`` if the last message has tool calls, ``"end"`` otherwise.
    """
    last_message = state["messages"][-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return CONTINUE

    return END
