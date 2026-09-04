from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.subagents.base import Subagent, SubagentStatus
from thumbelina.tools.base import ToolCategory
from thumbelina.tools.collaboration import (
    SUBAGENT_TOOL_TIMEOUT_SECONDS,
    CollaborationTool,
    CreateSubagentTool,
    ListSubagentsTool,
    make_collaboration_tools,
)


class FakeAgent:
    def __init__(self, id="a1", task="t", status_value="completed", result=None, error=None):
        self.id, self.task, self.result, self.error = id, task, result, error
        self.status = type("S", (), {"value": status_value})()


class FakeManager:
    """旧的最小 manager mock,保留 list 行为(create/run 默认成功)。"""

    def __init__(self, fail=False):
        self.fail, self.agents = fail, [FakeAgent()]

    async def create_agent(self, task):
        if self.fail:
            raise RuntimeError("no slots")
        return self.agents[0]

    async def run_agent(self, agent_id):
        pass

    async def list_agents(self):
        return self.agents


class EmptyManager:
    async def list_agents(self):
        return []


class _StatefulManager:
    """让测试可以逐步把 agent 推进到终态,模拟真实的 SubagentManager。"""

    def __init__(
        self, status_sequence: list[SubagentStatus], result: Any = "ok", error: str | None = None
    ):
        self.agent = Subagent(task="t", status=status_sequence[0])
        self.agent.result = result if status_sequence[-1] == SubagentStatus.COMPLETED else None
        self.agent.error = error if status_sequence[-1] == SubagentStatus.FAILED else None
        self._status_sequence = status_sequence
        self._poll_count = 0

    async def create_agent(self, task):
        return self.agent

    async def run_agent(self, agent_id):
        return None

    async def get_agent(self, agent_id):
        # 每次 poll 推进一个状态;序列耗尽时返回最后状态(终态)
        idx = min(self._poll_count, len(self._status_sequence) - 1)
        self.agent.status = self._status_sequence[idx]
        self._poll_count += 1
        return self.agent

    async def cancel_agent(self, agent_id):
        self.agent.status = SubagentStatus.CANCELLED
        return True


@pytest.mark.asyncio
async def test_create_subagent_waits_for_completion_and_returns_result():
    mgr = _StatefulManager(
        [SubagentStatus.PENDING, SubagentStatus.RUNNING, SubagentStatus.COMPLETED],
        result="审查通过",
    )
    tool = CreateSubagentTool(manager=mgr)
    out = await tool._arun(task="审查代码")
    assert "completed" in out
    assert "审查通过" in out
    assert tool.category == ToolCategory.COLLABORATION


@pytest.mark.asyncio
async def test_create_subagent_returns_error_on_failure():
    mgr = _StatefulManager(
        [SubagentStatus.RUNNING, SubagentStatus.FAILED],
        error="LLM unavailable",
    )
    tool = CreateSubagentTool(manager=mgr)
    out = await tool._arun(task="x")
    assert "failed" in out
    assert "LLM unavailable" in out


@pytest.mark.asyncio
async def test_create_subagent_handles_cancelled():
    mgr = _StatefulManager(
        [SubagentStatus.RUNNING, SubagentStatus.CANCELLED],
    )
    tool = CreateSubagentTool(manager=mgr)
    out = await tool._arun(task="x")
    assert "cancelled" in out


@pytest.mark.asyncio
async def test_create_subagent_runtime_error_on_create():
    tool = CreateSubagentTool(manager=FakeManager(fail=True))
    out = await tool._arun(task="x")
    assert out.startswith("Failed to create subagent: no slots")


@pytest.mark.asyncio
async def test_create_subagent_timeout_returns_status(monkeypatch):
    """把超时阈值临时调到 0,确保 polling 循环超时分支被命中。"""
    from thumbelina.tools import collaboration as col_mod

    monkeypatch.setattr(col_mod, "SUBAGENT_TOOL_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(col_mod, "SUBAGENT_TOOL_POLL_INTERVAL", 0.01)

    mgr = _StatefulManager([SubagentStatus.RUNNING])
    tool = CreateSubagentTool(manager=mgr)
    out = await tool._arun(task="x")
    assert "still running after 0s" in out
    assert "running" in out


@pytest.mark.asyncio
async def test_create_subagent_cancel_cancels_child(monkeypatch):
    """主 Agent 工具协程被 cancel 时,应当顺手把子 Agent 也置 cancelled,避免孤儿后台任务。"""
    from thumbelina.tools import collaboration as col_mod

    monkeypatch.setattr(col_mod, "SUBAGENT_TOOL_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(col_mod, "SUBAGENT_TOOL_POLL_INTERVAL", 0.01)

    real_mgr = MagicMock()
    real_mgr.create_agent = AsyncMock(
        return_value=Subagent(id="x1", task="t", status=SubagentStatus.PENDING)
    )
    real_mgr.run_agent = AsyncMock(return_value=None)
    real_mgr.get_agent = AsyncMock(
        return_value=Subagent(id="x1", task="t", status=SubagentStatus.RUNNING)
    )
    cancel_called = []
    real_mgr.cancel_agent = AsyncMock(side_effect=lambda _id: cancel_called.append(_id) or True)

    tool = CreateSubagentTool(manager=real_mgr)

    async def runner():
        await tool._arun(task="t")

    task = asyncio.create_task(runner())
    # 让等待循环跑起来,然后取消
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancel_called == ["x1"]


@pytest.mark.asyncio
async def test_list_subagents_empty_and_rows():
    t = ListSubagentsTool(manager=FakeManager())
    assert "ID: a1" in await t._arun()
    assert await ListSubagentsTool(manager=EmptyManager())._arun() == "No subagents found."


def test_tools_share_collaboration_base():
    assert issubclass(CreateSubagentTool, CollaborationTool)
    assert issubclass(ListSubagentsTool, CollaborationTool)
    assert ListSubagentsTool(manager=None).category == ToolCategory.COLLABORATION


def test_make_collaboration_tools_returns_two():
    assert len(make_collaboration_tools(FakeManager())) == 2


def test_subagent_tool_timeout_default_is_sane():
    """默认 5 分钟:覆盖大多数单次 LLM chat,又不会让主 Agent 无限卡死。"""
    assert 60 <= SUBAGENT_TOOL_TIMEOUT_SECONDS <= 600
