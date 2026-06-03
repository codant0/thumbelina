"""Specialized subagent types: MonitorAgent and WorkerAgent."""

from __future__ import annotations

import asyncio
import logging

from thumbelina.subagents.base import SubagentStatus
from thumbelina.subagents.communication import SharedState
from thumbelina.subagents.manager import SubagentManager

logger = logging.getLogger(__name__)


class MonitorAgent:
    """A subagent that runs periodically to check a condition.

    Parameters
    ----------
    task:
        Description of the task to execute on each monitoring cycle.
    interval_seconds:
        How often (in seconds) the agent re-runs its task.
    manager:
        The SubagentManager used to create and run subagents.
    """

    def __init__(
        self,
        task: str,
        interval_seconds: float,
        manager: SubagentManager,
    ) -> None:
        self.task = task
        self.interval_seconds = interval_seconds
        self.manager = manager
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None
        self._shared_state = SharedState()
        self.last_result: str | None = None

    async def start(self) -> None:
        """Start the monitoring loop.

        Raises
        ------
        RuntimeError
            If the monitor is already running.
        """
        if self._running:
            raise RuntimeError("MonitorAgent is already running")
        self._running = True
        self._loop_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the monitoring loop gracefully."""
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _monitor_loop(self) -> None:
        """Internal loop: periodically create and run a subagent for the task."""
        while self._running:
            try:
                agent = await self.manager.create_agent(self.task)
                await self.manager.run_agent(agent.id)
                # Wait for the agent to finish
                for _ in range(100):
                    await asyncio.sleep(0.1)
                    updated = await self.manager.get_agent(agent.id)
                    if updated and updated.status in (
                        SubagentStatus.COMPLETED,
                        SubagentStatus.FAILED,
                        SubagentStatus.CANCELLED,
                    ):
                        self.last_result = updated.result if updated.result else updated.error
                        break
                # 将最新结果存入共享状态
                await self._shared_state.set(
                    "monitor_last_result",
                    self.last_result,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("MonitorAgent cycle failed: %s", exc)

            # Sleep for the interval, but check for cancellation
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise
            if not self._running:
                break


class WorkerAgent:
    """A subagent with progress reporting.

    Parameters
    ----------
    task:
        Description of the task to execute.
    manager:
        The SubagentManager used to create and run subagents.
    """

    def __init__(
        self,
        task: str,
        manager: SubagentManager,
    ) -> None:
        self.task = task
        self.manager = manager
        self._shared_state = SharedState()
        self._agent_id: str | None = None
        self._progress: float = 0.0
        self._status_message: str = "Not started"

    @property
    def progress(self) -> float:
        """Current progress from 0.0 to 1.0."""
        return self._progress

    @property
    def status_message(self) -> str:
        """Current status description."""
        return self._status_message

    async def run(self) -> str | None:
        """Create and run the subagent, tracking progress.

        Returns
        -------
        str | None
            The agent result, or None if failed.
        """
        self._progress = 0.0
        self._status_message = "Creating subagent..."

        try:
            agent = await self.manager.create_agent(self.task)
            self._agent_id = agent.id
            self._progress = 0.1
            self._status_message = "Running subagent..."

            await self.manager.run_agent(agent.id)
            self._progress = 0.5

            # 将进度写入共享状态
            await self._shared_state.set(f"worker_{agent.id}_progress", self._progress)
            await self._shared_state.set(f"worker_{agent.id}_status", self._status_message)

            # Poll for completion
            for _ in range(300):
                await asyncio.sleep(0.1)
                updated = await self.manager.get_agent(agent.id)
                if updated is None:
                    break
                if updated.status == SubagentStatus.COMPLETED:
                    self._progress = 1.0
                    self._status_message = "Completed"
                    self._last_result = updated.result
                    await self._shared_state.set(f"worker_{agent.id}_progress", 1.0)
                    await self._shared_state.set(f"worker_{agent.id}_status", "Completed")
                    return updated.result
                if updated.status in (SubagentStatus.FAILED, SubagentStatus.CANCELLED):
                    self._progress = 1.0
                    self._status_message = (
                        f"Failed: {updated.error}" if updated.error else "Cancelled"
                    )
                    await self._shared_state.set(f"worker_{agent.id}_progress", 1.0)
                    await self._shared_state.set(f"worker_{agent.id}_status", self._status_message)
                    return None

            self._status_message = "Timed out waiting for completion"
            return None
        except Exception as exc:
            self._status_message = f"Error: {exc}"
            self._progress = 1.0
            logger.warning("WorkerAgent failed: %s", exc)
            return None
