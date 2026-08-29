"""事件触发工具:注册/查询未来时间与条件(spec §4.3)。

从 ``agent/graph.py`` 的 ``_make_scheduler_tools`` 迁入,函数体逐字保持,
对外 name/参数名/返回文案不变;统一继承
:class:`~thumbelina.tools.base.ThumbelinaBaseTool` 生命周期。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.scheduler.scheduler import ScheduledTask
from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory


class _ScheduleTaskArgs(BaseModel):
    description: str = Field(..., description="Description of the task to schedule.")
    time_expression: str = Field(..., description="Natural-language time expression.")


class _ListScheduledTasksArgs(BaseModel):
    pass


class EventTriggerTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.EVENT_TRIGGER
    time_parser: Any = None

    def parse_trigger(self, text: str) -> datetime | None:
        return self.time_parser.parse(text) if self.time_parser else None


class ScheduleTaskTool(EventTriggerTool):
    name: str = "schedule_task"
    description: str = "Schedule a task for a future time."
    args_schema: type[BaseModel] = _ScheduleTaskArgs
    scheduler: Any = None

    async def _execute(self, description: str, time_expression: str) -> str:
        parsed = self.parse_trigger(time_expression)
        if parsed is None:
            return f"Could not parse time expression: {time_expression}"
        task = ScheduledTask(description=description, scheduled_time=parsed)
        await self.scheduler.add_task(task)
        return (
            f"Task scheduled with ID {task.id}. Description: {description}. "
            f"Scheduled for: {parsed.isoformat()}"
        )


class ListScheduledTasksTool(EventTriggerTool):
    name: str = "list_scheduled_tasks"
    description: str = "List all scheduled tasks and their status."
    args_schema: type[BaseModel] = _ListScheduledTasksArgs
    scheduler: Any = None

    async def _execute(self) -> str:
        tasks = await self.scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks found."
        return "\n".join(
            f"- ID: {t.id}, Description: {t.description}, "
            f"Scheduled: {t.scheduled_time.isoformat()}, Status: {t.status.value}"
            for t in tasks
        )


def make_event_tools(scheduler: Any, time_parser: Any) -> list[BaseTool]:
    """返回封装 ``TaskScheduler`` 的事件触发工具对(迁移自 ``_make_scheduler_tools``)。"""
    return [
        ScheduleTaskTool(scheduler=scheduler, time_parser=time_parser),
        ListScheduledTasksTool(scheduler=scheduler, time_parser=time_parser),
    ]
