"""Agent graph definition and ThumbelinaAgent class."""

from __future__ import annotations

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


class ThumbelinaAgent:
    """Main agent class that orchestrates the LangGraph agent loop.

    Parameters
    ----------
    llm_provider:
        The LLM provider to use for generating responses.
    tools:
        Optional list of tools the agent can use.
    """

    def __init__(self, llm_provider: LLMProvider, tools: list[BaseTool] | None = None) -> None:
        self.llm_provider = llm_provider
        self.llm = llm_provider.chat_model
        self.tools: list[BaseTool] = tools or []
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
        return await call_model(state, self.llm)

    async def _tool_node_node(self, state: AgentState) -> dict[str, list[Any]]:
        """Node wrapper for executing tools."""
        return await tool_node(state, self.tools)

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
        initial_state: AgentState = {"messages": [HumanMessage(content=user_input)]}
        result = await self.graph.ainvoke(initial_state)

        # Get the last AI message
        last_message = result["messages"][-1]
        if isinstance(last_message, AIMessage):
            return str(last_message.content)

        return str(last_message.content)

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
        initial_state: AgentState = {"messages": [HumanMessage(content=user_input)]}

        async for event in self.graph.astream(initial_state):
            # Each event is a dict with node name as key and state update as value
            for node_name, state_update in event.items():
                if "messages" in state_update:
                    for message in state_update["messages"]:
                        if isinstance(message, AIMessage) and message.content:
                            yield str(message.content)
