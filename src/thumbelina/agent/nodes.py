"""Agent nodes for the LangGraph agent loop."""

from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from thumbelina.agent.state import AgentState


async def call_model(
    state: AgentState,
    llm: BaseChatModel,
    timeout: float | None = None,
) -> dict[str, list[AIMessage]]:
    """Call the LLM with the current conversation history.

    Parameters
    ----------
    state:
        Current agent state containing the message history.
    llm:
        The LangChain chat model to invoke.
    timeout:
        Optional timeout in seconds for the LLM request.

    Returns
    -------
    dict[str, list[AIMessage]]
        Updated state with the AI response appended.

    Raises
    ------
    asyncio.TimeoutError
        If *timeout* is set and the request exceeds it.
    """
    messages = state["messages"]
    if timeout is not None:
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
    else:
        response = await llm.ainvoke(messages)
    return {"messages": [response]}


async def tool_node(state: AgentState, tools: list[BaseTool]) -> dict[str, list[ToolMessage]]:
    """Execute tool calls from the last AI message.

    Parameters
    ----------
    state:
        Current agent state containing the message history.
    tools:
        List of available tools.

    Returns
    -------
    dict[str, list[ToolMessage]]
        Updated state with tool execution results.
    """
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    tool_map = {tool.name: tool for tool in tools}
    tool_messages: list[ToolMessage] = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]

        if tool_name in tool_map:
            result = await tool_map[tool_name].ainvoke(tool_args)
            tool_messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_call_id)
            )

    return {"messages": tool_messages}
