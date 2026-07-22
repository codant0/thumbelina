"""Agent graph definition and ThumbelinaAgent class."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from thumbelina.agent.edges import CONTINUE, should_continue
from thumbelina.agent.nodes import call_model, tool_node
from thumbelina.agent.state import AgentState
from thumbelina.llm.base import LLMProvider
from thumbelina.memory.manager import MemoryManager
from thumbelina.memory.namer import AUTO_NAME_AFTER_MESSAGES, ConversationNamer
from thumbelina.memory.profiler import UserProfiler
from thumbelina.scheduler.scheduler import ScheduledTask, TaskScheduler
from thumbelina.scheduler.time_parser import TimeParser
from thumbelina.skills.application import SkillApplicationEngine
from thumbelina.skills.composition_engine import CompositionEngine
from thumbelina.subagents.manager import SubagentManager

logger = logging.getLogger(__name__)


def _make_subagent_tools(manager: SubagentManager) -> list[BaseTool]:
    """Create LangChain tools that wrap SubagentManager operations.

    Parameters
    ----------
    manager:
        The SubagentManager instance to delegate to.

    Returns
    -------
    list[BaseTool]
        List of tool-callable functions.
    """

    @tool
    async def create_subagent(task: str) -> str:
        """Create and run a subagent to execute a task asynchronously."""
        try:
            agent = await manager.create_agent(task)
            await manager.run_agent(agent.id)
            return (
                f"Subagent created with ID {agent.id}. Task: {task}. Status: {agent.status.value}"
            )
        except RuntimeError as exc:
            return f"Failed to create subagent: {exc}"

    @tool
    async def list_subagents() -> str:
        """List all subagents and their current status."""
        agents = await manager.list_agents()
        if not agents:
            return "No subagents found."
        lines = []
        for a in agents:
            line = f"- ID: {a.id}, Task: {a.task}, Status: {a.status.value}"
            if a.result:
                line += f", Result: {a.result}"
            if a.error:
                line += f", Error: {a.error}"
            lines.append(line)
        return "\n".join(lines)

    return [create_subagent, list_subagents]


def _make_scheduler_tools(scheduler: TaskScheduler) -> list[BaseTool]:
    """Create LangChain tools that wrap TaskScheduler operations.

    Parameters
    ----------
    scheduler:
        The TaskScheduler instance to delegate to.

    Returns
    -------
    list[BaseTool]
        List of tool-callable functions.
    """
    time_parser = TimeParser()

    @tool
    async def schedule_task(description: str, time_expression: str) -> str:
        """Schedule a task for a future time."""
        parsed_time = time_parser.parse(time_expression)
        if parsed_time is None:
            return f"Could not parse time expression: {time_expression}"

        task = ScheduledTask(
            description=description,
            scheduled_time=parsed_time,
        )
        await scheduler.add_task(task)
        return (
            f"Task scheduled with ID {task.id}. "
            f"Description: {description}. "
            f"Scheduled for: {parsed_time.isoformat()}"
        )

    @tool
    async def list_scheduled_tasks() -> str:
        """List all scheduled tasks and their status."""
        tasks = await scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks found."
        lines = []
        for t in tasks:
            lines.append(
                f"- ID: {t.id}, Description: {t.description}, "
                f"Scheduled: {t.scheduled_time.isoformat()}, Status: {t.status.value}"
            )
        return "\n".join(lines)

    return [schedule_task, list_scheduled_tasks]


def _make_composition_tools(engine: CompositionEngine) -> list[BaseTool]:
    """Create LangChain tools that wrap CompositionEngine operations.

    Parameters
    ----------
    engine:
        The CompositionEngine instance to delegate to.

    Returns
    -------
    list[BaseTool]
        List of tool-callable functions.
    """

    @tool
    async def create_skill_composition(skill_ids: str, name: str, description: str) -> str:
        """Create a skill composition that chains multiple skills into a workflow.

        Args:
            skill_ids: Comma-separated list of skill IDs to chain together.
            name: Name for the composition.
            description: Description of what the composition does.
        """
        ids = [s.strip() for s in skill_ids.split(",") if s.strip()]
        if not ids:
            return "No skill IDs provided."
        try:
            composition = await engine.create_composition(
                skill_ids=ids, name=name, description=description
            )
            return (
                f"Composition created with ID {composition.id}. Name: {name}. Skills: {len(ids)}."
            )
        except Exception as exc:
            return f"Failed to create composition: {exc}"

    @tool
    async def list_skill_compositions() -> str:
        """List all skill compositions and their details."""
        compositions = await engine.composition_repo.list_all()
        if not compositions:
            return "No skill compositions found."
        lines = []
        for c in compositions:
            lines.append(
                f"- ID: {c.id}, Name: {c.name}, Skills: {len(c.skill_ids)}, Usage: {c.usage_count}"
            )
        return "\n".join(lines)

    @tool
    async def execute_skill_composition(user_input: str) -> str:
        """Find and execute a matching skill composition for the given input."""
        composition = await engine.match_composition(user_input)
        if composition is None:
            return "No matching composition found for the input."
        result = await engine.execute_composition(composition, user_input)
        return result

    return [create_skill_composition, list_skill_compositions, execute_skill_composition]


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
    request_timeout:
        Optional timeout for LLM requests in seconds.
    skill_engine:
        Optional skill application engine for matching and applying skills.
    subagent_manager:
        Optional subagent manager for creating and running subagents.
    scheduler:
        Optional task scheduler for scheduling future tasks.
    composition_engine:
        Optional composition engine for creating and executing skill compositions.
    user_profiler:
        Optional user profiler for building user profiles from conversations.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: list[BaseTool] | None = None,
        memory_manager: MemoryManager | None = None,
        request_timeout: float | None = None,
        skill_engine: SkillApplicationEngine | None = None,
        subagent_manager: SubagentManager | None = None,
        scheduler: TaskScheduler | None = None,
        composition_engine: CompositionEngine | None = None,
        user_profiler: UserProfiler | None = None,
        conversation_namer: ConversationNamer | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.memory_manager = memory_manager
        self.request_timeout = request_timeout
        self.skill_engine = skill_engine
        self.subagent_manager = subagent_manager
        self.scheduler = scheduler
        self.composition_engine = composition_engine
        self.user_profiler = user_profiler
        self.conversation_namer = conversation_namer
        self.current_conversation_id: str | None = None
        # Lazily-resolved chat model; None means resolve from llm_provider.
        self._llm: BaseChatModel | None = None
        # RAG components — injected after construction, shared via clone()
        self._rag_store_manager: Any | None = None
        self._rag_embedding_registry: Any | None = None

        # Build the combined tools list
        self.tools: list[BaseTool] = list(tools) if tools else []
        if self.subagent_manager is not None:
            self.tools.extend(_make_subagent_tools(self.subagent_manager))
        if self.scheduler is not None:
            self.tools.extend(_make_scheduler_tools(self.scheduler))
        if self.composition_engine is not None:
            self.tools.extend(_make_composition_tools(self.composition_engine))

        self.graph = self._build_graph()

    def swap_provider(self, new_provider: LLMProvider) -> None:
        """Hot-swap the LLM provider at runtime.

        Updates both ``llm_provider`` and the underlying LangChain
        ``chat_model`` so that subsequent graph invocations use the new
        model.  The compiled graph does **not** need to be rebuilt.
        """
        self.llm_provider = new_provider
        self._llm = new_provider.chat_model

    @property
    def llm(self) -> BaseChatModel:
        """Return the underlying LangChain chat model.

        Lazily resolved from ``llm_provider`` on first access so that
        the server can start without valid LLM credentials.
        """
        if not hasattr(self, "_llm") or self._llm is None:
            self._llm = self.llm_provider.chat_model
        return self._llm

    @llm.setter
    def llm(self, value: BaseChatModel | None) -> None:
        # ``None`` resets to lazy resolution from ``llm_provider`` so a
        # per-conversation override can be reverted to the shared default.
        self._llm = value

    def _build_graph(self) -> CompiledStateGraph[AgentState, Any]:
        """Build and compile the LangGraph agent graph."""
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._call_model_node)

        if self.tools:
            graph.add_node("tools", self._tool_node_node)
            graph.add_conditional_edges(
                "agent",
                should_continue,
                {
                    CONTINUE: "tools",
                    END: END,
                },
            )
            graph.add_edge("tools", "agent")
        else:
            graph.add_edge("agent", END)

        graph.set_entry_point("agent")
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
        """Persist a message to memory if enabled."""
        if self.memory_manager and self.current_conversation_id:
            try:
                await self.memory_manager.add_message(
                    conversation_id=self.current_conversation_id,
                    role=role,
                    content=content,
                )
            except Exception:
                logger.warning("Failed to persist message to memory", exc_info=True)

    async def _get_skill_context(self, user_input: str) -> str | None:
        """Attempt to find and apply a matching skill for the user input."""
        if self.skill_engine is None:
            return None
        try:
            matches = await self.skill_engine.find_matching_skills(user_input)
            if matches:
                context = await self.skill_engine.apply_skill(matches[0], user_input)
                return context
        except Exception:
            logger.warning("Skill matching failed", exc_info=True)
        return None

    async def _get_user_context(self, user_id: str = "default") -> str | None:
        """Get user profile context for injection into the agent."""
        if self.user_profiler is None:
            return None
        try:
            return await self.user_profiler.get_user_context(user_id)
        except Exception:
            logger.warning("Failed to get user context", exc_info=True)
        return None

    async def _get_rag_context(self, query: str, knowledge_base_id: str) -> str | None:
        """Retrieve RAG context for the given query from the specified knowledge base."""
        if not knowledge_base_id or not self._rag_store_manager or not self._rag_embedding_registry:
            return None

        try:
            store = self._rag_store_manager.get_or_create_store(knowledge_base_id)
            embedder = self._rag_embedding_registry.create()

            from thumbelina.rag.retrieval.context_formatter import ContextFormatter
            from thumbelina.rag.retrieval.strategies import SimpleRetriever

            retriever = SimpleRetriever(embedding_model=embedder, vector_store=store)
            chunks = await asyncio.to_thread(retriever.retrieve, query, 5)

            if not chunks:
                return None

            formatter = ContextFormatter()
            context = formatter.format(chunks)
            if context:
                return f"以下是与用户问题相关的知识库内容，请参考回答：\n\n{context}"
        except Exception:
            logger.warning("RAG context retrieval failed", exc_info=True)

        return None

    async def _maybe_auto_name(self) -> None:
        """Generate and persist a conversation title when none is set yet.

        Triggered after the first few user turns. Falls back silently when
        memory, the namer, or the LLM call is unavailable, and never
        overwrites a name the user set explicitly (including the reserved
        WeChat conversation).
        """
        if self.conversation_namer is None or self.memory_manager is None:
            return
        if not self.current_conversation_id:
            return
        try:
            conv = await self.memory_manager.get_conversation(self.current_conversation_id)
            if conv is None or conv.get("name"):
                return
            messages = await self.memory_manager.get_messages(self.current_conversation_id)
            user_count = sum(1 for m in messages if m.get("role") == "user")
            if user_count < AUTO_NAME_AFTER_MESSAGES:
                return
            name = await self.conversation_namer.suggest_name(messages)
            if name:
                await self.memory_manager.rename_conversation(self.current_conversation_id, name)
        except Exception:
            logger.warning("Auto-naming failed", exc_info=True)

    def clone(self) -> ThumbelinaAgent:
        """Create an independent clone sharing the same LLM provider and memory manager."""
        cloned = ThumbelinaAgent(
            llm_provider=self.llm_provider,
            tools=list(self.tools),
            memory_manager=self.memory_manager,
            request_timeout=self.request_timeout,
            skill_engine=self.skill_engine,
            subagent_manager=self.subagent_manager,
            scheduler=self.scheduler,
            composition_engine=self.composition_engine,
            user_profiler=self.user_profiler,
            conversation_namer=self.conversation_namer,
        )
        cloned._rag_store_manager = self._rag_store_manager
        cloned._rag_embedding_registry = self._rag_embedding_registry
        return cloned

    async def run(self, user_input: str) -> str:
        """Run the agent with user input and return the response."""
        await self._ensure_conversation()
        await self._persist_message("user", user_input)

        # Check for matching skills and prepend context if found
        initial_messages: list[Any] = []
        user_context = await self._get_user_context()
        if user_context:
            initial_messages.append(SystemMessage(content=user_context))

        # Inject RAG context if a knowledge base is bound to the conversation
        rag_context = None
        if self.current_conversation_id and self.memory_manager:
            try:
                conv = await self.memory_manager.get_conversation(self.current_conversation_id)
                if conv:
                    kb_id = conv.get("knowledge_base_id")
                    if kb_id:
                        rag_context = await self._get_rag_context(user_input, kb_id)
            except Exception:
                logger.warning("Failed to get RAG context", exc_info=True)
        if rag_context:
            initial_messages.append(SystemMessage(content=rag_context))

        skill_context = await self._get_skill_context(user_input)
        if skill_context:
            initial_messages.append(SystemMessage(content=skill_context))
        initial_messages.append(HumanMessage(content=user_input))

        initial_state: AgentState = {"messages": initial_messages}
        result = await self.graph.ainvoke(initial_state)

        last_message = result["messages"][-1]
        response = str(last_message.content)

        await self._persist_message("assistant", response)
        # Auto-name the conversation in the background so the reply is not delayed.
        asyncio.create_task(self._maybe_auto_name())

        return response

    async def stream(self, user_input: str) -> AsyncGenerator[str, None]:
        """Stream the agent's response."""
        await self._ensure_conversation()
        await self._persist_message("user", user_input)

        # Check for matching skills and prepend context if found
        initial_messages: list[Any] = []
        user_context = await self._get_user_context()
        if user_context:
            initial_messages.append(SystemMessage(content=user_context))

        # Inject RAG context if a knowledge base is bound to the conversation
        rag_context = None
        if self.current_conversation_id and self.memory_manager:
            try:
                conv = await self.memory_manager.get_conversation(self.current_conversation_id)
                if conv:
                    kb_id = conv.get("knowledge_base_id")
                    if kb_id:
                        rag_context = await self._get_rag_context(user_input, kb_id)
            except Exception:
                logger.warning("Failed to get RAG context", exc_info=True)
        if rag_context:
            initial_messages.append(SystemMessage(content=rag_context))

        skill_context = await self._get_skill_context(user_input)
        if skill_context:
            initial_messages.append(SystemMessage(content=skill_context))
        initial_messages.append(HumanMessage(content=user_input))

        initial_state: AgentState = {"messages": initial_messages}
        full_response = ""

        async for event in self.graph.astream(initial_state, stream_mode="updates"):
            for node_name, state_update in event.items():
                if "messages" in state_update:
                    for message in state_update["messages"]:
                        if (
                            isinstance(message, AIMessage)
                            and message.content
                            and not message.tool_calls
                        ):
                            chunk = str(message.content)
                            full_response += chunk
                            yield chunk

        if full_response:
            await self._persist_message("assistant", full_response)
            # Auto-name the conversation in the background so streaming is not delayed.
            asyncio.create_task(self._maybe_auto_name())
