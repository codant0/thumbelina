"""Tests for subagent manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.tools import tool as lc_tool

from thumbelina.subagents.base import Subagent, SubagentStatus
from thumbelina.subagents.manager import SubagentManager


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="Task completed")
    return provider


@pytest.fixture
def manager(mock_llm):
    """Create a SubagentManager."""
    return SubagentManager(llm_provider=mock_llm, max_agents=3)


class TestSubagentManager:
    """Tests for the SubagentManager class."""

    def test_manager_class_exists(self):
        """SubagentManager should be importable."""
        assert SubagentManager is not None

    def test_manager_requires_llm_provider(self):
        """Should accept an LLM provider."""
        mock_llm = MagicMock()
        mgr = SubagentManager(llm_provider=mock_llm)
        assert mgr.llm_provider is mock_llm

    def test_manager_default_max_agents(self):
        """Should default to 5 max agents."""
        mock_llm = MagicMock()
        mgr = SubagentManager(llm_provider=mock_llm)
        assert mgr.max_agents == 5

    def test_manager_custom_max_agents(self):
        """Should accept custom max_agents."""
        mock_llm = MagicMock()
        mgr = SubagentManager(llm_provider=mock_llm, max_agents=10)
        assert mgr.max_agents == 10

    @pytest.mark.asyncio
    async def test_create_agent(self, manager):
        """Should create a subagent."""
        agent = await manager.create_agent(task="Test task")

        assert agent is not None
        assert agent.task == "Test task"
        assert agent.status == SubagentStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_agent_respects_limit(self, manager):
        """Should not create more agents than max_agents."""
        for _ in range(3):
            await manager.create_agent(task="Task")

        with pytest.raises(RuntimeError, match="Maximum"):
            await manager.create_agent(task="Too many")

    @pytest.mark.asyncio
    async def test_get_agent(self, manager):
        """Should be able to get an agent by ID."""
        agent = await manager.create_agent(task="Test")
        result = await manager.get_agent(agent.id)

        assert result is not None
        assert result.id == agent.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent(self, manager):
        """Should return None for non-existent agent."""
        result = await manager.get_agent("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_agents(self, manager):
        """Should list all agents."""
        await manager.create_agent(task="Task 1")
        await manager.create_agent(task="Task 2")

        agents = await manager.list_agents()
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, manager):
        """Should return empty list when no agents."""
        agents = await manager.list_agents()
        assert agents == []

    @pytest.mark.asyncio
    async def test_cancel_agent(self, manager):
        """Should be able to cancel an agent."""
        agent = await manager.create_agent(task="Test")
        result = await manager.cancel_agent(agent.id)

        assert result is True
        updated = await manager.get_agent(agent.id)
        assert updated.status == SubagentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, manager):
        """Should return False when cancelling non-existent agent."""
        result = await manager.cancel_agent("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_run_agent(self, manager):
        """Should run an agent and complete successfully."""
        agent = await manager.create_agent(task="Summarize: hello world")
        await manager.run_agent(agent.id)

        # Should be RUNNING immediately after run_agent returns
        updated = await manager.get_agent(agent.id)
        assert updated.status == SubagentStatus.RUNNING

        # Let the background task complete
        await asyncio.sleep(0.1)

        done = await manager.get_agent(agent.id)
        assert done.status == SubagentStatus.COMPLETED
        assert done.result == "Task completed"

    @pytest.mark.asyncio
    async def test_run_agent_nonexistent(self, manager):
        """Should raise ValueError for non-existent agent."""
        with pytest.raises(ValueError, match="Agent not found"):
            await manager.run_agent("nonexistent")

    @pytest.mark.asyncio
    async def test_run_agent_already_running(self, manager):
        """Should raise ValueError if agent is not PENDING."""
        agent = await manager.create_agent(task="Test")
        await manager.run_agent(agent.id)

        with pytest.raises(ValueError, match="cannot be run"):
            await manager.run_agent(agent.id)

    @pytest.mark.asyncio
    async def test_run_agent_cancelled(self, manager):
        """Should raise ValueError if agent was cancelled."""
        agent = await manager.create_agent(task="Test")
        await manager.cancel_agent(agent.id)

        with pytest.raises(ValueError, match="cannot be run"):
            await manager.run_agent(agent.id)

    @pytest.mark.asyncio
    async def test_run_agent_failure(self, mock_llm):
        """Should mark agent as FAILED when LLM raises."""
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        mgr = SubagentManager(llm_provider=mock_llm, max_agents=3)

        agent = await mgr.create_agent(task="Test")
        await mgr.run_agent(agent.id)

        await asyncio.sleep(0.1)

        done = await mgr.get_agent(agent.id)
        assert done.status == SubagentStatus.FAILED
        assert "LLM down" in done.error


class TestSubagent:
    """Tests for the Subagent class."""

    def test_subagent_class_exists(self):
        """Subagent should be importable."""
        assert Subagent is not None

    def test_subagent_create(self):
        """Should create a Subagent."""
        agent = Subagent(id="a1", task="Test task")
        assert agent.id == "a1"
        assert agent.task == "Test task"
        assert agent.status == SubagentStatus.PENDING

    def test_subagent_default_status(self):
        """Should default to PENDING status."""
        agent = Subagent(id="a1", task="Test")
        assert agent.status == SubagentStatus.PENDING

    def test_subagent_status_enum(self):
        """SubagentStatus should have expected values."""
        assert SubagentStatus.PENDING == "pending"
        assert SubagentStatus.RUNNING == "running"
        assert SubagentStatus.COMPLETED == "completed"
        assert SubagentStatus.FAILED == "failed"
        assert SubagentStatus.CANCELLED == "cancelled"


# ---------------------------------------------------------------------------
# 工具循环模式(2026-09-06 修复):子 agent 绑定只读工具多轮执行,
# 不再是一次无工具 chat;伪工具语法文本被识别为失败而非结果。
# ---------------------------------------------------------------------------


class _ScriptedChatModel(BaseChatModel):
    """按脚本依次弹出响应的最小 chat model(工具绑定默认支持)。"""

    responses: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


@lc_tool
def probe_tool(dummy: str = "") -> str:
    """probe returns a fixed result"""
    return "PROBE_RESULT"


async def _wait_terminal(manager, agent_id, timeout=5.0):
    """轮询直到子 agent 到达终态,返回终态 Subagent。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        current = await manager.get_agent(agent_id)
        assert current is not None
        if current.status in (
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.CANCELLED,
        ):
            return current
        assert asyncio.get_event_loop().time() < deadline, "subagent did not finish"
        await asyncio.sleep(0.01)


