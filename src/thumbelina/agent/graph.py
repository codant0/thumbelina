"""Agent graph definition and ThumbelinaAgent class."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from thumbelina.agent.edges import CONTINUE, should_continue
from thumbelina.agent.nodes import call_model, tool_node
from thumbelina.agent.state import AgentState
from thumbelina.llm.base import LLMProvider
from thumbelina.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class ThumbelinaAgent:
    """Main agent class that orchestrates the LangGraph agent loop.

    Parameters
    ----------
    llm_provider:
        The LLM provider to use for generating responses.
    tools:
        Optional list of tools the agent can use.
    memory_manager:
        Optional memory manager for conversation persistence.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: list[BaseTool] | None = None,
        memory_manager: MemoryManager | None = None,
        request_timeout: float | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.llm = llm_provider.chat_model
        self.tools: list[BaseTool] = tools or []
        self.memory_manager = memory_manager
        self.request_timeout = request_timeout
        self.current_conversation_id: str | None = None
        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """Build and compile the LangGraph agent graph.

        Returns
        -------
        CompiledStateGraph
            The compiled agent graph.
        """
        # Create the graph with our state schema
        graph = StateGraph(AgentState)

        # Add the agent node (calls the LLM)
        graph.add_node("agent", self._call_model_node)

        # Add tools node if tools are provided
        if self.tools:
            graph.add_node("tools", self._tool_node_node)

            # Conditional edges: agent -> tools or end
            graph.add_conditional_edges(
                "agent",
                should_continue,
                {
                    CONTINUE: "tools",
                    END: END,
                },
            )

            # After tools, go back to agent
            graph.add_edge("tools", "agent")
        else:
            # No tools: agent -> end
            graph.add_edge("agent", END)

        # Set entry point
        graph.set_entry_point("agent")

        # Compile the graph
        return graph.compile()

    async def _call_model_node(self, state: AgentState) -> dict[str, list[AIMessage]]:
        """Node wrapper for calling the LLM."""
        return await call_model(state, self.llm, timeout=self.request_timeout)

    async def _tool_node_node(self, state: AgentState) -> dict[str, list[Any]]:
        """Node wrapper for executing tools."""
        return await tool_node(state, self.tools)

    async def _ensure_conversation(self) -> None:
        """Create a conversation if memory is enabled and none exists."""
        if self.memory_manager and not self.current_conversation_id:
            try:
                self.current_conversation_id = await self.memory_manager.create_conversation()
            except Exception:
                logger.warning(
                    "Failed to create conversation — messages will not be persisted "
                    "for this request",
                    exc_info=True,
                )

    async def _persist_message(self, role: str, content: str) -> None:
        """Persist a message to memory if enabled.

        Parameters
        ----------
        role:
            Role of the message sender (user, assistant, system).
        content:
            Content of the message.
        """
        if self.memory_manager and self.current_conversation_id:
            try:
                await self.memory_manager.add_message(
                    conversation_id=self.current_conversation_id,
                    role=role,
                    content=content,
                )
            except Exception:
                logger.warning("Failed to persist message to memory", exc_info=True)

    def clone(self) -> ThumbelinaAgent:
        """Create an independent clone sharing the same LLM provider and memory manager.

        Each clone has its own compiled graph and conversation tracking,
        making it safe for concurrent use (e.g., per-WebSocket-connection).

        Returns
        -------
        ThumbelinaAgent
            A new agent instance with isolated graph state.
        """
        return ThumbelinaAgent(
            llm_provider=self.llm_provider,
            tools=list(self.tools),
            memory_manager=self.memory_manager,
            request_timeout=self.request_timeout,
        )

    async def run(self, user_input: str) -> str:
        """Run the agent with user input and return the response.

        Parameters
        ----------
        user_input:
            The user's message.

        Returns
        -------
        str
            The agent's response.
        """
        await self._ensure_conversation()
        await self._persist_message("user", user_input)

        initial_state: AgentState = {"messages": [HumanMessage(content=user_input)]}
        result = await self.graph.ainvoke(initial_state)

        # Get the last AI message
        last_message = result["messages"][-1]
        response = str(last_message.content)

        await self._persist_message("assistant", response)

        return response

    async def stream(self, user_input: str) -> AsyncGenerator[str, None]:
        """Stream the agent's response.

        Parameters
        ----------
        user_input:
            The user's message.

        Yields
        ------
        str
            Incremental text chunks of the response.
        """
        await self._ensure_conversation()
        await self._persist_message("user", user_input)

        initial_state: AgentState = {"messages": [HumanMessage(content=user_input)]}
        full_response = ""

        async for event in self.graph.astream(initial_state):
            # Each event is a dict with node name as key and state update as value
            for node_name, state_update in event.items():
                if "messages" in state_update:
                    for message in state_update["messages"]:
                        if isinstance(message, AIMessage) and message.content:
                            chunk = str(message.content)
                            full_response += chunk
                            yield chunk

        if full_response:
            await self._persist_message("assistant", full_response)
