"""协作工具:委托/查询其他 agent(spec §4.3)。

从 ``agent/graph.py`` 的 ``_make_subagent_tools`` 迁入,函数体逐字保持,
对外 name/参数名/返回文案不变;统一继承
:class:`~thumbelina.tools.base.ThumbelinaBaseTool` 生命周期。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory


class _CreateSubagentArgs(BaseModel):
    task: str = Field(..., description="Task to delegate to the subagent.")


class _ListSubagentsArgs(BaseModel):
    pass


class CollaborationTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.COLLABORATION


class CreateSubagentTool(CollaborationTool):
    name: str = "create_subagent"
    description: str = "Create and run a subagent to execute a task asynchronously."
    args_schema: type[BaseModel] = _CreateSubagentArgs
    manager: Any = None

    async def _execute(self, task: str) -> str:
        try:
            agent = await self.manager.create_agent(task)
            await self.manager.run_agent(agent.id)
            return (
                f"Subagent created with ID {agent.id}. Task: {task}. Status: {agent.status.value}"
            )
        except RuntimeError as exc:
            return f"Failed to create subagent: {exc}"


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
