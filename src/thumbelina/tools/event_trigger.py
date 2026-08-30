"""事件触发工具:注册/查询未来时间与条件(spec §4.3)。

从 ``agent/graph.py`` 的 ``_make_scheduler_tools`` 迁入,函数体逐字保持,
对外 name/参数名/返回文案不变;统一继承
:class:`~thumbelina.tools.base.ThumbelinaBaseTool` 生命周期。

event-timer-tasks 扩展(design §4.3/§6): ``schedule_task`` 增可选
``cron_expression``/``channel`` 参数(cron 循环任务 + 交付渠道,渠道名大小写
不敏感、空串默认 web),``list_scheduled_tasks`` 每行增 Trigger/Channel 字段;
旧两参调用 ``schedule_task(description, time_expression)`` 的返回文案逐字不变。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.scheduler.cron import validate_cron
from thumbelina.scheduler.models import DeliveryChannel, ScheduledTask, TriggerKind
from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory

_AVAILABLE_CHANNELS = ", ".join(c.value for c in DeliveryChannel)


def _resolve_channel(name: str) -> DeliveryChannel | None:
    """Normalize a channel name (case-insensitive); ``None`` when unknown.

    An empty string means "not specified" and defaults to :attr:`DeliveryChannel.WEB`.
    """
    if not name:
        return DeliveryChannel.WEB
    normalized = name.strip().lower()
    if normalized not in {c.value for c in DeliveryChannel}:
        return None
    return DeliveryChannel(normalized)


def _unknown_channel_error(name: str) -> str:
    """Design §6 wording; *name* is echoed verbatim as the caller typed it."""
    return f"Error: Unknown channel '{name}'. Available: {_AVAILABLE_CHANNELS}."


class _ScheduleTaskArgs(BaseModel):
    description: str = Field(..., description="Description of the task to schedule.")
    time_expression: str = Field(
        "",
        description=(
            "Natural-language time expression for a one-off task; "
            "mutually exclusive with cron_expression."
        ),
    )
    cron_expression: str = Field(
        "",
        description=(
            "5-field cron expression (min hour day month weekday, or @daily etc.) "
            "for a recurring task; mutually exclusive with time_expression."
        ),
    )
    channel: str = Field(
        "",
        description=f"Delivery channel: {_AVAILABLE_CHANNELS}. Defaults to web.",
    )


class _ListScheduledTasksArgs(BaseModel):
    pass


class EventTriggerTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.EVENT_TRIGGER
    time_parser: Any = None

    def parse_trigger(self, text: str) -> datetime | None:
        return self.time_parser.parse(text) if self.time_parser else None


class ScheduleTaskTool(EventTriggerTool):
    name: str = "schedule_task"
    description: str = (
        "Schedule a task for a future time (one-off) or on a recurring cron "
        "schedule; optionally specify a delivery channel (web, wechat, or qq)."
    )
    args_schema: type[BaseModel] = _ScheduleTaskArgs
    scheduler: Any = None

    # mypy[override]: 基类 _execute(**kwargs) 由 _arun 以 args_schema 校验后的
    # 具名参数调用;具名签名是刻意的收窄(与项目其他工具一致),类型安全由
    # pydantic args_schema 保证,故精准豁免而非改成 **kwargs 取参。
    async def _execute(  # type: ignore[override]
        self,
        description: str,
        time_expression: str = "",
        cron_expression: str = "",
        channel: str = "",
    ) -> str:
        if time_expression and cron_expression:
            return "Error: provide either time_expression or cron_expression, not both."

        if cron_expression:
            # cron 分支(design §6):先 validate_cron 拒绝非法表达式,再渠道白名单。
            error = validate_cron(cron_expression)
            if error is not None:
                return f"Error: {error}"
            delivery = _resolve_channel(channel)
            if delivery is None:
                return _unknown_channel_error(channel)
            task = ScheduledTask(
                description=description,
                trigger=TriggerKind.CRON,
                cron_expr=cron_expression,
                scheduled_time=None,
                channel=delivery,
                content=description,
                source="agent",
            )
            try:
                await self.scheduler.add_task(task)
            except ValueError as exc:
                # 永不触发的表达式(如 ``0 0 31 2 *``)由 add_task 的 next_run
                # 兜底计算抛出(design §6),与本地校验共用同一 Error 文案。
                return f"Error: {exc}"
            return (
                f"Task scheduled with ID {task.id}. Description: {description}. "
                f"Cron: {cron_expression}. Channel: {delivery.value}."
            )

        delivery = _resolve_channel(channel)
        if delivery is None:
            return _unknown_channel_error(channel)
        parsed = self.parse_trigger(time_expression)
        if parsed is None:
            return f"Could not parse time expression: {time_expression}"
        task = ScheduledTask(
            description=description,
            scheduled_time=parsed,
            channel=delivery,
            content=description,
            source="agent",
        )
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

    # mypy[override]: 同 ScheduleTaskTool——无参收窄由空 args_schema 保证。
    async def _execute(self) -> str:  # type: ignore[override]
        tasks = await self.scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks found."
        return "\n".join(self._render_row(task) for task in tasks)

    @staticmethod
    def _render_row(task: ScheduledTask) -> str:
        """One row per task; legacy prefix kept verbatim, Trigger/Channel appended."""
        parts = [
            f"- ID: {task.id}",
            f"Description: {task.description}",
        ]
        # cron 任务经 API 创建时 scheduled_time 为 None(仅作创建基线),跳过该段。
        if task.scheduled_time is not None:
            parts.append(f"Scheduled: {task.scheduled_time.isoformat()}")
        parts.append(f"Status: {task.status.value}")
        if task.trigger == TriggerKind.CRON:
            parts.append(f"Trigger: cron({task.cron_expr})")
            if task.next_run is not None:
                parts.append(f"Next: {task.next_run.isoformat()}")
        else:
            parts.append("Trigger: once")
        parts.append(f"Channel: {task.channel.value}")
        return ", ".join(parts)


def make_event_tools(scheduler: Any, time_parser: Any) -> list[BaseTool]:
    """返回封装 ``TaskScheduler`` 的事件触发工具对(迁移自 ``_make_scheduler_tools``)。"""
    return [
        ScheduleTaskTool(scheduler=scheduler, time_parser=time_parser),
        ListScheduledTasksTool(scheduler=scheduler, time_parser=time_parser),
    ]
