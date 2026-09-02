"""Tests for task scheduler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thumbelina.repository.db import create_db_engine
from thumbelina.repository.models import Base
from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.models import TaskEvent, TaskEventType, TriggerKind
from thumbelina.scheduler.scheduler import ScheduledTask, TaskScheduler, TaskStatus
from thumbelina.scheduler.store import TaskStore

# Fixed "now" for recover() tests so cron fire times are deterministic
# (the hourly expression ``0 * * * *`` lands exactly on whole hours).
FIXED_NOW = datetime(2026, 8, 30, 12, 0, 0)


@pytest.fixture
def scheduler():
    """Create a TaskScheduler."""
    return TaskScheduler()


@pytest.fixture
def sample_task():
    """Create a sample scheduled task."""
    return ScheduledTask(
        id="task-1",
        description="Test task",
        scheduled_time=datetime.now() + timedelta(hours=1),
    )


class TestTaskScheduler:
    """Tests for the TaskScheduler class."""

    def test_scheduler_class_exists(self):
        """TaskScheduler should be importable."""
        assert TaskScheduler is not None

    def test_scheduler_creates_instance(self):
        """Should create a TaskScheduler."""
        s = TaskScheduler()
        assert s is not None

    @pytest.mark.asyncio
    async def test_add_task(self, scheduler, sample_task):
        """Should be able to add a task."""
        await scheduler.add_task(sample_task)

    @pytest.mark.asyncio
    async def test_get_task(self, scheduler, sample_task):
        """Should be able to get a task by ID."""
        await scheduler.add_task(sample_task)
        result = await scheduler.get_task("task-1")

        assert result is not None
        assert result.id == "task-1"
        assert result.description == "Test task"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, scheduler):
        """Should return None for non-existent task."""
        result = await scheduler.get_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_tasks(self, scheduler):
        """Should list all tasks."""
        task1 = ScheduledTask(id="t1", description="Task 1", scheduled_time=datetime.now())
        task2 = ScheduledTask(id="t2", description="Task 2", scheduled_time=datetime.now())
        await scheduler.add_task(task1)
        await scheduler.add_task(task2)

        tasks = await scheduler.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, scheduler):
        """Should return empty list when no tasks."""
        tasks = await scheduler.list_tasks()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_cancel_task(self, scheduler, sample_task):
        """Should be able to cancel a task."""
        await scheduler.add_task(sample_task)
        result = await scheduler.cancel_task("task-1")

        assert result is True
        task = await scheduler.get_task("task-1")
        assert task.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, scheduler):
        """Should return False when cancelling non-existent task."""
        result = await scheduler.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_pending_tasks(self, scheduler):
        """Should get tasks that are due."""
        past_task = ScheduledTask(
            id="past",
            description="Past task",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        future_task = ScheduledTask(
            id="future",
            description="Future task",
            scheduled_time=datetime.now() + timedelta(hours=1),
        )
        await scheduler.add_task(past_task)
        await scheduler.add_task(future_task)

        pending = await scheduler.get_due_tasks()
        assert len(pending) == 1
        assert pending[0].id == "past"

    @pytest.mark.asyncio
    async def test_complete_task(self, scheduler, sample_task):
        """Should be able to mark a task as completed."""
        await scheduler.add_task(sample_task)
        await scheduler.complete_task("task-1")

        task = await scheduler.get_task("task-1")
        assert task.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler):
        """Should start and stop the polling loop."""
        assert scheduler.running is False

        await scheduler.start()
        assert scheduler.running is True

        await scheduler.stop()
        assert scheduler.running is False

    @pytest.mark.asyncio
    async def test_start_already_running_raises(self, scheduler):
        """Should raise RuntimeError if already running."""
        await scheduler.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                await scheduler.start()
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_poll_executes_due_task(self, scheduler):
        """Background poll should execute due tasks via callback."""
        past_task = ScheduledTask(
            id="past",
            description="Past task",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(past_task)

        executed: list[str] = []

        async def callback(task: ScheduledTask) -> None:
            executed.append(task.id)

        await scheduler.start(on_due_task=callback)

        # Wait briefly for the poll loop to pick up the task
        await asyncio.sleep(0.2)

        await scheduler.stop()

        assert past_task.id in executed
        updated = await scheduler.get_task(past_task.id)
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_poll_handles_callback_error(self, scheduler):
        """Should mark task as FAILED when callback raises.

        Design doc ``2026-08-30-event-timer-tasks`` D10: failure is no
        longer conflated with cancellation (the old assertion expected
        ``CANCELLED``); a failing callback now produces the ``FAILED``
        terminal status for once tasks plus a ``task.failed`` event.
        """
        past_task = ScheduledTask(
            id="past",
            description="Past task",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(past_task)

        async def failing_callback(task: ScheduledTask) -> None:
            raise RuntimeError("boom")

        await scheduler.start(on_due_task=failing_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task(past_task.id)
        assert updated.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_not_running_initially(self, scheduler):
        """Scheduler should not be running initially."""
        assert scheduler.running is False


class TestScheduledTask:
    """Tests for the ScheduledTask class."""

    def test_task_class_exists(self):
        """ScheduledTask should be importable."""
        assert ScheduledTask is not None

    def test_task_create(self):
        """Should create a ScheduledTask."""
        task = ScheduledTask(
            id="t1",
            description="Test",
            scheduled_time=datetime.now(),
        )
        assert task.id == "t1"
        assert task.status == TaskStatus.PENDING

    def test_task_default_status(self):
        """Should default to PENDING status."""
        task = ScheduledTask(id="t1", description="Test", scheduled_time=datetime.now())
        assert task.status == TaskStatus.PENDING

    def test_task_status_enum(self):
        """TaskStatus should have expected values."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_task_default_condition(self):
        """Condition should default to None."""
        task = ScheduledTask(id="t1", description="Test", scheduled_time=datetime.now())
        assert task.condition is None

    def test_task_with_condition(self):
        """Should store a condition string."""
        task = ScheduledTask(
            id="t1",
            description="Watch file",
            scheduled_time=datetime.now(),
            condition="file_changed:/tmp/data.csv",
        )
        assert task.condition == "file_changed:/tmp/data.csv"


