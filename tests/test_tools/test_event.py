from __future__ import annotations

from datetime import datetime

import pytest

from thumbelina.tools.base import ToolCategory
from thumbelina.tools.event import (
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
