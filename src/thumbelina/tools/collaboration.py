"""协作工具:委托/查询其他 agent(spec §4.3)。

从 ``agent/graph.py`` 的 ``_make_subagent_tools`` 迁入,函数体逐字保持,
对外 name/参数名/返回文案不变;统一继承
:class:`~thumbelina.tools.base.ThumbelinaBaseTool` 生命周期。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.subagents.base import SubagentStatus
from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory

logger = logging.getLogger(__name__)

# 单次 create_subagent 工具调用的最长等待时间(秒)。
# 子 Agent 内部单次 LLM chat 可能耗时数十秒;这里给到 5 分钟覆盖大多数任务,
# 超过则视为超时,把当前 status 返回给主 Agent 让它继续决策。
SUBAGENT_TOOL_TIMEOUT_SECONDS = 300.0

# 等待循环的 tick 间隔;轮询用以保持子 Agent 生命周期事件的实时推送路径不变。
SUBAGENT_TOOL_POLL_INTERVAL = 0.1


class _CreateSubagentArgs(BaseModel):
    task: str = Field(..., description="Task to delegate to the subagent.")


class _ListSubagentsArgs(BaseModel):
    pass


class CollaborationTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.COLLABORATION


class CreateSubagentTool(CollaborationTool):
    name: str = "create_subagent"
    description: str = (
        "Create and run a subagent to execute a task synchronously. "
        "Returns the subagent's final result or error once it completes."
    )
    args_schema: type[BaseModel] = _CreateSubagentArgs
    manager: Any = None

    async def _execute(self, task: str) -> str:
        try:
            agent = await self.manager.create_agent(task)
        except RuntimeError as exc:
            return f"Failed to create subagent: {exc}"

        try:
            await self.manager.run_agent(agent.id)
        except ValueError as exc:
            return f"Failed to run subagent {agent.id}: {exc}"

        # 同步等待子 Agent 走到终态。
        # 之所以必须等待:主 Agent 工具调用拿到 result/error 后才能做汇总;
        # 若提前返回 PENDING,主 Agent 会基于占位信息回答用户,造成体验断层。
        terminal_statuses = (
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.CANCELLED,
        )
        deadline = asyncio.get_running_loop().time() + SUBAGENT_TOOL_TIMEOUT_SECONDS
        try:
            while True:
                current = await self.manager.get_agent(agent.id)
                if current is None:
                    return f"Subagent {agent.id} disappeared from manager before completion."
                if current.status in terminal_statuses:
                    return self._format_terminal_result(agent.id, task, current)
                if asyncio.get_running_loop().time() >= deadline:
                    logger.warning(
                        "Subagent %s exceeded tool timeout %.1fs; returning current status",
                        agent.id,
                        SUBAGENT_TOOL_TIMEOUT_SECONDS,
                    )
                    return (
                        f"Subagent {agent.id} still running after "
                        f"{SUBAGENT_TOOL_TIMEOUT_SECONDS:.0f}s (status={current.status.value}). "
                        "Use list_subagents to re-check later."
                    )
                await asyncio.sleep(SUBAGENT_TOOL_POLL_INTERVAL)
        except asyncio.CancelledError:
            # 主 Agent 收到 cancel/stop 时,工具协程被中断;尽量把子 Agent 也标取消,
            # 避免孤儿后台任务继续占用 LLM 配额。
            try:
                await self.manager.cancel_agent(agent.id)
            except Exception:
                logger.debug("cancel_agent failed during tool cancel", exc_info=True)
            raise

    @staticmethod
    def _format_terminal_result(agent_id: str, task: str, agent: Any) -> str:
        """把子 Agent 的终态打包成主 Agent 易于消费的字符串。"""
        if agent.status == SubagentStatus.COMPLETED:
            return f"Subagent {agent_id} completed.\nTask: {task}\nResult:\n{agent.result}"
        if agent.status == SubagentStatus.FAILED:
            return (
                f"Subagent {agent_id} failed.\n"
                f"Task: {task}\n"
                f"Error: {agent.error or 'unknown error'}"
            )
        if agent.status == SubagentStatus.CANCELLED:
            return f"Subagent {agent_id} was cancelled before completion.\nTask: {task}"
        # 不应到达:仅在调用方传入非终态时被命中。
        return f"Subagent {agent_id} status: {agent.status.value}"


class ListSubagentsTool(CollaborationTool):
    name: str = "list_subagents"
    description: str = "List all subagents and their current status."
    args_schema: type[BaseModel] = _ListSubagentsArgs
    manager: Any = None

    async def _execute(self) -> str:
        agents = await self.manager.list_agents()
        return self.report_status(agents)

    @staticmethod
    def report_status(agents: list[Any]) -> str:
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


def make_collaboration_tools(manager: Any) -> list[BaseTool]:
    """返回封装 ``SubagentManager`` 的协作工具对(迁移自 ``_make_subagent_tools``)。"""
    return [CreateSubagentTool(manager=manager), ListSubagentsTool(manager=manager)]
