"""Task scheduler for managing scheduled tasks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    """Status of a scheduled task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """A scheduled task.

    Attributes
    ----------
    id:
        Unique identifier.
    description:
        Description of the task.
    scheduled_time:
        When the task should run.
    status:
        Current status of the task.
    result:
        Result of the task execution.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    scheduled_time: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None


class TaskScheduler:
    """Scheduler for managing and executing scheduled tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}

    async def add_task(self, task: ScheduledTask) -> None:
        """Add a task to the scheduler."""
        self._tasks[task.id] = task

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    async def list_tasks(self) -> list[ScheduledTask]:
        """List all tasks."""
        return list(self._tasks.values())

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.CANCELLED
        return True

    async def complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.COMPLETED

    async def get_due_tasks(self) -> list[ScheduledTask]:
        """Get tasks that are due to run."""
        now = datetime.now()
        return [
            task for task in self._tasks.values()
            if task.status == TaskStatus.PENDING and task.scheduled_time <= now
        ]
