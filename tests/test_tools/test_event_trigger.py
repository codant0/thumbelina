from __future__ import annotations

from datetime import datetime

import pytest

from thumbelina.scheduler.cron import CronTrigger
from thumbelina.scheduler.models import DeliveryChannel, TriggerKind
from thumbelina.tools.base import ToolCategory
from thumbelina.tools.event_trigger import (
    EventTriggerTool,
    ListScheduledTasksTool,
    ScheduleTaskTool,
    make_event_tools,
)


class FakeTask:
    def __init__(self, id="t1", description="d", scheduled_time=None, status_value="pending"):
        self.id = id
        self.description = description
        self.scheduled_time = scheduled_time or datetime(2026, 1, 1, 9, 0)
        self.status = type("S", (), {"value": status_value})()
        # v2 字段(list 行新增 Trigger/Channel 输出会消费);默认值镜像 ScheduledTask。
        self.trigger = TriggerKind.ONCE
        self.cron_expr = None
        self.next_run = None
        self.channel = DeliveryChannel.WEB


class FakeScheduler:
    def __init__(self, tasks=None):
        self.added: list = []
        self.tasks = tasks if tasks is not None else [FakeTask()]

    async def add_task(self, task):
        self.added.append(task)

    async def list_tasks(self):
        return self.tasks


class FakeTimeParser:
    def __init__(self, result=None):
        self.result = result or datetime(2026, 1, 1, 9, 0)

    def parse(self, text):
        return self.result


@pytest.mark.asyncio
async def test_schedule_task_ok():
    sched = FakeScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(description="call mom", time_expression="in 1 hour")
    assert "Task scheduled with ID" in out
    assert "Scheduled for: 2026-01-01T09:00:00" in out
    assert tool.category == ToolCategory.EVENT_TRIGGER
    assert isinstance(tool, EventTriggerTool)
    assert len(sched.added) == 1


@pytest.mark.asyncio
async def test_schedule_task_unparseable():
    parser = FakeTimeParser()
    parser.result = None
    tool = ScheduleTaskTool(scheduler=FakeScheduler(), time_parser=parser)
    out = await tool._arun(description="x", time_expression="gibberish")
    assert out == "Could not parse time expression: gibberish"


@pytest.mark.asyncio
async def test_list_scheduled_tasks_empty_and_rows():
    tool = ListScheduledTasksTool(scheduler=FakeScheduler(), time_parser=FakeTimeParser())
    out = await tool._arun()
    assert "ID: t1" in out
    assert "Status: pending" in out
    empty = ListScheduledTasksTool(scheduler=FakeScheduler(tasks=[]), time_parser=FakeTimeParser())
    assert await empty._arun() == "No scheduled tasks found."


def test_make_event_tools_returns_two():
    tools = make_event_tools(FakeScheduler(), FakeTimeParser())
    assert len(tools) == 2
    assert {t.name for t in tools} == {"schedule_task", "list_scheduled_tasks"}


# --- Task 9: schedule_task cron/channel 扩展(design §6) --------------------


class CronFallbackScheduler(FakeScheduler):
    """FakeScheduler + 真实 add_task 的 cron next_run 兜底(镜像 scheduler v2)。

    与 :meth:`TaskScheduler.add_task` 一致:CRON 任务 next_run 为 None 时用真
    :class:`CronTrigger` 计算,永不触发的表达式(如 ``0 0 31 2 *``)抛
    ``ValueError("Invalid cron expression: ...")``。
    """

    async def add_task(self, task):
        if task.trigger == TriggerKind.CRON and task.next_run is None:
            try:
                task.next_run = CronTrigger(task.cron_expr).next_after(datetime.now())
            except ValueError as exc:
                raise ValueError(f"Invalid cron expression: {task.cron_expr!r} ({exc})") from exc
        await super().add_task(task)


