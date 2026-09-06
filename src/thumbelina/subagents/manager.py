"""Subagent manager for creating and managing subagents."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from thumbelina.llm.base import LLMProvider
from thumbelina.subagents.base import Subagent, SubagentEvent, SubagentStatus

logger = logging.getLogger(__name__)

# 工具循环模式（set_tools 注入工具后启用）的系统提示。
_SUBAGENT_SYSTEM_WITH_TOOLS = (
    "You are a subagent executing a specific task. You have access to "
    "read-only perception tools (read/search/list/fetch). Use them to "
    "verify facts before reporting; never fabricate file contents or "
    "code references. Work autonomously within a bounded number of "
    "rounds — budget them carefully and produce your final answer "
    "before running out — then return only the result as plain text."
)

# 无工具降级模式（未注入工具 / 模型不支持工具绑定）的系统提示。
# 必须明确声明无工具能力：否则模型会把工具调用写成 <read_file> 之类的
# 伪语法文本（2026-09-06 事故），runner 误把该文本当结果返回。
_SUBAGENT_SYSTEM_NO_TOOLS = (
    "You are a subagent executing a specific task. You have NO tool "
    "access in this mode: you cannot read files, run commands, or "
    "browse. Answer from the task description alone and state "
    "explicitly what could not be verified. Never emit fake tool-call "
    "syntax such as <read_file> — it will not be executed."
)

# 工具循环轮次耗尽后的强制收束指令（作为 user 消息追加在完整循环
# 历史之后；不带工具绑定调用，模型只能基于已有证据输出文本结论）。
_WRAP_UP_INSTRUCTION = (
    "You have reached the tool-round limit. Do not attempt any further "
    "tool calls. Based ONLY on the evidence you have gathered above, "
    "produce your final answer to the original task now, as plain text."
)

# 无工具降级模式下检测"模型输出了伪工具调用语法"——出现即视为任务未真正
# 执行（模型以为自己在调工具），标记 FAILED 而非把垃圾文本当结果。
_PSEUDO_TOOL_TAG_RE = re.compile(
    r"</?(?:read_file|write_file|edit_file|search_files|list_directory|run_shell|"
    r"fetch_url|web_search|create_subagent|list_subagents|search_memory|read_memory|"
    r"remember|notify)\s*>"
    r"|<(?:path|command|pattern|query|file_path)\s*>",
    re.IGNORECASE,
)

# 工具循环的默认轮次上限与单工具超时。24 轮:深度评审类任务(读文档 +
# 逐一核对代码引用)实测 12 轮不够用,会耗尽轮次而拿不出结论。
SUBAGENT_MAX_ROUNDS = 24
SUBAGENT_TOOL_TIMEOUT_SECONDS = 300.0


def _looks_like_pseudo_tool_text(text: str) -> bool:
    """判断一段文本是否形如未被执行的伪工具调用（XML 风格标签）。"""
    return bool(_PSEUDO_TOOL_TAG_RE.search(text))


def _message_text(message: object) -> str:
    """提取 LLM 消息的文本内容（content 可能为 str 或分块列表）。"""
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


SubagentListener = Callable[[SubagentEvent], Awaitable[None]]


def _iso(dt: datetime | None) -> str | None:
    """Format a datetime as ISO-8601 with timezone, ``None`` for unset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


