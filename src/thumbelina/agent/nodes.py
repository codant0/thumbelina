"""Agent nodes for the LangGraph agent loop."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from thumbelina.agent.state import AgentState

logger = logging.getLogger(__name__)

# 工具事件回调(工具可见性特性):收到单个工具的执行结果摘要。
# payload 形如 ``{"call_id", "is_error", "duration_ms", "content"}``。
ToolEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


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


async def tool_node(
    state: AgentState,
    tools: list[BaseTool],
    on_tool_event: ToolEventCallback | None = None,
) -> dict[str, list[ToolMessage]]:
    """Execute tool calls from the last AI message.

    Tool calls from the same AIMessage are dispatched concurrently with
    ``asyncio.gather`` so a model that emits N independent tool calls in one
    turn waits ``max(t_i)`` instead of ``sum(t_i)``. ``gather`` preserves the
    input order, so the returned ``ToolMessage`` list always aligns with the
    original ``tool_calls`` list by ``tool_call_id`` (required by OpenAI-style
    providers). One failing tool does not abort the rest: failures are
    captured via ``return_exceptions=True`` and rendered as an
    ``Error executing tool ...`` ``ToolMessage``.

    Parameters
    ----------
    state:
        Current agent state containing the message history.
    tools:
        List of available tools.
    on_tool_event:
        Optional async callback invoked per tool the moment it finishes
        (before the whole ``gather`` batch completes), with a payload
        ``{"call_id", "is_error", "duration_ms", "content"}``. Callback
        exceptions are swallowed (debug log) and never affect tool
        execution. The error state comes from the control flow here, not
        from inspecting the content string.

    Returns
    -------
    dict[str, list[ToolMessage]]
        Updated state with tool execution results.
    """
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    tool_map = {tool.name: tool for tool in tools}

    async def _invoke_one(tool_call: dict) -> ToolMessage:
        tool_name = tool_call["name"]
        tool_call_id = tool_call["id"]
        started = time.monotonic()

        async def _notify(is_error: bool, content: str) -> None:
            if on_tool_event is None:
                return
            try:
                await on_tool_event(
                    {
                        "call_id": tool_call_id,
                        "is_error": is_error,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "content": content,
                    }
                )
            except Exception:
                logger.debug("tool_node on_tool_event callback failed", exc_info=True)

        if tool_name not in tool_map:
            content = f"Error: Unknown tool '{tool_name}'"
            await _notify(True, content)
            return ToolMessage(content=content, tool_call_id=tool_call_id)

        try:
            result = await tool_map[tool_name].ainvoke(tool_call["args"])
        except Exception as exc:
            content = f"Error executing tool '{tool_name}': {exc}"
            await _notify(True, content)
            return ToolMessage(content=content, tool_call_id=tool_call_id)
        content = str(result)
        await _notify(False, content)
        return ToolMessage(content=content, tool_call_id=tool_call_id)

    tool_messages: list[ToolMessage] = list(
        await asyncio.gather(*(_invoke_one(tc) for tc in last_message.tool_calls))
    )

    return {"messages": tool_messages}
