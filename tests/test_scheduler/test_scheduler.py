"""Tests for task scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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
        persisted = await store.get_task("cron-fail")
        assert persisted is not None
        assert persisted.status == TaskStatus.PENDING
        assert persisted.error == "boom"

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