@pytest.mark.asyncio
async def test_schedule_task_cron_creates_cron_task():
    sched = CronFallbackScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(
        description="hourly report", cron_expression="*/30 * * * *", channel="WeChat"
    )
    assert len(sched.added) == 1
    task = sched.added[0]
    assert task.trigger == TriggerKind.CRON
    assert task.cron_expr == "*/30 * * * *"
    assert task.channel == DeliveryChannel.WECHAT
    assert task.channel.value == "wechat"
    assert task.description == "hourly report"
    assert task.content == "hourly report"
    assert task.source == "agent"
    assert task.next_run is not None
    assert "Task scheduled with ID" in out
    assert "Cron: */30 * * * *" in out
    assert "Channel: wechat" in out


@pytest.mark.asyncio
async def test_schedule_task_rejects_time_and_cron_together():
    sched = FakeScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(
        description="x", time_expression="in 1 hour", cron_expression="*/30 * * * *"
    )
    assert out == "Error: provide either time_expression or cron_expression, not both."
    assert sched.added == []


@pytest.mark.asyncio
async def test_schedule_task_rejects_invalid_cron():
    sched = FakeScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(description="x", cron_expression="not a cron")
    assert out.startswith("Error: Invalid cron expression")
    assert "not a cron" in out
    assert sched.added == []


@pytest.mark.asyncio
async def test_schedule_task_rejects_unknown_channel():
    sched = FakeScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(description="x", cron_expression="*/30 * * * *", channel="sms")
    assert out == "Error: Unknown channel 'sms'. Available: web, wechat, qq."
    assert sched.added == []
    # once 路径同样校验渠道;错误文案保留调用方原始写法(不静默改写大小写)。
    out_once = await tool._arun(description="x", time_expression="in 1 hour", channel="SMS")
    assert out_once == "Error: Unknown channel 'SMS'. Available: web, wechat, qq."
    assert sched.added == []


@pytest.mark.asyncio
async def test_schedule_task_never_firing_cron_returns_error():
    sched = CronFallbackScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(description="x", cron_expression="0 0 31 2 *")
    assert out.startswith("Error: Invalid cron expression")
    assert "0 0 31 2 *" in out
    assert sched.added == []


@pytest.mark.asyncio
async def test_schedule_task_once_with_channel_keeps_message_and_passes_fields():
    sched = FakeScheduler()
    tool = ScheduleTaskTool(scheduler=sched, time_parser=FakeTimeParser())
    out = await tool._arun(description="call mom", time_expression="in 1 hour", channel="wechat")
    task = sched.added[0]
    assert out == (
        f"Task scheduled with ID {task.id}. Description: call mom. "
        "Scheduled for: 2026-01-01T09:00:00"
    )
    assert task.channel == DeliveryChannel.WECHAT
    assert task.content == "call mom"
    assert task.source == "agent"
    assert task.trigger == TriggerKind.ONCE


def test_schedule_task_new_args_are_optional():
    tool = ScheduleTaskTool(scheduler=FakeScheduler(), time_parser=FakeTimeParser())
    schema = tool.args_schema.model_json_schema()
    props = schema["properties"]
    assert "cron_expression" in props
    assert "channel" in props
    required = schema.get("required", [])
    for field in ("time_expression", "cron_expression", "channel"):
        assert field not in required


@pytest.mark.asyncio
async def test_list_scheduled_tasks_shows_trigger_and_channel():
    cron_task = FakeTask(id="c1", description="cron job", status_value="pending")
    cron_task.trigger = TriggerKind.CRON
    cron_task.cron_expr = "*/30 * * * *"
    cron_task.next_run = datetime(2026, 1, 1, 9, 30)
    once_task = FakeTask(id="o1", description="once job")
    tool = ListScheduledTasksTool(
        scheduler=FakeScheduler(tasks=[cron_task, once_task]), time_parser=FakeTimeParser()
    )
    out = await tool._arun()
    assert "Trigger: cron(*/30 * * * *)" in out
    assert "Next: 2026-01-01T09:30:00" in out
    assert "Trigger: once" in out
    assert out.count("Channel: web") == 2
