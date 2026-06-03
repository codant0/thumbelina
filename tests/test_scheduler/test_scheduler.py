"""Tests for task scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from thumbelina.scheduler.scheduler import ScheduledTask, TaskScheduler, TaskStatus


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
        """Should mark task as CANCELLED when callback raises."""
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
        assert updated.status == TaskStatus.CANCELLED

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