class TestConditionalTasks:
    """Tests for condition-based task scheduling."""

    @pytest.mark.asyncio
    async def test_condition_met_executes_task(self):
        """Should execute task when condition returns True."""

        async def always_true(c: str) -> bool:
            return True

        scheduler = TaskScheduler(check_condition=always_true)

        past_task = ScheduledTask(
            id="cond-1",
            description="Conditional task",
            scheduled_time=datetime.now() - timedelta(hours=1),
            condition="file_changed:/tmp/test",
        )
        await scheduler.add_task(past_task)

        executed: list[str] = []

        async def callback(task: ScheduledTask) -> None:
            executed.append(task.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "cond-1" in executed
        updated = await scheduler.get_task("cond-1")
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_not_met_skips_task(self):
        """Should skip task when condition returns False."""

        async def always_false(c: str) -> bool:
            return False

        scheduler = TaskScheduler(check_condition=always_false)

        past_task = ScheduledTask(
            id="cond-2",
            description="Conditional task",
            scheduled_time=datetime.now() - timedelta(hours=1),
            condition="file_changed:/tmp/test",
        )
        await scheduler.add_task(past_task)

        executed: list[str] = []

        async def callback(task: ScheduledTask) -> None:
            executed.append(task.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "cond-2" not in executed
        updated = await scheduler.get_task("cond-2")
        assert updated.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_condition_check_receives_condition_string(self):
        """Should pass the condition string to the check callback."""
        received_conditions: list[str] = []

        async def checker(condition: str) -> bool:
            received_conditions.append(condition)
            return True

        scheduler = TaskScheduler(check_condition=checker)

        task = ScheduledTask(
            id="cond-3",
            description="Test",
            scheduled_time=datetime.now() - timedelta(hours=1),
            condition="file_changed:/data.csv",
        )
        await scheduler.add_task(task)

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "file_changed:/data.csv" in received_conditions

    @pytest.mark.asyncio
    async def test_no_condition_ignores_check_callback(self):
        """Time-based tasks (no condition) should execute without check_condition."""
        check_called = []

        async def checker(condition: str) -> bool:
            check_called.append(condition)
            return True

        scheduler = TaskScheduler(check_condition=checker)

        task = ScheduledTask(
            id="time-1",
            description="Time-based task",
            scheduled_time=datetime.now() - timedelta(hours=1),
            # No condition set
        )
        await scheduler.add_task(task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "time-1" in executed
        assert len(check_called) == 0

    @pytest.mark.asyncio
    async def test_condition_check_error_continues(self):
        """Should continue processing other tasks when condition check raises."""
        call_count = 0

        async def checker(condition: str) -> bool:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("check failed")

        scheduler = TaskScheduler(check_condition=checker)

        cond_task = ScheduledTask(
            id="err-1",
            description="Will fail condition check",
            scheduled_time=datetime.now() - timedelta(hours=1),
            condition="bad_condition",
        )
        time_task = ScheduledTask(
            id="time-1",
            description="Time-based",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(cond_task)
        await scheduler.add_task(time_task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # The condition task should not be executed, but the time task should
        assert "err-1" not in executed
        assert "time-1" in executed

    @pytest.mark.asyncio
    async def test_scheduler_without_check_condition(self):
        """Tasks with conditions still execute on time when no check_condition is set."""
        scheduler = TaskScheduler()  # No check_condition

        task = ScheduledTask(
            id="no-check",
            description="Condition task without checker",
            scheduled_time=datetime.now() - timedelta(hours=1),
            condition="file_changed:/tmp/test",
        )
        await scheduler.add_task(task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # Without check_condition, condition is ignored and task runs on time
        assert "no-check" in executed


# ---------------------------------------------------------------------------
# v2: event-driven scheduling, cron, pause/resume, recover (design doc
# ``2026-08-30-event-timer-tasks`` §4/§5.2/§7.2/§7.3, decisions D5/D6/D10)
# ---------------------------------------------------------------------------


class _EventRecorder:
    """Collect every TaskEvent routed through the bus, in emission order."""

    def __init__(self) -> None:
        self.events: list[TaskEvent] = []

    async def __call__(self, event: TaskEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [event.type.value for event in self.events]


def _make_bus(recorder: _EventRecorder) -> EventBus:
    """A bus with the recorder subscribed to every event type."""
    bus = EventBus()
    for event_type in TaskEventType:
        bus.subscribe(event_type, recorder)
    return bus


def _due_cron_task(task_id: str = "cron-due") -> ScheduledTask:
    """A PENDING cron task whose next_run is already in the past."""
    return ScheduledTask(
        id=task_id,
        description="Every minute",
        trigger=TriggerKind.CRON,
        cron_expr="* * * * *",
        scheduled_time=None,
        next_run=datetime.now() - timedelta(minutes=1),
    )


def _prompt_once_task(task_id: str = "prompt-once") -> ScheduledTask:
    """A PENDING once task, mode=prompt, due now."""
    return ScheduledTask(
        id=task_id,
        description="Prompt once",
        scheduled_time=datetime.now() - timedelta(hours=1),
        mode="prompt",
    )


def _prompt_cron_task(task_id: str = "prompt-cron") -> ScheduledTask:
    """A PENDING cron task, mode=prompt, whose next_run is already in the past."""
    return ScheduledTask(
        id=task_id,
        description="Every minute prompt",
        trigger=TriggerKind.CRON,
        cron_expr="* * * * *",
        scheduled_time=None,
        next_run=datetime.now() - timedelta(minutes=1),
        mode="prompt",
    )


async def _wait_for(predicate, timeout: float = 5.0) -> bool:
    """Poll ``predicate`` until it holds or ``timeout`` (real seconds) pass."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def _wait_for_status(
    scheduler: TaskScheduler, task_id: str, status: TaskStatus
) -> ScheduledTask:
    """Poll until the task reaches ``status`` (bounded)."""
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        task = await scheduler.get_task(task_id)
        if task is not None and task.status == status:
            return task
        if asyncio.get_running_loop().time() > deadline:
            seen = task.status.value if task is not None else "missing"
            raise AssertionError(f"task {task_id} never reached {status} (saw {seen})")
        await asyncio.sleep(0.01)


async def _wait_for_settled(scheduler: TaskScheduler, task_id: str) -> ScheduledTask:
    """Poll until a prompt task is fully settled (out of _inflight with a
    non-None error, or terminal status).  Unlike _wait_for_status this does
    not short-circuit on a still-pending cron task that has not fired yet."""
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        task = await scheduler.get_task(task_id)
        if task is not None and task.id not in scheduler._inflight and task.error is not None:
            return task
        if asyncio.get_running_loop().time() > deadline:
            seen = f"status={task.status.value}" if task is not None else "missing"
            raise AssertionError(f"task {task_id} never settled (saw {seen})")
        await asyncio.sleep(0.01)


@pytest.fixture
def engine(tmp_path: Path):
    """File-backed sqlite engine with both scheduler tables created."""
    eng = create_db_engine(f"sqlite:///{tmp_path / 'scheduler-v2.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def store(engine) -> TaskStore:
    return TaskStore(engine)


class TestCronTasks:
    """v2: cron tasks fire on next_run and return to PENDING (§5.2)."""

    @pytest.mark.asyncio
    async def test_cron_task_fires_and_returns_to_pending(self, scheduler):
        """After a successful round the cron task is PENDING with next_run advanced."""
        now = datetime.now()
        task = _due_cron_task("cron-1")
        await scheduler.add_task(task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert executed == ["cron-1"]
        updated = await scheduler.get_task("cron-1")
        assert updated is not None
        assert updated.status == TaskStatus.PENDING
        assert updated.next_run is not None
        assert updated.next_run > now
        assert updated.last_run is not None

    @pytest.mark.asyncio
    async def test_cron_callback_failure_keeps_pending_with_error(self, store):
        """A failing delivery keeps the cron task PENDING and records the error."""
        scheduler = TaskScheduler(store=store)
        task = _due_cron_task("cron-fail")
        await scheduler.add_task(task)

        async def failing_callback(t: ScheduledTask) -> None:
            raise RuntimeError("boom")

        await scheduler.start(on_due_task=failing_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task("cron-fail")
        assert updated is not None
        assert updated.status == TaskStatus.PENDING
        assert updated.error == "boom"
        assert updated.next_run is not None
        assert updated.next_run > datetime.now()  # failed slot consumed (R1)
        persisted = await store.get_task("cron-fail")
        assert persisted is not None
        assert persisted.status == TaskStatus.PENDING
        assert persisted.error == "boom"
        assert persisted.next_run is not None
        assert persisted.next_run > datetime.now()  # advanced next_run persisted

    @pytest.mark.asyncio
    async def test_cron_failure_consumes_slot_and_does_not_retry_next_poll(self):
        """A failed cron round consumes its slot (review ruling R1).

        next_run advances to the next future occurrence, so the next poll
        round neither calls the callback nor emits ``task.due`` again —
        no 1Hz retry storm.  The daily ``0 23 * * *`` expression keeps the
        recomputed next_run hours away, making the second-poll assertion
        deterministic.
        """
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        now = datetime.now()
        task = ScheduledTask(
            id="cron-fail-once",
            description="Daily 23:00, failing delivery",
            trigger=TriggerKind.CRON,
            cron_expr="0 23 * * *",
            scheduled_time=None,
            next_run=now - timedelta(minutes=1),  # due now
        )
        await scheduler.add_task(task)

        calls: list[str] = []

        async def failing_callback(t: ScheduledTask) -> None:
            calls.append(t.id)
            raise RuntimeError("boom")

        await scheduler.start(on_due_task=failing_callback)
        await asyncio.sleep(0.2)  # first round fires and fails
        assert await scheduler.get_due_tasks() == []  # slot consumed
        await asyncio.sleep(1.2)  # past the next poll wake-up (floor is 1s)
        await scheduler.stop()

        assert calls == ["cron-fail-once"]
        due_events = [e for e in recorder.events if e.type == TaskEventType.DUE]
        assert len(due_events) == 1
        updated = await scheduler.get_task("cron-fail-once")
        assert updated is not None
        assert updated.status == TaskStatus.PENDING
        assert updated.error == "boom"
        assert updated.next_run is not None
        assert updated.next_run > now

    @pytest.mark.asyncio
    async def test_add_task_computes_next_run_fallback(self, scheduler):
        """add_task fills a missing next_run from the cron expression."""
        task = ScheduledTask(
            description="Morning briefing",
            trigger=TriggerKind.CRON,
            cron_expr="0 9 * * *",
            scheduled_time=None,
        )
        await scheduler.add_task(task)

        stored = await scheduler.get_task(task.id)
        assert stored is not None
        assert stored.next_run is not None
        assert stored.next_run > datetime.now()

    @pytest.mark.asyncio
    async def test_add_task_preserves_provided_next_run(self, scheduler):
        """A caller-supplied next_run is kept as the sole scheduling basis."""
        next_run = datetime.now() + timedelta(hours=2)
        task = ScheduledTask(
            description="Morning briefing",
            trigger=TriggerKind.CRON,
            cron_expr="0 9 * * *",
            scheduled_time=None,
            next_run=next_run,
        )
        await scheduler.add_task(task)

        stored = await scheduler.get_task(task.id)
        assert stored is not None
        assert stored.next_run == next_run

    @pytest.mark.asyncio
    async def test_add_task_rejects_never_firing_cron_expression(self, scheduler):
        """``0 0 31 2 *`` never fires — creation is refused with ValueError."""
        task = ScheduledTask(
            description="Impossible",
            trigger=TriggerKind.CRON,
            cron_expr="0 0 31 2 *",
            scheduled_time=None,
        )
        with pytest.raises(ValueError, match="Invalid cron expression"):
            await scheduler.add_task(task)
        assert await scheduler.get_task(task.id) is None

    @pytest.mark.asyncio
    async def test_add_task_rejects_invalid_cron_expression(self, scheduler):
        task = ScheduledTask(
            description="Broken",
            trigger=TriggerKind.CRON,
            cron_expr="not-a-cron",
            scheduled_time=None,
        )
        with pytest.raises(ValueError, match="Invalid cron expression"):
            await scheduler.add_task(task)
        assert await scheduler.get_task(task.id) is None

    @pytest.mark.asyncio
    async def test_add_task_rejects_cron_without_expression(self, scheduler):
        task = ScheduledTask(
            description="No expr",
            trigger=TriggerKind.CRON,
            cron_expr=None,
            scheduled_time=None,
        )
        with pytest.raises(ValueError):
            await scheduler.add_task(task)
        assert await scheduler.get_task(task.id) is None

    @pytest.mark.asyncio
    async def test_get_due_tasks_includes_due_cron(self, scheduler):
        """The due criterion for cron is ``status=PENDING ∧ next_run <= now``."""
        task = _due_cron_task("cron-due-2")
        future_cron = ScheduledTask(
            id="cron-future",
            description="Later",
            trigger=TriggerKind.CRON,
            cron_expr="0 9 * * *",
            scheduled_time=None,
            next_run=datetime.now() + timedelta(hours=1),
        )
        await scheduler.add_task(task)
        await scheduler.add_task(future_cron)

        due = await scheduler.get_due_tasks()
        assert [t.id for t in due] == ["cron-due-2"]


class TestPauseResume:
    """v2: pause/resume (cron only; design §8.1 semantics at scheduler level)."""

    @pytest.mark.asyncio
    async def test_pause_prevents_firing(self, scheduler):
        task = _due_cron_task("cron-pause")
        await scheduler.add_task(task)
        assert await scheduler.pause_task(task.id) is True
        assert task.status == TaskStatus.PAUSED

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert executed == []
        updated = await scheduler.get_task("cron-pause")
        assert updated is not None
        assert updated.status == TaskStatus.PAUSED

    @pytest.mark.asyncio
    async def test_resume_recomputes_next_run_and_restores_pending(self, scheduler):
        task = _due_cron_task("cron-resume")
        await scheduler.add_task(task)
        await scheduler.pause_task(task.id)

        resumed_at = datetime.now()
        assert await scheduler.resume_task(task.id) is True
        assert task.status == TaskStatus.PENDING
        assert task.next_run is not None
        assert task.next_run > resumed_at

    @pytest.mark.asyncio
    async def test_resumed_task_fires_when_due_again(self, scheduler):
        task = _due_cron_task("cron-resume-fire")
        await scheduler.add_task(task)
        await scheduler.pause_task(task.id)
        await scheduler.resume_task(task.id)

        # Resume recomputed next_run into the future; force it due again to
        # prove the task participates in scheduling once more.
        task.next_run = datetime.now() - timedelta(minutes=1)
        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert executed == ["cron-resume-fire"]
        updated = await scheduler.get_task("cron-resume-fire")
        assert updated is not None
        assert updated.status == TaskStatus.PENDING
        assert updated.next_run is not None
        assert updated.next_run > datetime.now() - timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_pause_rejects_once_task(self, scheduler):
        task = ScheduledTask(
            id="once-pause",
            description="Once",
            scheduled_time=datetime.now() + timedelta(hours=1),
        )
        await scheduler.add_task(task)
        assert await scheduler.pause_task("once-pause") is False
        updated = await scheduler.get_task("once-pause")
        assert updated is not None
        assert updated.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_resume_requires_paused_status(self, scheduler):
        task = _due_cron_task("cron-not-paused")
        await scheduler.add_task(task)
        assert await scheduler.resume_task("cron-not-paused") is False

    @pytest.mark.asyncio
    async def test_pause_nonexistent_task(self, scheduler):
        assert await scheduler.pause_task("missing") is False

    @pytest.mark.asyncio
    async def test_paused_task_can_be_cancelled(self, scheduler):
        task = _due_cron_task("cron-paused-cancel")
        await scheduler.add_task(task)
        assert await scheduler.pause_task(task.id) is True
        assert await scheduler.cancel_task(task.id) is True
        updated = await scheduler.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.CANCELLED


class TestRecover:
    """recover() implements all five §7.2 startup-recovery rules."""

    @pytest.mark.asyncio
    async def test_recover_without_store_is_noop(self, scheduler):
        await scheduler.recover()
        await scheduler.recover(now=FIXED_NOW)
        assert await scheduler.list_tasks() == []

    @pytest.mark.asyncio
    async def test_recover_marks_overdue_once_missed(self, store):
        """Rule 1 (mark policy): beyond grace → MISSED terminal + task.missed."""
        recorder = _EventRecorder()
        task = ScheduledTask(
            id="late-once",
            description="Late",
            scheduled_time=FIXED_NOW - timedelta(minutes=10),
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder))
        await scheduler.recover(now=FIXED_NOW)

        recovered = await scheduler.get_task("late-once")
        assert recovered is not None
        assert recovered.status == TaskStatus.MISSED
        persisted = await store.get_task("late-once")
        assert persisted is not None
        assert persisted.status == TaskStatus.MISSED

        missed = [e for e in recorder.events if e.type == TaskEventType.MISSED]
        assert len(missed) == 1
        assert missed[0].task_id == "late-once"
        assert missed[0].payload["policy"] == "mark"

    @pytest.mark.asyncio
    async def test_recover_keeps_once_within_grace_pending_then_fires(self, store):
        """Rule 2: (now-grace, now] → stays PENDING and fires on the next scan."""
        task = ScheduledTask(
            id="grace-once",
            description="Within grace",
            scheduled_time=FIXED_NOW - timedelta(minutes=2),
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store)
        await scheduler.recover(now=FIXED_NOW)
        recovered = await scheduler.get_task("grace-once")
        assert recovered is not None
        assert recovered.status == TaskStatus.PENDING

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "grace-once" in executed
        updated = await scheduler.get_task("grace-once")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_recover_fails_residue_running_once(self, store):
        """Rule 3: ONCE RUNNING residue from a previous process → FAILED."""
        recorder = _EventRecorder()
        task = ScheduledTask(
            id="stuck-once",
            description="Interrupted",
            scheduled_time=FIXED_NOW - timedelta(hours=1),
            status=TaskStatus.RUNNING,
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder))
        await scheduler.recover(now=FIXED_NOW)

        recovered = await scheduler.get_task("stuck-once")
        assert recovered is not None
        assert recovered.status == TaskStatus.FAILED
        assert recovered.error == "interrupted by restart"
        persisted = await store.get_task("stuck-once")
        assert persisted is not None
        assert persisted.status == TaskStatus.FAILED

        failed = [e for e in recorder.events if e.type == TaskEventType.FAILED]
        assert len(failed) == 1
        assert failed[0].payload["error"] == "interrupted by restart"

    @pytest.mark.asyncio
    async def test_recover_fails_residue_running_cron(self, store):
        """Rule 5: CRON RUNNING residue → FAILED (same treatment as rule 3)."""
        task = ScheduledTask(
            id="stuck-cron",
            description="Interrupted cron",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=FIXED_NOW + timedelta(hours=1),
            status=TaskStatus.RUNNING,
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store)
        await scheduler.recover(now=FIXED_NOW)

        recovered = await scheduler.get_task("stuck-cron")
        assert recovered is not None
        assert recovered.status == TaskStatus.FAILED
        assert recovered.error == "interrupted by restart"

    @pytest.mark.asyncio
    async def test_recover_fails_cron_task_with_invalid_expression(self, store):
        """M4 (final review): a stored row whose ``cron_expr`` no longer
        parses (hand-edited DB / external writer) must not be hydrated —
        left schedulable it would be due on every poll cycle (1Hz delivery
        storm).  It is failed and kept out of the working set instead."""
        recorder = _EventRecorder()
        task = ScheduledTask(
            id="cron-bad-expr",
            description="Hand-edited row",
            trigger=TriggerKind.CRON,
            cron_expr="not a cron",
            scheduled_time=None,
            next_run=datetime.now() - timedelta(minutes=1),
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder))
        await scheduler.recover(now=datetime.now())

        # Not hydrated into the in-memory working set → never scheduled.
        assert all(t.id != "cron-bad-expr" for t in await scheduler.list_tasks())
        assert await scheduler.get_due_tasks() == []
        # The store row carries the FAILED verdict.
        persisted = await store.get_task("cron-bad-expr")
        assert persisted is not None
        assert persisted.status == TaskStatus.FAILED
        assert persisted.error == "invalid cron expression"
        failed = [e for e in recorder.events if e.type == TaskEventType.FAILED]
        assert len(failed) == 1
        assert failed[0].payload["error"] == "invalid cron expression"

    @pytest.mark.asyncio
    async def test_recover_fails_paused_cron_task_with_invalid_expression(self, store):
        """A PAUSED cron task with an unparsable expression can never be
        resumed (resume re-validates); recover fails it up front."""
        task = ScheduledTask(
            id="cron-bad-paused",
            description="Paused with broken expr",
            trigger=TriggerKind.CRON,
            cron_expr="* * *",
            scheduled_time=None,
            next_run=datetime.now() + timedelta(hours=1),
            status=TaskStatus.PAUSED,
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store)
        await scheduler.recover(now=datetime.now())

        assert all(t.id != "cron-bad-paused" for t in await scheduler.list_tasks())
        persisted = await store.get_task("cron-bad-paused")
        assert persisted is not None
        assert persisted.status == TaskStatus.FAILED
        assert persisted.error == "invalid cron expression"

    @pytest.mark.asyncio
    async def test_recover_skips_cron_tasks_without_croniter(self, store, monkeypatch):
        """croniter 缺失时的优雅降级：cron 任务不水合、**不**判 FAILED——
        store 行原样保留（装回 croniter 后重启可正常 recover），一次性任务
        不受影响。直接 FAILED 会是对正常行的错误定论。"""
        import thumbelina.scheduler.scheduler as scheduler_module

        monkeypatch.setattr(scheduler_module, "CRONITER_AVAILABLE", False)
        recorder = _EventRecorder()
        cron_task = ScheduledTask(
            id="cron-no-lib",
            description="Hourly",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=datetime.now() - timedelta(minutes=30),
        )
        once_task = ScheduledTask(
            id="once-still-works",
            description="Reminder",
            trigger=TriggerKind.ONCE,
            scheduled_time=datetime.now() + timedelta(hours=1),
        )
        await store.upsert_task(cron_task)
        await store.upsert_task(once_task)

        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder))
        await scheduler.recover(now=datetime.now())

        # cron 任务未水合，且 store 行保持 PENDING 原样。
        assert all(t.trigger != TriggerKind.CRON for t in await scheduler.list_tasks())
        persisted = await store.get_task("cron-no-lib")
        assert persisted is not None
        assert persisted.status == TaskStatus.PENDING
        assert persisted.error is None
        # 一次性任务照常水合，且没有 FAILED/事件副作用。
        assert any(t.id == "once-still-works" for t in await scheduler.list_tasks())
        assert recorder.events == []

    @pytest.mark.asyncio
    async def test_recover_advances_overdue_cron_with_single_summary_event(self, store):
        """Rule 4 (mark): next_run jumps to the future, ONE summary task.missed."""
        recorder = _EventRecorder()
        task = ScheduledTask(
            id="cron-backlog",
            description="Hourly",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=FIXED_NOW - timedelta(minutes=90),
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder))
        await scheduler.recover(now=FIXED_NOW)

        recovered = await scheduler.get_task("cron-backlog")
        assert recovered is not None
        assert recovered.status == TaskStatus.PENDING
        # occurrences in (10:30, 12:00] are 11:00 and 12:00; next is 13:00
        assert recovered.next_run == datetime(2026, 8, 30, 13, 0, 0)
        persisted = await store.get_task("cron-backlog")
        assert persisted is not None
        assert persisted.next_run == datetime(2026, 8, 30, 13, 0, 0)

        missed = [e for e in recorder.events if e.type == TaskEventType.MISSED]
        assert len(missed) == 1  # one summary, not one per skipped occurrence
        assert missed[0].payload["skipped_occurrences"] == 2
        assert missed[0].payload["policy"] == "mark"

    @pytest.mark.asyncio
    async def test_recover_run_policy_emits_summary_missed_and_fires_once(self, store):
        """Rule 4 under ``run`` policy (review ruling R2).

        A single summary ``task.missed`` is emitted under both policies;
        ``run`` differs from ``mark`` only in that the backlog fires at
        most once (next_run is left untouched so the scan consumes it).
        """
        recorder = _EventRecorder()
        config = SimpleNamespace(missed_policy="run", missed_grace_minutes=5)
        overdue = datetime.now() - timedelta(minutes=1)
        task = ScheduledTask(
            id="cron-run-backlog",
            description="Every minute, run policy",
            trigger=TriggerKind.CRON,
            cron_expr="* * * * *",
            scheduled_time=None,
            next_run=overdue,
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder), config=config)
        await scheduler.recover(now=datetime.now())

        recovered = await scheduler.get_task("cron-run-backlog")
        assert recovered is not None
        assert recovered.status == TaskStatus.PENDING
        assert recovered.next_run is not None
        # recover left next_run untouched (the backlog still fires via scan)
        assert abs((recovered.next_run - overdue).total_seconds()) < 1

        missed = [e for e in recorder.events if e.type == TaskEventType.MISSED]
        assert len(missed) == 1  # one summary event under run policy too
        assert missed[0].payload["policy"] == "run"
        assert missed[0].payload["skipped_occurrences"] >= 1

        # Align to just after a minute boundary so the *next* scheduled
        # occurrence is ~59s away — "fires exactly once" stays deterministic.
        while datetime.now().second > 57:
            await asyncio.sleep(0.2)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert executed == ["cron-run-backlog"]  # fired exactly once
        fired = await scheduler.get_task("cron-run-backlog")
        assert fired is not None
        assert fired.status == TaskStatus.PENDING
        assert fired.next_run is not None
        assert fired.next_run > datetime.now() - timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_recover_run_policy_keeps_overdue_once_pending(self, store):
        """§7.3 ``run`` policy: overdue once tasks stay PENDING and fire."""
        config = SimpleNamespace(missed_policy="run", missed_grace_minutes=5)
        task = ScheduledTask(
            id="run-once",
            description="Run late",
            scheduled_time=FIXED_NOW - timedelta(minutes=10),
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, config=config)
        await scheduler.recover(now=FIXED_NOW)
        recovered = await scheduler.get_task("run-once")
        assert recovered is not None
        assert recovered.status == TaskStatus.PENDING

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "run-once" in executed
        updated = await scheduler.get_task("run-once")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_recover_defaults_mark_policy_with_custom_grace(self, store):
        """Default policy is ``mark``; grace minutes come from config."""
        config = SimpleNamespace(missed_policy="mark", missed_grace_minutes=30)
        task = ScheduledTask(
            id="wide-grace",
            description="Within wide grace",
            scheduled_time=FIXED_NOW - timedelta(minutes=10),
        )
        await store.upsert_task(task)

        scheduler = TaskScheduler(store=store, config=config)
        await scheduler.recover(now=FIXED_NOW)

        recovered = await scheduler.get_task("wide-grace")
        assert recovered is not None
        assert recovered.status == TaskStatus.PENDING  # inside 30min grace


class TestStorePersistence:
    """v2: every status transition is written through to the store."""

    @pytest.mark.asyncio
    async def test_once_lifecycle_persists_transitions(self, store):
        scheduler = TaskScheduler(store=store)
        task = ScheduledTask(
            id="persist-once",
            description="Once",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(task)

        persisted = await store.get_task("persist-once")
        assert persisted is not None
        assert persisted.status == TaskStatus.PENDING

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        persisted = await store.get_task("persist-once")
        assert persisted is not None
        assert persisted.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_pause_resume_cancel_persist(self, store):
        scheduler = TaskScheduler(store=store)
        task = _due_cron_task("persist-cron")
        await scheduler.add_task(task)

        await scheduler.pause_task(task.id)
        persisted = await store.get_task(task.id)
        assert persisted is not None
        assert persisted.status == TaskStatus.PAUSED

        await scheduler.resume_task(task.id)
        persisted = await store.get_task(task.id)
        assert persisted is not None
        assert persisted.status == TaskStatus.PENDING

        await scheduler.cancel_task(task.id)
        persisted = await store.get_task(task.id)
        assert persisted is not None
        assert persisted.status == TaskStatus.CANCELLED


class TestEventEmission:
    """v2: structured events on the bus match the §5.2 firing sequence."""

    @pytest.mark.asyncio
    async def test_once_full_lifecycle_event_sequence(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = ScheduledTask(
            id="ev-once",
            description="Once",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert recorder.types() == ["task.created", "task.due", "task.completed"]
        due_event = recorder.events[1]
        assert due_event.payload["scheduled_for"] is not None

    @pytest.mark.asyncio
    async def test_cron_failure_event_sequence(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        await scheduler.add_task(_due_cron_task("ev-cron-fail"))

        async def failing_callback(t: ScheduledTask) -> None:
            raise RuntimeError("boom")

        await scheduler.start(on_due_task=failing_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert recorder.types() == ["task.created", "task.due", "task.failed"]
        failed = recorder.events[-1]
        assert failed.payload["error"] == "boom"

    @pytest.mark.asyncio
    async def test_cancel_emits_cancelled_event(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = ScheduledTask(
            id="ev-cancel",
            description="Cancel me",
            scheduled_time=datetime.now() + timedelta(hours=1),
        )
        await scheduler.add_task(task)
        await scheduler.cancel_task(task.id)

        assert recorder.types() == ["task.created", "task.cancelled"]

    @pytest.mark.asyncio
    async def test_condition_not_met_emits_no_due_event(self):
        recorder = _EventRecorder()

        async def always_false(c: str) -> bool:
            return False

        scheduler = TaskScheduler(bus=_make_bus(recorder), check_condition=always_false)
        task = ScheduledTask(
            id="ev-cond",
            description="Conditional",
            scheduled_time=datetime.now() - timedelta(hours=1),
            condition="file_changed:/tmp/never",
        )
        await scheduler.add_task(task)

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert recorder.types() == ["task.created"]

    @pytest.mark.asyncio
    async def test_no_bus_silently_drops_events(self):
        """Without a bus, events are dropped and firing still completes."""
        scheduler = TaskScheduler()  # no bus, no store
        task = ScheduledTask(
            id="ev-drop",
            description="No bus",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert executed == ["ev-drop"]
        updated = await scheduler.get_task("ev-drop")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED


class _FailingStore:
    """A store whose every operation raises — simulates a dead database."""

    async def upsert_task(self, task: ScheduledTask) -> None:
        raise RuntimeError("db down")

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        raise RuntimeError("db down")

    async def list_tasks(self) -> list[ScheduledTask]:
        raise RuntimeError("db down")


class TestStoreFailureDegradation:
    """设计 §11: 存储不可用 → 调度器回退内存 dict 运行 + logger.warning，服务器不挂。"""

    @pytest.mark.asyncio
    async def test_scheduler_survives_store_failure(self, caplog):
        """A raising store must not kill the poll loop or lose in-memory state.

        Two due tasks are added up front: without the guard the first
        persist failure would propagate out of ``add_task`` / the poll loop;
        with the guard both tasks still fire and complete.
        """
        with caplog.at_level("WARNING"):
            scheduler = TaskScheduler(store=_FailingStore())
            await scheduler.add_task(
                ScheduledTask(
                    id="degrade-a",
                    description="First due",
                    scheduled_time=datetime.now() - timedelta(hours=1),
                )
            )
            await scheduler.add_task(
                ScheduledTask(
                    id="degrade-b",
                    description="Second due",
                    scheduled_time=datetime.now() - timedelta(hours=1),
                )
            )

            executed: list[str] = []

            async def callback(t: ScheduledTask) -> None:
                executed.append(t.id)

            await scheduler.start(on_due_task=callback)
            await asyncio.sleep(0.3)
            assert scheduler.running is True  # loop survived the store errors
            await scheduler.stop()
            assert scheduler.running is False

        assert executed == ["degrade-a", "degrade-b"]
        first = await scheduler.get_task("degrade-a")
        assert first is not None
        assert first.status == TaskStatus.COMPLETED
        second = await scheduler.get_task("degrade-b")
        assert second is not None
        assert second.status == TaskStatus.COMPLETED
        assert "Task store" in caplog.text  # degradation was warned about

    @pytest.mark.asyncio
    async def test_recover_with_failing_store_does_not_raise(self, caplog):
        with caplog.at_level("WARNING"):
            scheduler = TaskScheduler(store=_FailingStore())
            await scheduler.recover()  # must not raise
        assert await scheduler.list_tasks() == []
        assert "Task store" in caplog.text

    @pytest.mark.asyncio
    async def test_get_task_with_failing_store_returns_none(self):
        scheduler = TaskScheduler(store=_FailingStore())
        # Memory miss + guarded store fallback → None instead of RuntimeError.
        assert await scheduler.get_task("missing") is None


class TestPollLoopResilience:
    """C1 (final review): one poisoned scan round must not kill the loop,
    and a loop that died with a real exception must not break ``stop()``."""

    @pytest.mark.asyncio
    async def test_poll_loop_survives_poison_scan_and_keeps_delivering(self, caplog):
        """A tz-aware ``scheduled_time`` makes the naive comparison in
        ``get_due_tasks`` raise ``TypeError`` every round.  The loop must
        log the failure, keep polling, and deliver other tasks once the
        poison is gone.
        """
        with caplog.at_level("WARNING"):
            scheduler = TaskScheduler()
            poison = ScheduledTask(
                id="poison",
                description="Aware timestamp from a hand-written row",
                scheduled_time=datetime(2027, 1, 1, tzinfo=UTC),
            )
            healthy = ScheduledTask(
                id="healthy",
                description="Due now",
                scheduled_time=datetime.now() - timedelta(hours=1),
            )
            await scheduler.add_task(poison)
            await scheduler.add_task(healthy)

            executed: list[str] = []

            async def callback(t: ScheduledTask) -> None:
                executed.append(t.id)

            await scheduler.start(on_due_task=callback)
            await asyncio.sleep(0.2)  # first scan hits the poison

            # The loop is alive despite the poisoned scan round.
            assert scheduler._poll_task is not None
            assert not scheduler._poll_task.done()

            # Remove the poison: the next round delivers the healthy task.
            await scheduler.cancel_task("poison")
            await asyncio.sleep(1.5)  # past the 1s poll-wake floor
            await scheduler.stop()

        assert executed == ["healthy"]
        updated = await scheduler.get_task("healthy")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert "Scan round failed" in caplog.text

    @pytest.mark.asyncio
    async def test_stop_swallows_exception_from_dead_poll_task(self, caplog):
        """``stop()`` must not raise when the poll task died with a real
        exception (not cancellation) — a propagating error would break the
        lifespan shutdown.
        """
        scheduler = TaskScheduler()

        async def _poison() -> None:
            raise TypeError("can't compare offset-naive and offset-aware datetimes")

        scheduler._running = True
        scheduler._poll_task = asyncio.create_task(_poison())
        await asyncio.sleep(0.05)  # let the poison task fail

        with caplog.at_level("WARNING"):
            await scheduler.stop()  # must not raise

        assert scheduler.running is False
        assert scheduler._poll_task is None
        assert "TypeError" in caplog.text


class TestReapedTaskNotResurrected:
    """I2 (final review): the Heartbeat's stale-RUNNING reaper may fail a
    task while its delivery callback is still in flight.  When the callback
    then returns successfully, ``_fire_task`` must keep the FAILED verdict
    instead of overwriting it (FAILED→COMPLETED resurrection + contradictory
    event pair)."""

    @pytest.mark.asyncio
    async def test_success_callback_after_reaping_keeps_failed(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = ScheduledTask(
            id="reaped-once",
            description="Reaped mid-delivery",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(task)

        async def reaping_callback(t: ScheduledTask) -> None:
            # Simulate the Heartbeat reaping the RUNNING task as stale
            # while the delivery is in flight, then delivering fine.
            t.status = TaskStatus.FAILED
            t.error = "stale running"

        await scheduler.start(on_due_task=reaping_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task("reaped-once")
        assert updated is not None
        assert updated.status == TaskStatus.FAILED
        assert updated.error == "stale running"
        assert recorder.types() == ["task.created", "task.due"]  # no COMPLETED

    @pytest.mark.asyncio
    async def test_cron_reaped_during_delivery_stays_failed(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        await scheduler.add_task(_due_cron_task("reaped-cron"))

        async def reaping_callback(t: ScheduledTask) -> None:
            t.status = TaskStatus.FAILED
            t.error = "stale running"

        await scheduler.start(on_due_task=reaping_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task("reaped-cron")
        assert updated is not None
        assert updated.status == TaskStatus.FAILED  # not resurrected to PENDING
        assert recorder.types() == ["task.created", "task.due"]  # no COMPLETED


class TestReapedTaskFailurePathGuarded:
    """I2 (final review): the success path of ``_fire_task`` already keeps
    the Heartbeat reaper's FAILED verdict; the failure path (callback
    raises) must respect it too — no PENDING resurrection, no ``next_run``
    advance, and no second ``task.failed`` on top of the reaper's own
    (contradictory event pair)."""

    @pytest.mark.asyncio
    async def test_cron_failure_callback_after_reaping_stays_failed(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = _due_cron_task("reaped-cron-fail")
        await scheduler.add_task(task)
        reaped_next_run = task.next_run

        async def reaping_then_failing_callback(t: ScheduledTask) -> None:
            # Simulate the Heartbeat reaping the RUNNING task as stale
            # while the delivery is in flight, then the delivery failing.
            t.status = TaskStatus.FAILED
            t.error = "stale running"
            raise RuntimeError("boom")

        await scheduler.start(on_due_task=reaping_then_failing_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task("reaped-cron-fail")
        assert updated is not None
        assert updated.status == TaskStatus.FAILED  # not resurrected to PENDING
        assert updated.error == "stale running"  # reaper's verdict, not "boom"
        assert updated.next_run == reaped_next_run  # not advanced past the reap
        assert recorder.types() == ["task.created", "task.due"]  # no second task.failed

    @pytest.mark.asyncio
    async def test_once_failure_callback_after_reaping_keeps_single_failed(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = ScheduledTask(
            id="reaped-once-fail",
            description="Reaped mid-delivery, delivery then fails",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(task)

        async def reaping_then_failing_callback(t: ScheduledTask) -> None:
            # Simulate the full stale-RUNNING reaper disposition (heartbeat
            # _check_stale_running): FAILED verdict + task.failed event,
            # then the delivery fails anyway.
            t.status = TaskStatus.FAILED
            t.error = "stale running"
            await scheduler._persist(t)
            await scheduler._emit(
                scheduler._make_event(t, TaskEventType.FAILED, {"error": "stale running"})
            )
            raise RuntimeError("boom")

        await scheduler.start(on_due_task=reaping_then_failing_callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task("reaped-once-fail")
        assert updated is not None
        assert updated.status == TaskStatus.FAILED
        assert updated.error == "stale running"  # reaper's verdict, not "boom"
        # Exactly one task.failed — the reaper's own, no contradictory pair.
        assert recorder.types() == ["task.created", "task.due", "task.failed"]


class TestV2Construction:
    """v2: all constructor parameters are optional (graceful degradation)."""

    def test_all_optional_parameters(self):
        scheduler = TaskScheduler(
            store=None,
            bus=None,
            check_condition=None,
            config=None,
        )
        assert scheduler.running is False

    def test_config_duck_typing_accepted(self):
        config = SimpleNamespace(missed_policy="run", missed_grace_minutes=1)
        scheduler = TaskScheduler(config=config)
        assert scheduler.running is False

    @pytest.mark.asyncio
    async def test_store_without_recover_still_scans_memory_tasks(self, store):
        """Tasks added via add_task fire even before recover() hydrates."""
        scheduler = TaskScheduler(store=store)
        task = ScheduledTask(
            id="no-recover",
            description="Direct add",
            scheduled_time=datetime.now() - timedelta(hours=1),
        )
        await scheduler.add_task(task)

        executed: list[str] = []

        async def callback(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert executed == ["no-recover"]


class TestPromptMode:
    """Task 12: mode="prompt" — 后台执行、cron 槽位提前消费、超时、_inflight
    （设计 §5.4）。notify 路径行为逐字不变；这些用例只针对 prompt 分支。"""

    @pytest.mark.asyncio
    async def test_prompt_fire_does_not_block_scan_and_tracks_inflight(self):
        """A slow prompt execution must not block the scan round: a second due
        task fires while the prompt task is still executing, and the prompt
        task id is in ``_inflight`` until it settles."""
        scheduler = TaskScheduler()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_runner(task: ScheduledTask) -> str:
            entered.set()
            await release.wait()
            return "slow reply"

        prompt = _prompt_once_task("prompt-slow")
        second = ScheduledTask(
            id="prompt-second",
            description="Second task",
            scheduled_time=datetime.now() - timedelta(hours=1),
            mode="notify",
        )
        await scheduler.add_task(prompt)
        await scheduler.add_task(second)

        executed: list[str] = []

        async def on_due(t: ScheduledTask) -> None:
            executed.append(t.id)

        await scheduler.start(on_due_task=on_due, on_prompt_task=slow_runner)
        try:
            assert await _wait_for(entered.is_set)
            # The scan round was not blocked: the second task already fired
            # while the prompt execution is still in flight.
            assert "prompt-second" in executed
            assert prompt.id in scheduler._inflight
            running = await scheduler.get_task("prompt-slow")
            assert running is not None and running.status == TaskStatus.RUNNING
        finally:
            release.set()
            assert await _wait_for(lambda: prompt.id not in scheduler._inflight)
            await scheduler.stop()

        updated = await scheduler.get_task("prompt-slow")
        assert updated is not None and updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_prompt_once_completed_records_reply_result(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = _prompt_once_task("prompt-once")
        await scheduler.add_task(task)

        async def runner(t: ScheduledTask) -> str:
            return "早安简报已生成"

        await scheduler.start(on_prompt_task=runner)
        try:
            settled = await _wait_for_status(scheduler, "prompt-once", TaskStatus.COMPLETED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.COMPLETED
        assert settled.result == "早安简报已生成"
        assert recorder.types() == ["task.created", "task.due", "task.completed"]
        completed = [e for e in recorder.events if e.type == TaskEventType.COMPLETED]
        assert len(completed) == 1
        assert completed[0].payload["result"] == "早安简报已生成"
        assert task.id not in scheduler._inflight

    @pytest.mark.asyncio
    async def test_prompt_cron_advances_next_run_immediately_while_running(self, store):
        """The cron slot is consumed at fire time, decoupled from the execution
        duration: next_run is advanced and persisted while the task is still
        RUNNING, and the advanced value is kept at settle time."""
        recorder = _EventRecorder()
        scheduler = TaskScheduler(store=store, bus=_make_bus(recorder))
        now = datetime.now()
        task = _prompt_cron_task("prompt-cron-advance")
        task.next_run = now - timedelta(minutes=1)
        await scheduler.add_task(task)

        entered = asyncio.Event()
        release = asyncio.Event()

        async def runner(t: ScheduledTask) -> str:
            entered.set()
            await release.wait()
            return "cron reply"

        await scheduler.start(on_prompt_task=runner)
        try:
            assert await _wait_for(entered.is_set)
            running = await scheduler.get_task("prompt-cron-advance")
            assert running is not None and running.status == TaskStatus.RUNNING
            assert running.next_run is not None and running.next_run > now
            persisted = await store.get_task("prompt-cron-advance")
            assert persisted is not None
            assert persisted.status == TaskStatus.RUNNING
            assert persisted.next_run is not None and persisted.next_run == running.next_run
        finally:
            release.set()
            assert await _wait_for(lambda: task.id not in scheduler._inflight)
            await scheduler.stop()

        updated = await scheduler.get_task("prompt-cron-advance")
        assert updated is not None and updated.status == TaskStatus.PENDING
        assert updated.next_run == running.next_run  # not recomputed at settle time
        assert updated.result == "cron reply"
        completed = [e for e in recorder.events if e.type == TaskEventType.COMPLETED]
        assert len(completed) == 1
        assert completed[0].payload["result"] == "cron reply"
        # The reply is durably persisted on the task row (GET /tasks/{id}).
        persisted = await store.get_task("prompt-cron-advance")
        assert persisted is not None
        assert persisted.result == "cron reply"

    @pytest.mark.asyncio
    async def test_notify_fire_persists_receipt_as_task_result(self, store):
        """A notify callback's receipt is persisted as the task's result —
        the durable record behind GET /tasks/{id}, not just the event payload."""
        scheduler = TaskScheduler(store=store)
        task = _due_cron_task("notify-receipt")
        await scheduler.add_task(task)

        async def callback(t: ScheduledTask) -> str:
            return "delivered via web event pipeline"

        await scheduler.start(on_due_task=callback)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        updated = await scheduler.get_task("notify-receipt")
        assert updated is not None
        assert updated.status == TaskStatus.PENDING
        assert updated.result == "delivered via web event pipeline"
        persisted = await store.get_task("notify-receipt")
        assert persisted is not None
        assert persisted.result == "delivered via web event pipeline"

    @pytest.mark.asyncio
    async def test_prompt_timeout_fails_once_with_error(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(
            bus=_make_bus(recorder), config=SimpleNamespace(prompt_timeout_seconds=1)
        )
        task = _prompt_once_task("prompt-timeout")
        await scheduler.add_task(task)

        async def forever(t: ScheduledTask) -> str:
            await asyncio.sleep(30)

        await scheduler.start(on_prompt_task=forever)
        try:
            settled = await _wait_for_status(scheduler, "prompt-timeout", TaskStatus.FAILED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.FAILED
        assert settled.error == "prompt timed out"
        failed = [e for e in recorder.events if e.type == TaskEventType.FAILED]
        assert len(failed) == 1
        assert failed[0].payload["error"] == "prompt timed out"
        assert task.id not in scheduler._inflight

    @pytest.mark.asyncio
    async def test_prompt_runner_exception_fails_once(self):
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        task = _prompt_once_task("prompt-exc")
        await scheduler.add_task(task)

        async def boom(t: ScheduledTask) -> str:
            raise RuntimeError("llm exploded")

        await scheduler.start(on_prompt_task=boom)
        try:
            settled = await _wait_for_status(scheduler, "prompt-exc", TaskStatus.FAILED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.FAILED
        assert settled.error == "llm exploded"
        failed = [e for e in recorder.events if e.type == TaskEventType.FAILED]
        assert len(failed) == 1
        assert failed[0].payload["error"] == "llm exploded"

    @pytest.mark.asyncio
    async def test_prompt_cron_failure_returns_pending_with_error(self, store):
        scheduler = TaskScheduler(store=store)
        now = datetime.now()
        task = _prompt_cron_task("prompt-cron-fail")
        task.next_run = now - timedelta(minutes=1)
        await scheduler.add_task(task)

        async def boom(t: ScheduledTask) -> str:
            raise RuntimeError("boom")

        await scheduler.start(on_prompt_task=boom)
        try:
            # Wait for the settle (error recorded), not the PENDING status —
            # the cron task is already PENDING before it fires.
            settled = await _wait_for_settled(scheduler, "prompt-cron-fail")
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.PENDING
        assert settled.error == "boom"
        assert settled.next_run is not None and settled.next_run > now
        persisted = await store.get_task("prompt-cron-fail")
        assert persisted is not None
        assert persisted.status == TaskStatus.PENDING
        assert persisted.error == "boom"
        assert persisted.next_run is not None and persisted.next_run > now

    @pytest.mark.asyncio
    async def test_prompt_without_runner_directly_fails(self):
        """start() without on_prompt_task settles prompt tasks synchronously:
        once → FAILED, cron → PENDING (aligned with notify's
        start(on_due_task=None) direct-complete)."""
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        once = _prompt_once_task("prompt-norunner-once")
        cron = _prompt_cron_task("prompt-norunner-cron")
        await scheduler.add_task(once)
        await scheduler.add_task(cron)

        await scheduler.start()  # no callbacks at all
        try:
            await asyncio.sleep(0.2)
        finally:
            await scheduler.stop()

        settled_once = await scheduler.get_task("prompt-norunner-once")
        assert settled_once is not None and settled_once.status == TaskStatus.FAILED
        assert settled_once.error == "prompt runner not configured"
        settled_cron = await scheduler.get_task("prompt-norunner-cron")
        assert settled_cron is not None and settled_cron.status == TaskStatus.PENDING
        assert settled_cron.error == "prompt runner not configured"
        assert once.id not in scheduler._inflight
        failed = [e for e in recorder.events if e.type == TaskEventType.FAILED]
        assert len(failed) == 2
        assert all(e.payload["error"] == "prompt runner not configured" for e in failed)

    @pytest.mark.asyncio
    async def test_inflight_removed_after_settlement(self):
        """_inflight contains the task id while executing and is discarded
        after settlement, driven by a controllable prompt runner."""
        scheduler = TaskScheduler()
        task = _prompt_once_task("prompt-inflight")
        await scheduler.add_task(task)

        entered = asyncio.Event()
        release = asyncio.Event()

        async def runner(t: ScheduledTask) -> str:
            entered.set()
            await release.wait()
            return "ok"

        await scheduler.start(on_prompt_task=runner)
        try:
            assert await _wait_for(entered.is_set)
            assert task.id in scheduler._inflight
            release.set()
            assert await _wait_for(lambda: task.id not in scheduler._inflight)
        finally:
            await scheduler.stop()

        updated = await scheduler.get_task("prompt-inflight")
        assert updated is not None and updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_prompt_cron_timeout_returns_pending_with_timeout_error(self):
        scheduler = TaskScheduler(config=SimpleNamespace(prompt_timeout_seconds=1))
        task = _prompt_cron_task("prompt-cron-timeout")
        await scheduler.add_task(task)

        async def forever(t: ScheduledTask) -> str:
            await asyncio.sleep(30)

        await scheduler.start(on_prompt_task=forever)
        try:
            settled = await _wait_for_settled(scheduler, "prompt-cron-timeout")
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.PENDING
        assert settled.error == "prompt timed out"

    @pytest.mark.asyncio
    async def test_stop_waits_for_inflight_prompt_tasks(self):
        """T13: shutdown must wait for in-flight prompt executions instead of
        cutting them off — the runner's reply still lands its COMPLETED verdict
        (and the persist/emit run while the loop is alive)."""
        scheduler = TaskScheduler()
        task = _prompt_once_task("prompt-stop-wait")
        await scheduler.add_task(task)

        entered = asyncio.Event()
        release = asyncio.Event()

        async def runner(t: ScheduledTask) -> str:
            entered.set()
            await release.wait()
            return "done during stop"

        await scheduler.start(on_prompt_task=runner)
        try:
            assert await _wait_for(entered.is_set)
            assert task.id in scheduler._inflight

            # stop() must block until the in-flight runner settles.
            stop_task = asyncio.create_task(scheduler.stop())
            await asyncio.sleep(0.1)
            assert not stop_task.done()
            release.set()
            await asyncio.wait_for(stop_task, timeout=5)
        finally:
            if scheduler.running:
                await scheduler.stop()

        updated = await scheduler.get_task("prompt-stop-wait")
        assert updated is not None and updated.status == TaskStatus.COMPLETED
        assert task.id not in scheduler._inflight

    @pytest.mark.asyncio
    async def test_stop_retrieves_exception_from_inflight_execution(self, caplog, monkeypatch):
        """T13 / Task 12 Minor 4: stop() awaits each in-flight execution task's
        result, so an unexpected background exception is retrieved (and logged)
        instead of leaking as 'Task exception was never retrieved'."""
        scheduler = TaskScheduler()
        task = _prompt_once_task("prompt-stop-exc")
        await scheduler.add_task(task)

        entered = asyncio.Event()
        release = asyncio.Event()

        async def runner(t: ScheduledTask) -> str:
            entered.set()
            await release.wait()
            return "ok"

        original_settle = scheduler._settle_prompt

        async def exploding_settle(*args: Any, **kwargs: Any) -> None:
            await original_settle(*args, **kwargs)
            raise RuntimeError("settle exploded")

        monkeypatch.setattr(scheduler, "_settle_prompt", exploding_settle)

        await scheduler.start(on_prompt_task=runner)
        try:
            assert await _wait_for(entered.is_set)
            stop_task = asyncio.create_task(scheduler.stop())
            await asyncio.sleep(0.1)
            assert not stop_task.done()
            with caplog.at_level("WARNING"):
                release.set()
                await asyncio.wait_for(stop_task, timeout=5)
        finally:
            if scheduler.running:
                await scheduler.stop()

        assert task.id not in scheduler._inflight
        # Minor-3 (review): the background exception is retrieved and logged
        # exactly once — by the done callback; stop()'s drain swallows without
        # a second log record.
        matches = [r for r in caplog.records if "settle exploded" in r.getMessage()]
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_prompt_cron_failure_scheduled_for_is_fired_slot(self):
        """T13 / Task 12 review item (b): a failed cron prompt round's FAILED
        payload.scheduled_for must point at the *fired* slot (the next_run that
        triggered this round), not the newly-advanced next_run — aligned with
        the notify path's captured slot."""
        recorder = _EventRecorder()
        scheduler = TaskScheduler(bus=_make_bus(recorder))
        fired = datetime.now() - timedelta(minutes=1)
        task = _prompt_cron_task("prompt-cron-slot")
        task.next_run = fired
        await scheduler.add_task(task)

        async def boom(t: ScheduledTask) -> str:
            raise RuntimeError("boom")

        await scheduler.start(on_prompt_task=boom)
        try:
            settled = await _wait_for_settled(scheduler, "prompt-cron-slot")
        finally:
            await scheduler.stop()

        failed = [e for e in recorder.events if e.type == TaskEventType.FAILED]
        assert len(failed) == 1
        assert failed[0].payload["scheduled_for"] == fired.isoformat()
        assert settled.next_run is not None and settled.next_run > fired
