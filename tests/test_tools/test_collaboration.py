from __future__ import annotations

import pytest

from thumbelina.tools.base import ToolCategory
from thumbelina.tools.collaboration import (
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


@pytest.mark.asyncio
async def test_create_subagent_ok():
    tool = CreateSubagentTool(manager=FakeManager())
    out = await tool._arun(task="do it")
    assert "Subagent created with ID a1" in out
    assert tool.category == ToolCategory.COLLABORATION


@pytest.mark.asyncio
async def test_create_subagent_runtime_error():
    tool = CreateSubagentTool(manager=FakeManager(fail=True))
    assert (await tool._arun(task="x")).startswith("Failed to create subagent: no slots")


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