class SubagentManager:
    """Manager for creating and managing subagents.

    Parameters
    ----------
    llm_provider:
        The LLM provider for subagent execution.
    max_agents:
        Maximum number of concurrent subagents.
    max_rounds:
        工具循环模式的轮次上限，防止失控循环。
    tool_timeout:
        工具循环模式下单工具执行超时（秒），``None`` = 不限时。
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        max_agents: int = 5,
        max_rounds: int = SUBAGENT_MAX_ROUNDS,
        tool_timeout: float | None = SUBAGENT_TOOL_TIMEOUT_SECONDS,
    ) -> None:
        self.llm_provider = llm_provider
        self.max_agents = max_agents
        self.max_rounds = max_rounds
        self.tool_timeout = tool_timeout
        self._agents: dict[str, Subagent] = {}
        # 工具循环模式的工具集（默认为空 = 无工具降级模式）。通过
        # ``set_tools`` 在应用装配时注入只读感知类工具。
        self._tools: list[BaseTool] = []
        # Listeners receive a SubagentEvent at every status transition.
        # They may be sync or async coroutines; async listeners are scheduled
        # as tasks so a slow subscriber cannot block the manager's loop.
        self._listeners: list[SubagentListener] = []

    def set_tools(self, tools: Sequence[BaseTool]) -> None:
        """注入子 agent 可用的工具集（只读感知类）。

        注入后子 agent 以"工具循环"模式运行：模型可多轮调用工具核实
        事实再产出结论。传空列表则退回无工具的单轮 chat 模式。
        """
        self._tools = list(tools)

    def add_listener(self, fn: SubagentListener) -> Callable[[], None]:
        """Register a lifecycle listener. Returns an unsubscribe callable."""
        self._listeners.append(fn)

        def _unsubscribe() -> None:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

        return _unsubscribe

    async def _emit(
        self,
        agent: Subagent,
        event_type: SubagentEvent.__dataclass_fields__[type].type,  # type: ignore[attr-defined]
    ) -> None:
        """Notify all listeners of a subagent status transition.

        Listener exceptions are swallowed at the dispatch boundary so a
        single misbehaving subscriber cannot break the manager.
        """
        event = SubagentEvent(
            type=event_type,
            id=agent.id,
            task=agent.task,
            status=agent.status,
            result=agent.result,
            error=agent.error,
            started_at=_iso(agent.started_at),
            finished_at=_iso(agent.finished_at),
            conversation_id=agent.conversation_id,
        )
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    # Fire-and-forget so we never block the manager's loop
                    # or the calling tool coroutine on a slow subscriber.
                    asyncio.create_task(result)
            except Exception:
                logger.warning("Subagent listener raised", exc_info=True)

    async def create_agent(self, task: str, conversation_id: str | None = None) -> Subagent:
        """Create a new subagent.

        Parameters
        ----------
        task:
            Description of the task for the agent to execute.
        conversation_id:
            发起会话 id（可选）：随生命周期事件广播，供监听方按会话路由。

        Returns
        -------
        Subagent
            The created subagent.

        Raises
        ------
        RuntimeError
            If maximum number of agents is reached.
        """
        if len(self._agents) >= self.max_agents:
            raise RuntimeError(f"Maximum number of agents ({self.max_agents}) reached")

        agent = Subagent(task=task, conversation_id=conversation_id)
        self._agents[agent.id] = agent
        return agent

    async def run_agent(self, agent_id: str) -> None:
        """Start executing a subagent asynchronously.

        The agent executes the task via the LLM provider in a background
        coroutine.  Status transitions: PENDING → RUNNING → COMPLETED/FAILED.

        Parameters
        ----------
        agent_id:
            ID of the agent to run.

        Raises
        ------
        ValueError
            If the agent does not exist or is not in PENDING state.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id!r}")
        if agent.status != SubagentStatus.PENDING:
            raise ValueError(
                f"Agent {agent_id!r} cannot be run: current status is {agent.status.value}"
            )

        agent.status = SubagentStatus.RUNNING
        agent.started_at = datetime.now(UTC)
        asyncio.create_task(self._execute(agent))

    async def _execute(self, agent: Subagent) -> None:
        """Internal: execute the agent's task and store the result.

        注入了工具时走"工具循环"模式（bind_tools + 复用主 agent 的
        ``tool_node`` 执行工具，轮次封顶）；否则退回无工具的单轮 chat
        模式，并对伪工具语法文本做失败校验。工作区上下文（ContextVar）
        由 ``create_task`` 自动继承自派发它的会话上下文，工具因此与主
        agent 使用同一工作区边界。
        """
        await self._emit(agent, "subagent.started")
        try:
            if self._tools:
                agent.result = await self._run_tool_loop(agent.task)
            else:
                agent.result = await self._run_single_shot(agent.task)
            agent.status = SubagentStatus.COMPLETED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.completed")
        except asyncio.CancelledError:
            agent.status = SubagentStatus.CANCELLED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.cancelled")
            raise
        except Exception as exc:
            logger.warning("Subagent %s failed: %s", agent.id, exc)
            agent.error = str(exc)
            agent.status = SubagentStatus.FAILED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.failed")

    async def _run_tool_loop(self, task: str) -> str:
        """工具循环模式：绑定只读工具，多轮"调用→执行→回填"直到产出结论。

        - 模型不支持 ``bind_tools`` 时自动退回无工具单轮模式。
        - 每个工具调用复用 :func:`thumbelina.agent.nodes.tool_node`，与主
          agent 保持一致的错误文案与 per-tool 超时语义。
        - 达到轮次上限时返回已有文本并明确标注"可能不完整"，绝不静默截断。
        """
        # 惰性导入避免包初始化环（agent 包初始化会加载协作工具链）。
        from langchain_core.messages import BaseMessage

        from thumbelina.agent.nodes import tool_node

        try:
            model = self.llm_provider.chat_model.bind_tools(self._tools)
        except Exception:
            logger.warning(
                "Subagent chat model %r does not support tool binding; "
                "falling back to single-shot mode",
                type(self.llm_provider).__name__,
            )
            return await self._run_single_shot(task)

        messages: list[BaseMessage] = [
            SystemMessage(content=_SUBAGENT_SYSTEM_WITH_TOOLS),
            HumanMessage(content=task),
        ]
        last_text = ""
        for _round in range(self.max_rounds):
            response = await model.ainvoke(messages)
            messages.append(response)
            last_text = _message_text(response)
            if not getattr(response, "tool_calls", None):
                return last_text
            executed = await tool_node(
                {"messages": messages}, self._tools, timeout=self.tool_timeout
            )
            messages.extend(executed["messages"])
        # 轮次耗尽:用一次无工具调用强制收束。循环里模型可能全程只发工具
        # 调用(last_text 为空),只返回提示语对主 agent 毫无价值;带上完整
        # 循环历史让模型基于已 gathered 的证据直接产出结论。
        try:
            conclusion = await self.llm_provider.chat_model.ainvoke(
                [*messages, HumanMessage(content=_WRAP_UP_INSTRUCTION)]
            )
            last_text = _message_text(conclusion) or last_text
        except Exception:
            logger.warning("Subagent wrap-up call failed; returning note only", exc_info=True)
        return (
            f"(Subagent reached its {self.max_rounds}-round tool limit; "
            f"result may be incomplete.)\n\n{last_text}"
        )

    async def _run_single_shot(self, task: str) -> str:
        """无工具单轮模式：一次 chat 调用，且拒绝伪工具语法文本。"""
        messages = [
            {"role": "system", "content": _SUBAGENT_SYSTEM_NO_TOOLS},
            {"role": "user", "content": task},
        ]
        result = await self.llm_provider.chat(messages)
        if _looks_like_pseudo_tool_text(result):
            # 模型把工具调用写成了文本（以为自己在调工具）——任务实际
            # 未执行。标记 FAILED 让主 agent 知道结果不可信,而不是把
            # 垃圾文本当结论汇总给用户。
            raise ValueError(
                "subagent has no tool access and the model emitted pseudo "
                "tool-call syntax instead of a result; task was not actually "
                "executed"
            )
        return result

    async def get_agent(self, agent_id: str) -> Subagent | None:
        """Get a subagent by ID."""
        return self._agents.get(agent_id)

    async def list_agents(self) -> list[Subagent]:
        """List all subagents."""
        return list(self._agents.values())

    async def cancel_agent(self, agent_id: str) -> bool:
        """Cancel a subagent.

        Parameters
        ----------
        agent_id:
            ID of the agent to cancel.

        Returns
        -------
        bool
            True if cancelled, False if not found.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return False

        # Only flip status if the agent is still running; terminal states
        # are preserved so we don't lie about a completed run. The asyncio
        # task running the LLM call is not currently tracked, so we don't
        # attempt to interrupt it here — the cancel_event-style behaviour
        # belongs to a future enhancement.
        if agent.status in (SubagentStatus.PENDING, SubagentStatus.RUNNING):
            agent.status = SubagentStatus.CANCELLED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.cancelled")
        return True