class TestSubagentToolLoop:
    """set_tools 注入工具后的循环执行路径。"""

    @pytest.mark.asyncio
    async def test_tool_loop_executes_tools_and_returns_final_result(self, manager):
        manager.set_tools([probe_tool])
        manager.llm_provider.chat_model = _ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "probe_tool",
                            "args": {"dummy": "x"},
                            "id": "c1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="final answer cites PROBE_RESULT"),
            ]
        )

        agent = await manager.create_agent(task="use the probe")
        await manager.run_agent(agent.id)
        current = await _wait_terminal(manager, agent.id)

        assert current.status == SubagentStatus.COMPLETED
        assert current.result == "final answer cites PROBE_RESULT"

    @pytest.mark.asyncio
    async def test_tool_loop_round_limit_wraps_up_with_conclusion(self, manager):
        """达到轮次上限:强制无工具收束,返回'标注 + 基于证据的结论'。"""
        manager.set_tools([probe_tool])
        manager.max_rounds = 3
        manager.llm_provider.chat_model = _ScriptedChatModel(
            responses=[
                *[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "probe_tool", "args": {}, "id": f"c{i}", "type": "tool_call"}
                        ],
                    )
                    for i in range(3)
                ],
                AIMessage(content="concluded: probe always returns PROBE_RESULT"),
            ]
        )

        agent = await manager.create_agent(task="loop forever")
        await manager.run_agent(agent.id)
        current = await _wait_terminal(manager, agent.id)

        assert current.status == SubagentStatus.COMPLETED
        assert "tool limit" in current.result
        assert "concluded" in current.result

    @pytest.mark.asyncio
    async def test_tool_loop_inherits_workspace_context(self, manager, tmp_path):
        """子 agent 的 create_task 上下文继承会话工作区(ContextVar)。"""
        from thumbelina.tools.workspace_context import get_workspace, set_workspace

        seen: list = []

        class _WsProbeTool(BaseTool):
            name: str = "ws_probe"
            description: str = "probe active workspace"

            def _run(self) -> str:  # pragma: no cover - 同步路径不使用
                return "WS=none"

            async def _arun(self) -> str:
                seen.append(get_workspace())
                return "probed"

        manager.set_tools([_WsProbeTool()])
        set_workspace(str(tmp_path))
        manager.llm_provider.chat_model = _ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ws_probe", "args": {}, "id": "c1", "type": "tool_call"}],
                ),
                AIMessage(content="done"),
            ]
        )

        agent = await manager.create_agent(task="probe workspace")
        await manager.run_agent(agent.id)
        current = await _wait_terminal(manager, agent.id)

        assert current.status == SubagentStatus.COMPLETED
        # 工具在子 agent 任务里观察到的工作区 == 派发会话设置的工作区。
        assert seen == [str(tmp_path)]

    @pytest.mark.asyncio
    async def test_model_without_bind_tools_falls_back_to_single_shot(self, manager):
        """不支持 bind_tools 的模型自动退回单轮 chat 模式。"""

        class _NoBindModel(_ScriptedChatModel):
            def bind_tools(self, tools, **kwargs):
                raise NotImplementedError("no tools")

        manager.set_tools([probe_tool])
        manager.llm_provider.chat_model = _NoBindModel(responses=[AIMessage(content="x")])
        manager.llm_provider.chat = AsyncMock(return_value="single shot answer")

        agent = await manager.create_agent(task="task")
        await manager.run_agent(agent.id)
        current = await _wait_terminal(manager, agent.id)

        assert current.status == SubagentStatus.COMPLETED
        assert current.result == "single shot answer"


class TestSingleShotPseudoToolGuard:
    """无工具单轮模式必须拒绝伪工具语法文本(2026-09-06 事故根因之一)。"""

    @pytest.mark.asyncio
    async def test_pseudo_tool_text_marks_subagent_failed(self, manager):
        manager.llm_provider.chat = AsyncMock(
            return_value=(
                "我将对文档进行评审。" + chr(10)
                + "<read_file>" + chr(10)
                + "<path>x.md</path>" + chr(10)
                + "</read_file>"
            )
        )

        agent = await manager.create_agent(task="review the doc")
        await manager.run_agent(agent.id)
        current = await _wait_terminal(manager, agent.id)

        assert current.status == SubagentStatus.FAILED
        assert "pseudo tool-call" in (current.error or "")

    @pytest.mark.asyncio
    async def test_plain_result_still_completes(self, manager):
        manager.llm_provider.chat = AsyncMock(return_value="评审结论:设计合理。")

        agent = await manager.create_agent(task="review")
        await manager.run_agent(agent.id)
        current = await _wait_terminal(manager, agent.id)

        assert current.status == SubagentStatus.COMPLETED
        assert current.result == "评审结论:设计合理。"
