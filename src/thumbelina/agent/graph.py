"""Agent graph definition and ThumbelinaAgent class."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from thumbelina.agent.compression import (
    SlidingWindowCompressor,
    compression_stats,
    create_compressor,
    estimate_messages_tokens,
    strip_first_assistant_thinking,
)
from thumbelina.agent.edges import CONTINUE, should_continue
from thumbelina.agent.nodes import call_model, tool_node
from thumbelina.agent.state import AgentState
from thumbelina.llm.base import LLMProvider
from thumbelina.memory.manager import MemoryManager
from thumbelina.memory.namer import AUTO_NAME_AFTER_MESSAGES, ConversationNamer
from thumbelina.memory.profiler import UserProfiler
from thumbelina.prompts.roles import get_role_prompt
from thumbelina.scheduler.scheduler import ScheduledTask, TaskScheduler
from thumbelina.scheduler.time_parser import TimeParser
from thumbelina.skills.application import SkillApplicationEngine
from thumbelina.skills.composition_engine import CompositionEngine
from thumbelina.subagents.manager import SubagentManager

if TYPE_CHECKING:
    from thumbelina.config.models import ContextConfig

logger = logging.getLogger(__name__)


def _extract_chunk_parts(message_chunk: Any) -> tuple[str, str]:
    """Split an AI message chunk into (visible_text, reasoning_text).

    Reasoning may arrive as structured content blocks (Anthropic thinking),
    ``additional_kwargs["reasoning_content"]`` (DeepSeek / OpenAI-compatible
    endpoints), or a ``reasoning`` attribute (newer langchain-openai).
    """
    text = ""
    reasoning = ""

    content = getattr(message_chunk, "content", None)
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                part_type = part.get("type")
                if part_type in ("thinking", "reasoning"):
                    reasoning += str(part.get("thinking") or part.get("text") or "")
                elif part_type == "text":
                    text += str(part.get("text", ""))
                elif part.get("text"):
                    text += str(part.get("text"))
            else:
                text += str(part)
    elif content:
        text = str(content)

    additional = getattr(message_chunk, "additional_kwargs", None) or {}
    extra = additional.get("reasoning_content") or additional.get("reasoning")
    if isinstance(extra, str):
        reasoning += extra

    attr = getattr(message_chunk, "reasoning", None)
    if isinstance(attr, str):
        reasoning += attr
    elif isinstance(attr, dict):
        reasoning += str(attr.get("text") or "")

    return text, reasoning


def _is_ordered_subset(subset: Sequence[Any], full: Sequence[Any]) -> bool:
    """Return ``True`` when *subset* appears in *full* in the same order."""
    iterator = iter(full)
    return all(any(item == candidate for item in iterator) for candidate in subset)


def _messages_state_update(
    current: Sequence[BaseMessage], compressed: Sequence[BaseMessage]
) -> dict[str, list[Any]]:
    """Translate a compressed sequence into an ``add_messages`` update.

    A pure deletion (every kept message keeps its object — and thus id —
    and order) emits only ``RemoveMessage`` entries plus any kept message
    that was modified in place (e.g. thinking blocks stripped). Any
    restructuring (e.g. a summary replacement) replaces the whole
    sequence: remove every current message, then re-append the compressed
    sequence. Messages that reuse a current id are re-appended as copies
    with fresh ids, because ``add_messages`` re-inserts a removed id at its
    original position — which would break the compressed order.
    """
    current_by_id = {message.id: message for message in current if message.id is not None}
    kept_ids = [message.id for message in compressed]
    pure_deletion = all(mid in current_by_id for mid in kept_ids) and _is_ordered_subset(
        kept_ids, [message.id for message in current]
    )
    if pure_deletion:
        kept = set(kept_ids)
        update: list[Any] = [
            RemoveMessage(id=message.id)
            for message in current
            if message.id is not None and message.id not in kept
        ]
        # Re-emit kept messages that changed so add_messages updates them
        # in place (same id keeps their position).
        update.extend(
            m for m in compressed if m.id is not None and current_by_id.get(m.id) is not m
        )
        return {"messages": update} if update else {}

    replacement: list[Any] = [
        RemoveMessage(id=message.id) for message in current if message.id is not None
    ]
    for message in compressed:
        if message.id is not None and message.id in current_by_id:
            replacement.append(message.model_copy(update={"id": None}))
        else:
            replacement.append(message)
    return {"messages": replacement}


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
    role:
        Optional role persona name; the matching ``prompts/roles/<role>.md``
        file is injected as the leading system message on every request.
    checkpointer:
        Optional LangGraph checkpoint saver that persists graph state (the
        mutable LLM context workspace) between turns, keyed by the current
        conversation id. Clones share the same saver instance so they never
        open duplicate connections. ``None`` disables checkpointing and
        preserves pre-checkpoint behaviour exactly.
    context_config:
        Context/compression settings (``config.context``). Defaults to
        :class:`ContextConfig` defaults: strategy ``summary_recent``,
        trigger threshold 0.8, 6 recent turns.
    context_window_tokens:
        Fallback context window (in tokens, from
        ``config.llm.context_window``) used by the compress node when a
        run does not carry ``configurable["context_window_tokens"]``
        (e.g. channel paths that call the graph directly).
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
        role: str | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        context_config: ContextConfig | None = None,
        context_window_tokens: int | None = None,
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
        self.role = role
        self.role_prompt = get_role_prompt(role) if role else None
        self.current_conversation_id: str | None = None
        # Lazily-resolved chat model; None means resolve from llm_provider.
        self._llm: BaseChatModel | None = None
        # RAG components — injected after construction, shared via clone()
        self._rag_store_manager: Any | None = None
        self._rag_embedding_registry: Any | None = None
        # Checkpoint saver — shared by reference via clone(); None disables
        # checkpointing and keeps pre-checkpoint behaviour exactly.
        self._checkpointer = checkpointer
        # Context compression (design doc 四.5): strategy/threshold from
        # config.context, fallback window from config.llm.context_window.
        # Imported lazily: module-level import would create a cycle
        # (config.models → channels → wechat_channel → agent.graph).
        if context_config is None:
            from thumbelina.config.models import ContextConfig

            context_config = ContextConfig()
        self._context_config = context_config
        self._context_window_tokens = context_window_tokens
        compress_config = self._context_config.compress
        try:
            self._compressor = create_compressor(
                compress_config.strategy,
                recent_turns=compress_config.recent_turns,
                llm_provider=self.llm_provider,
            )
        except ValueError:
            logger.warning(
                "Unknown compression strategy %r; falling back to sliding_window",
                compress_config.strategy,
            )
            self._compressor = SlidingWindowCompressor()

        # Build the combined tools list
        self.tools: list[BaseTool] = list(tools) if tools else []
        if self.subagent_manager is not None:
            self.tools.extend(_make_subagent_tools(self.subagent_manager))
        if self.scheduler is not None:
            self.tools.extend(_make_scheduler_tools(self.scheduler))
        if self.composition_engine is not None:
            self.tools.extend(_make_composition_tools(self.composition_engine))
        # clone() re-passes the combined list, so the extends above re-add
        # generated tools; dedupe or the LLM API rejects duplicate names.
        seen: set[str] = set()
        unique_tools: list[BaseTool] = []
        for item in self.tools:
            if item.name not in seen:
                seen.add(item.name)
                unique_tools.append(item)
        self.tools = unique_tools

        self.graph = self._build_graph()

    def swap_provider(self, new_provider: LLMProvider) -> None:
        """Hot-swap the LLM provider at runtime.

        Updates both ``llm_provider`` and the underlying LangChain
        ``chat_model`` so that subsequent graph invocations use the new
        model.  The compiled graph does **not** need to be rebuilt.
        Summarizing compressors hold their own provider reference, so it is
        re-pointed here as well (pure-deletion strategies have none).
        """
        self.llm_provider = new_provider
        self._llm = new_provider.chat_model
        compressor = getattr(self, "_compressor", None)
        if compressor is not None and hasattr(compressor, "llm_provider"):
            compressor.llm_provider = new_provider

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
        """Build and compile the LangGraph agent graph.

        Structure: entry → compress → agent (→ tools → agent …). The
        compress node runs once per turn, ahead of the LLM call, and trims
        the checkpoint history only when usage nears the context window;
        below the threshold it passes the state through untouched so the
        pure-append prefix (provider prefix caching) is preserved.
        """
        graph = StateGraph(AgentState)
        graph.add_node("compress", self._compress_node)
        graph.add_node("agent", self._call_model_node)
        graph.add_edge("compress", "agent")

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

        graph.set_entry_point("compress")
        return graph.compile(checkpointer=self._checkpointer)

    def _resolve_context_window(self, config: RunnableConfig | None) -> int | None:
        """Resolve the context window for the compress node.

        Priority: ``configurable["context_window_tokens"]`` carried by the
        run config (resolved per conversation by the caller: session
        endpoint → globally active endpoint → default), then the
        agent-level fallback (``config.llm.context_window``).
        """
        if config:
            configurable = config.get("configurable") or {}
            value = configurable.get("context_window_tokens")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return self._context_window_tokens

    async def _compress_node(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """Compress the checkpoint history when usage nears the window.

        Runs once per turn ahead of the LLM call (entry → compress →
        agent). Usage is estimated with the shared RAG token estimator;
        below ``window × context.compress.threshold`` the state passes
        through with zero changes. When triggered, the configured strategy
        compresses towards the 50% low watermark; a failing strategy (e.g.
        the T6 placeholders) degrades to pure deletion so compression never
        blocks a conversation. The compressed sequence is written back to
        the state, so the checkpointer fixes it for subsequent turns.
        """
        messages = state["messages"]
        if not messages:
            return {}
        window = self._resolve_context_window(config)
        if window is None:
            return {}

        compress_config = self._context_config.compress
        used = estimate_messages_tokens(messages)
        if used < window * compress_config.threshold:
            return {}

        logger.info(
            "Context usage %d tokens reached %.0f%% of window %d; compressing with %r",
            used,
            compress_config.threshold * 100,
            window,
            getattr(self._compressor, "name", self._compressor.__class__.__name__),
        )
        try:
            compressed = await self._compressor.compress(messages, window)
        except Exception:
            logger.warning(
                "Compression strategy %r failed; falling back to sliding_window",
                getattr(self._compressor, "name", self._compressor.__class__.__name__),
                exc_info=True,
            )
            try:
                compressed = await SlidingWindowCompressor().compress(messages, window)
            except Exception:
                logger.warning(
                    "Fallback compression failed; keeping state unchanged", exc_info=True
                )
                return {}

        # Anthropic boundary: a promoted leading assistant turn may carry
        # thinking blocks that can no longer be replayed (HTTP 400).
        compressed = strip_first_assistant_thinking(list(compressed))
        update = _messages_state_update(messages, compressed)
        if update:
            stats = compression_stats(messages, compressed)
            logger.info(
                "Context compressed: %d -> %d estimated tokens (%d message(s) kept)",
                stats.tokens_before,
                stats.tokens_after,
                len(compressed),
            )
        return update

    async def _call_model_node(self, state: AgentState) -> dict[str, list[AIMessage]]:
        """Node wrapper for calling the LLM."""
        model = self.llm
        if self.tools:
            try:
                model = model.bind_tools(self.tools)
            except NotImplementedError:
                logger.debug("Model does not support tool binding; tools disabled")
        return await call_model(state, model, timeout=self.request_timeout)

    async def _tool_node_node(self, state: AgentState) -> dict[str, list[Any]]:
        """Node wrapper for executing tools."""
        return await tool_node(state, self.tools)

    def _run_config(self, context_window_tokens: int | None = None) -> RunnableConfig | None:
        """Build the LangGraph run config for checkpointing.

        Returns ``None`` when no checkpointer is attached and no context
        window was supplied so the invocation behaves exactly as before
        checkpointing existed. With a checkpointer, LangGraph requires a
        ``thread_id`` in the config (it raises ``ValueError`` otherwise):
        the active conversation id is used as the thread id so context
        accumulates across turns of the same conversation; paths without a
        conversation get an ephemeral id so they remain stateless and
        error-free.

        ``context_window_tokens`` is the per-conversation context window
        resolved by the caller (session endpoint → globally active endpoint
        → ``llm.context_window``); it is carried in ``configurable`` so the
        compress node can read it from the run config.
        """
        if self._checkpointer is None and context_window_tokens is None:
            return None
        configurable: dict[str, Any] = {}
        if self._checkpointer is not None:
            thread_id = self.current_conversation_id or str(uuid4())
            configurable["thread_id"] = thread_id
        if context_window_tokens is not None:
            configurable["context_window_tokens"] = context_window_tokens
        return {"configurable": configurable}

    async def _is_first_turn(self, config: RunnableConfig) -> bool:
        """Return ``True`` when the checkpoint thread holds no messages yet.

        Session-level context (role prompt, user profile) is persisted by the
        checkpointer, so it may only be injected on the thread's first turn;
        re-injecting it every turn would accumulate duplicate copies in the
        persisted state.
        """
        try:
            snapshot = await self.graph.aget_state(config)
        except Exception:
            logger.warning("Checkpoint state lookup failed; treating turn as first", exc_info=True)
            return True
        if snapshot is None:
            return True
        return not snapshot.values.get("messages")

    async def _build_initial_messages(
        self, user_input: str, config: RunnableConfig | None
    ) -> list[Any]:
        """Build the input message sequence for one turn.

        With a checkpointer the persisted state already contains earlier
        turns, so the sequence is kept pure-append (protects provider-side
        prefix caching):

        - The role prompt and the user profile are session/user-level and
          are injected only on the thread's first turn (empty checkpoint),
          in that order, ahead of the conversation history. Subsequent turns
          restore them from the checkpoint; re-injecting would accumulate
          duplicates in the persisted state.
        - Ephemeral context (RAG chunks, skill instructions) is injected
          every turn and intentionally left in the state — no per-turn
          cleanup; it is removed only by the compression stage once usage
          nears the context window.

        Without a checkpointer the state never persists, so every turn
        carries the role prompt and profile exactly as before checkpointing.
        """
        first_turn = True
        if self._checkpointer is not None and config is not None:
            first_turn = await self._is_first_turn(config)

        messages: list[Any] = []
        if first_turn:
            if self.role_prompt:
                messages.append(SystemMessage(content=self.role_prompt))
            user_context = await self._get_user_context()
            if user_context:
                messages.append(SystemMessage(content=user_context))

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
            messages.append(SystemMessage(content=rag_context))

        skill_context = await self._get_skill_context(user_input)
        if skill_context:
            messages.append(SystemMessage(content=skill_context))
        messages.append(HumanMessage(content=user_input))
        return messages

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

    async def _persist_message(
        self, role: str, content: str, reasoning_content: str | None = None
    ) -> None:
        """Persist a message to memory if enabled."""
        if self.memory_manager and self.current_conversation_id:
            try:
                await self.memory_manager.add_message(
                    conversation_id=self.current_conversation_id,
                    role=role,
                    content=content,
                    reasoning_content=reasoning_content,
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
            # 在工作线程中获取模型实例，避免阻塞事件循环
            # （若启动后的后台预加载仍在进行，会等待其完成并复用缓存实例）
            embedder = await asyncio.to_thread(self._rag_embedding_registry.create)

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
            role=self.role,
            checkpointer=self._checkpointer,
            context_config=self._context_config,
            context_window_tokens=self._context_window_tokens,
        )
        cloned._rag_store_manager = self._rag_store_manager
        cloned._rag_embedding_registry = self._rag_embedding_registry
        return cloned

    async def run(self, user_input: str, context_window_tokens: int | None = None) -> str:
        """Run the agent with user input and return the response.

        Parameters
        ----------
        user_input:
            The user's message.
        context_window_tokens:
            Optional per-conversation context window (in tokens) resolved by
            the caller (session endpoint → globally active endpoint →
            ``llm.context_window``). It is carried in the run config for the
            compress node.
        """
        await self._ensure_conversation()
        await self._persist_message("user", user_input)

        config = self._run_config(context_window_tokens)
        initial_messages = await self._build_initial_messages(user_input, config)

        initial_state: AgentState = {"messages": initial_messages}
        result = await self.graph.ainvoke(initial_state, config=config)

        last_message = result["messages"][-1]
        response = str(last_message.content)

        await self._persist_message("assistant", response)
        # Auto-name the conversation in the background so the reply is not delayed.
        asyncio.create_task(self._maybe_auto_name())

        return response

    async def stream(
        self, user_input: str, context_window_tokens: int | None = None
    ) -> AsyncGenerator[dict[str, str], None]:
        """Stream the agent's response as typed events.

        Yields dicts of the form ``{"type": "content" | "reasoning",
        "text": str}`` so callers can render the model's thinking process
        separately from the visible answer.

        ``context_window_tokens`` is the optional per-conversation context
        window (in tokens) resolved by the caller; it is carried in the run
        config for the compress node.
        """
        await self._ensure_conversation()
        await self._persist_message("user", user_input)

        config = self._run_config(context_window_tokens)
        initial_messages = await self._build_initial_messages(user_input, config)

        initial_state: AgentState = {"messages": initial_messages}
        full_response = ""
        full_reasoning = ""
        pending_content = ""
        pending_reasoning = ""
        # Batch tokens before yielding: send when buffer reaches size OR timeout
        batch_size = 30  # characters per batch
        flush_interval = 0.05  # seconds (50ms) - flush even if batch size not reached
        last_flush = asyncio.get_event_loop().time()

        async for event in self.graph.astream(initial_state, stream_mode="messages", config=config):
            # event is a tuple: (message_chunk, metadata)
            if not isinstance(event, tuple) or len(event) < 1:
                continue

            message_chunk = event[0]
            metadata = event[1] if len(event) > 1 and isinstance(event[1], dict) else {}
            # State maintenance from the compress node (deletions, stripped
            # assistant re-emissions) is not part of the reply.
            if metadata.get("langgraph_node") == "compress":
                continue

            # Accept both streaming chunks (AIMessageChunk) and complete
            # responses (AIMessage). The latter occurs with non-streaming
            # LLM providers, where astream(stream_mode="messages") emits a
            # single AIMessage instead of per-token chunks.
            if not isinstance(message_chunk, AIMessage) or getattr(
                message_chunk, "tool_calls", None
            ):
                continue

            content, reasoning = _extract_chunk_parts(message_chunk)
            if content:
                full_response += content
                pending_content += content
            if reasoning:
                full_reasoning += reasoning
                pending_reasoning += reasoning
            if not content and not reasoning:
                continue

            # Yield when buffer reaches batch size or time interval
            now = asyncio.get_event_loop().time()
            due = (now - last_flush) >= flush_interval
            if pending_reasoning and (len(pending_reasoning) >= batch_size or due):
                yield {"type": "reasoning", "text": pending_reasoning}
                pending_reasoning = ""
                last_flush = now
            if pending_content and (len(pending_content) >= batch_size or due):
                yield {"type": "content", "text": pending_content}
                pending_content = ""
                last_flush = now

        # Yield any remaining content
        if pending_reasoning:
            yield {"type": "reasoning", "text": pending_reasoning}
        if pending_content:
            yield {"type": "content", "text": pending_content}

        if full_response:
            await self._persist_message(
                "assistant", full_response, reasoning_content=full_reasoning or None
            )
            # Auto-name the conversation in the background so streaming is not delayed.
            asyncio.create_task(self._maybe_auto_name())
