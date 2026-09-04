"""Tests for SubagentManager lifecycle event broadcasting."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.subagents.base import SubagentStatus
from thumbelina.subagents.manager import SubagentManager


@pytest.fixture
def mock_llm():
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="done")
    return provider


@pytest.fixture
def manager(mock_llm):
    return SubagentManager(llm_provider=mock_llm, max_agents=3)


class TestListenerRegistration:
    def test_add_listener_returns_unsubscribe(self, manager):
        received: list = []

        async def listener(_event):
            received.append(_event)

        unsubscribe = manager.add_listener(listener)
        assert callable(unsubscribe)
        unsubscribe()
        # calling twice is idempotent
        unsubscribe()
        assert len(manager._listeners) == 0

    def test_multiple_listeners(self, manager):
        unsub1 = manager.add_listener(lambda e: None)
        unsub2 = manager.add_listener(lambda e: None)
        assert len(manager._listeners) == 2
        unsub1()
        assert len(manager._listeners) == 1
        unsub2()
        assert len(manager._listeners) == 0


class TestLifecycleEvents:
    @pytest.mark.asyncio
    async def test_started_and_completed(self, manager):
        events: list = []

        async def listener(event):
            events.append(event)

        manager.add_listener(listener)
        agent = await manager.create_agent(task="hello")
        await manager.run_agent(agent.id)
        await asyncio.sleep(0.1)

        types = [e.type for e in events]
        assert types == ["subagent.started", "subagent.completed"]
        last = events[-1]
        assert last.id == agent.id
        assert last.task == "hello"
        assert last.status == SubagentStatus.COMPLETED
        assert last.result == "done"
        assert last.started_at is not None
        assert last.finished_at is not None

    @pytest.mark.asyncio
    async def test_failed_emits_failure(self, mock_llm):
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
        mgr = SubagentManager(llm_provider=mock_llm, max_agents=3)
        events: list = []

        async def listener(event):
            events.append(event)

        mgr.add_listener(listener)
        agent = await mgr.create_agent(task="x")
        await mgr.run_agent(agent.id)
        await asyncio.sleep(0.1)

        assert [e.type for e in events] == ["subagent.started", "subagent.failed"]
        assert events[-1].error == "boom"
        assert events[-1].status == SubagentStatus.FAILED

    @pytest.mark.asyncio
    async def test_cancel_emits_event(self, manager):
        events: list = []

        async def listener(event):
            events.append(event)

        manager.add_listener(listener)
        agent = await manager.create_agent(task="x")
        await manager.cancel_agent(agent.id)
        # cancel_agent is sync; emission is scheduled via create_task.
        # Give the loop a tick to dispatch the listener.
        await asyncio.sleep(0)

        types = [e.type for e in events]
        assert types == ["subagent.cancelled"]
        assert events[-1].id == agent.id
        assert events[-1].status == SubagentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_sync_listener_does_not_block(self, manager):
        """同步 listener 抛错也不应阻止 manager / 后续 listener。"""

        async def good(event):
            good.events.append(event)

        good.events = []

        def bad(event):
            raise RuntimeError("boom")

        manager.add_listener(bad)
        manager.add_listener(good)
        agent = await manager.create_agent(task="x")
        await manager.run_agent(agent.id)
        await asyncio.sleep(0.1)

        # good 仍然收到了 started + completed
        assert [e.type for e in good.events] == [
            "subagent.started",
            "subagent.completed",
        ]

    @pytest.mark.asyncio
    async def test_listener_exception_swallowed(self, manager):
        def bad(event):
            raise RuntimeError("nope")

        manager.add_listener(bad)
        agent = await manager.create_agent(task="x")
        # 不应抛出
        await manager.run_agent(agent.id)
        await asyncio.sleep(0.1)
        assert (await manager.get_agent(agent.id)).status == SubagentStatus.COMPLETED
