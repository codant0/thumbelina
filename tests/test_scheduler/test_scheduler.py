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
