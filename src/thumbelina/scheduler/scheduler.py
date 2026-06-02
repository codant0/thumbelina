"""Task scheduler for managing scheduled tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# How often the polling loop wakes up to check for due tasks (seconds).
_POLL_INTERVAL = 1.0


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
    """Scheduler for managing and executing scheduled tasks.

    Call :meth:`start` to begin the background polling loop, and
    :meth:`stop` to shut it down gracefully.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the background polling loop is active."""
        return self._running

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

    async def start(
        self,
        on_due_task: Callable[[ScheduledTask], Awaitable[None]] | None = None,
    ) -> None:
        """Start the background polling loop.

        Parameters
        ----------
        on_due_task:
            Optional async callback invoked for each due task.  The
            scheduler sets the task status to ``RUNNING`` before calling
            and to ``COMPLETED`` on success.

        Raises
        ------
        RuntimeError
            If the polling loop is already running.
        """
        if self._running:
            raise RuntimeError("Scheduler polling loop is already running")

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(on_due_task))

    async def stop(self) -> None:
        """Stop the background polling loop gracefully."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(
        self,
        on_due_task: Callable[[ScheduledTask], Awaitable[None]] | None,
    ) -> None:
        """Internal: periodically check for and execute due tasks."""
        while self._running:
            due = await self.get_due_tasks()
            for task in due:
                task.status = TaskStatus.RUNNING
                try:
                    if on_due_task is not None:
                        await on_due_task(task)
                    task.status = TaskStatus.COMPLETED
                except Exception as exc:
                    logger.warning("Scheduled task %s failed: %s", task.id, exc)
                    task.status = TaskStatus.CANCELLED
            await asyncio.sleep(_POLL_INTERVAL)
            # Re-check after sleep — stop() may have been called during sleep
            if not self._running:
                break
