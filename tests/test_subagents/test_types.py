"""Tests for specialized subagent types: MonitorAgent and WorkerAgent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.subagents.manager import SubagentManager
from thumbelina.subagents.types import MonitorAgent, WorkerAgent


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="Task completed")
    return provider


@pytest.fixture
def manager(mock_llm):
    """Create a SubagentManager."""
    return SubagentManager(llm_provider=mock_llm, max_agents=5)


class TestMonitorAgent:
    """Tests for MonitorAgent."""

    def test_class_exists(self):
        """MonitorAgent should be importable."""
        assert MonitorAgent is not None

    def test_create(self, manager):
        """Should create a MonitorAgent."""
        monitor = MonitorAgent(
            task="Check system health",
            interval_seconds=10.0,
            manager=manager,
        )
        assert monitor.task == "Check system health"
        assert monitor.interval_seconds == 10.0
        assert monitor.manager is manager

    def test_not_running_initially(self, manager):
        """Should not be running after creation."""
        monitor = MonitorAgent(task="test", interval_seconds=1.0, manager=manager)
        assert monitor.last_result is None

    @pytest.mark.asyncio
    async def test_start_stop(self, manager):
        """Should start and stop cleanly."""
        monitor = MonitorAgent(
            task="echo test",
            interval_seconds=0.2,
            manager=manager,
        )
        await monitor.start()
        # 短暂等待确保循环已启动
        await asyncio.sleep(0.05)
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_start_already_running_raises(self, manager):
        """Should raise RuntimeError if already running."""
        monitor = MonitorAgent(
            task="test",
            interval_seconds=1.0,
            manager=manager,
        )
        await monitor.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                await monitor.start()
        finally:
            await monitor.stop()

    @pytest.mark.asyncio
    async def test_executes_task_on_interval(self, manager):
        """Should execute the task on each interval."""
        monitor = MonitorAgent(
            task="test task",
            interval_seconds=0.15,
            manager=manager,
        )
        await monitor.start()
        # Wait for a couple of cycles
        await asyncio.sleep(0.4)
        await monitor.stop()

        # Should have created at least one agent
        agents = await manager.list_agents()
        assert len(agents) >= 1

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, manager):
        """Stop should be a no-op when not running."""
        monitor = MonitorAgent(task="test", interval_seconds=1.0, manager=manager)
        await monitor.stop()  # Should not raise


class TestWorkerAgent:
    """Tests for WorkerAgent."""

    def test_class_exists(self):
        """WorkerAgent should be importable."""
        assert WorkerAgent is not None

    def test_create(self, manager):
        """Should create a WorkerAgent."""
        worker = WorkerAgent(task="Process data", manager=manager)
        assert worker.task == "Process data"
        assert worker.manager is manager

    def test_initial_progress(self, manager):
        """Should start at 0.0 progress."""
        worker = WorkerAgent(task="test", manager=manager)
        assert worker.progress == 0.0

    def test_initial_status(self, manager):
        """Should have 'Not started' status initially."""
        worker = WorkerAgent(task="test", manager=manager)
        assert worker.status_message == "Not started"

    @pytest.mark.asyncio
    async def test_run_completes(self, manager):
        """Should complete and report 1.0 progress."""
        worker = WorkerAgent(task="test task", manager=manager)
        result = await worker.run()

        assert result == "Task completed"
        assert worker.progress == 1.0
        assert worker.status_message == "Completed"

    @pytest.mark.asyncio
    async def test_run_failure(self, mock_llm):
        """Should report failure status when LLM raises."""
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM error"))
        mgr = SubagentManager(llm_provider=mock_llm, max_agents=5)

        worker = WorkerAgent(task="failing task", manager=mgr)
        result = await worker.run()

        assert result is None
        assert worker.progress == 1.0
        assert "error" in worker.status_message.lower() or "failed" in worker.status_message.lower()
