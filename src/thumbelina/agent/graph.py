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
    """当 *subset* 以相同顺序出现在 *full* 中时返回 ``True``。"""
    iterator = iter(full)
    return all(any(item == candidate for item in iterator) for candidate in subset)


def _messages_state_update(
    current: Sequence[BaseMessage], compressed: Sequence[BaseMessage]
) -> dict[str, list[Any]]:
    """把压缩后的序列转换为 ``add_messages`` 更新。

    纯删除（每条保留的消息都沿用原对象 —— 从而保留 id 与顺序）只发出
    ``RemoveMessage`` 条目，外加任何被就地修改的保留消息（例如
    thinking 块被剥离）。任何结构重组（例如摘要替换）都会替换整个
    序列：先移除所有当前消息，再重新追加压缩后的序列。复用当前 id
    的消息会以全新 id 的副本重新追加，因为 ``add_messages`` 会把已移除
    的 id 重新插回其原始位置 —— 这会破坏压缩后的顺序。
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
        # 重新发出发生变化的保留消息，让 add_messages 就地更新它们
        # （相同的 id 使其保持在原位置）。
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
        可选的 LangGraph 检查点存储器，在轮次之间持久化图状态
        （可变的 LLM 上下文工作区），以当前会话 id 为键。克隆实例共享
        同一个 saver 实例，因此绝不会打开重复连接。``None`` 禁用检查点，
        并完全保留检查点出现之前的行为。
    context_config:
        上下文/压缩设置（``config.context``）。默认使用
        :class:`ContextConfig` 的默认值：策略 ``summary_recent``、
        触发阈值 0.8、保留 6 轮。
    context_window_tokens:
        压缩节点在运行未携带
        ``configurable["context_window_tokens"]``（例如直接调用图的
        channel 路径）时使用的兜底上下文窗口（单位为 token，
        来自 ``config.llm.context_window``）。
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
        # 检查点存储器 —— 经 clone() 按引用共享；None 禁用检查点，
        # 并完全保留检查点出现之前的行为。
        self._checkpointer = checkpointer
        # 上下文压缩（设计文档 四.5）：策略/阈值来自
        # config.context，兜底窗口来自 config.llm.context_window。
        # 延迟导入：模块级导入会形成循环
        # （config.models → channels → wechat_channel → agent.graph）。
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
        摘要类压缩器持有各自的 provider 引用，因此这里也会一并重新
        指向（纯删除策略没有该引用）。
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
        """构建并编译 LangGraph agent 图。

        结构：entry → compress → agent (→ tools → agent …)。压缩节点
        每轮运行一次，先于 LLM 调用，仅当用量接近上下文窗口时裁剪
        检查点历史；低于阈值时原样放行状态，从而保留纯追加前缀
        （provider 前缀缓存）。
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
        """解析压缩节点使用的上下文窗口。

        优先级：运行配置携带的
        ``configurable["context_window_tokens"]``（由调用方按会话解析：
        会话端点 → 全局活跃端点 → 默认值），其次是 agent 级兜底
        （``config.llm.context_window``）。
        """
        if config:
            configurable = config.get("configurable") or {}
            value = configurable.get("context_window_tokens")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return self._context_window_tokens

    async def _compress_node(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """当用量接近窗口时压缩检查点历史。

        每轮在 LLM 调用之前运行一次（entry → compress → agent）。
        用量通过共享的 RAG token 估算器估算；低于
        ``window × context.compress.threshold`` 时状态零改动放行。
        触发后，配置的策略向 50% 低水位压缩；失败的策略（例如 T6
        占位实现）降级为纯删除，压缩永远不会阻塞会话。压缩后的序列
        写回状态，因此检查点存储器会把它固定下来供后续轮次使用。
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

        # Anthropic 边界：被提升到头部的前导 assistant 轮次可能携带
        # 无法再重放的 thinking 块（HTTP 400）。
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
        """构建用于检查点的 LangGraph 运行配置。

        未挂检查点且未提供上下文窗口时返回 ``None``，使调用行为与
        检查点出现之前完全一致。挂有检查点时，LangGraph 要求配置中
        带有 ``thread_id``（否则抛出 ``ValueError``）：活跃会话 id 用作
        thread id，使上下文在同一会话的各轮之间累积；没有会话的路径
        获得临时 id，从而保持无状态且不报错。

        ``context_window_tokens`` 是调用方按会话解析的上下文窗口
        （会话端点 → 全局活跃端点 → ``llm.context_window``）；它被放入
        ``configurable``，以便压缩节点从运行配置中读取。
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
        """当检查点线程尚无任何消息时返回 ``True``。

        会话级上下文（角色提示词、用户画像）由检查点存储器持久化，
        因此只能在线程的首轮注入；每轮都重新注入会在持久化状态中
        累积重复副本。
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
        """构建单轮的输入消息序列。

        挂有检查点时，持久化状态已包含更早的轮次，因此序列保持
        纯追加（保护 provider 侧的前缀缓存）：

        - 角色提示词与用户画像是会话/用户级的，仅在线程的首轮
          （空检查点）按此顺序注入，位于对话历史之前。后续轮次从
          检查点恢复它们；重复注入会在持久化状态中累积副本。
        - 临时上下文（RAG 片段、skill 指令）每轮注入，并且有意保留
          在状态中 —— 不做逐轮清理；仅当用量接近上下文窗口时才由
          压缩阶段移除。

        没有检查点时状态从不持久化，因此每一轮都携带角色提示词与
        画像，与检查点出现之前完全一致。
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

        # 若会话绑定了知识库，则注入 RAG 上下文
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
            用户的消息。
        context_window_tokens:
            可选的按会话上下文窗口（单位为 token），由调用方解析
            （会话端点 → 全局活跃端点 → ``llm.context_window``）。
            它被放入运行配置中供压缩节点使用。
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

        ``context_window_tokens`` 是可选的按会话上下文窗口（单位为
        token），由调用方解析；它被放入运行配置中供压缩节点使用。
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
            # 来自压缩节点的状态维护（删除、被剥离的 assistant 重新
            # 发出）不属于回复内容。
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
