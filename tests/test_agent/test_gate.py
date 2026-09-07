"""Tests for the tool-binding filter (belt) and the execution gate (Task 7+8).

Task 7: ``model.bind_tools()`` 在调 LLM 之前按当前 ``PermissionMode`` 过
滤工具列表。READ_ONLY 只暴露 ``READ_ONLY_TOOLS``；其它模式一律返回 True
（按 spec §6.1，bind 端不重复过滤 KNOWN_TOOLS，避免与闸门冲突）。

Task 8: ``ThumbelinaAgent._permission_gate`` 节点首行闸门裁决：
- READ_ONLY → 全量 deny（合成 ToolMessage）；
- confirm + 无审批者 → 无人值守路径直接拒绝（绝不 interrupt）；
- confirm + 有审批者 → 调 ``langgraph.types.interrupt``；首过抛出 GraphInterrupt，
  resume 后按决策列表放行/拒绝；
- AUTO 模式 → confirm 命中转为 ``auto_allowed`` allow。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from thumbelina.tools.permissions import (
    PermissionMode,
    is_tool_available,
    set_approval_context,
    set_permission_mode,
)


def test_read_only_hides_mutating_tools() -> None:
    """READ_ONLY 模式：只读工具放行，写/执行工具一律隐藏。"""
    assert is_tool_available(PermissionMode.READ_ONLY, "read_file") is True
    assert is_tool_available(PermissionMode.READ_ONLY, "run_shell") is False
    assert is_tool_available(PermissionMode.READ_ONLY, "schedule_task") is False


def test_other_modes_expose_all_known() -> None:
    """非 READ_ONLY 模式：``is_tool_available`` 一律放行（闸门/工具级安全复核把关）。"""
    for mode in (
        PermissionMode.WORKSPACE_WRITE,
        PermissionMode.GLOBAL_WRITE,
        PermissionMode.FULL_ACCESS,
        PermissionMode.AUTO,
    ):
        assert is_tool_available(mode, "run_shell") is True


@pytest.fixture(autouse=True)
def _reset_permission_context():
    """Permissions' 两个 ContextVar 是进程级全局；隔离每个测试避免串扰。"""
    set_permission_mode(PermissionMode.READ_ONLY)
    set_approval_context(False)
    yield
    set_permission_mode(PermissionMode.READ_ONLY)
    set_approval_context(False)


@pytest.mark.asyncio
async def test_call_model_node_binds_only_read_only_tools_in_read_only_mode() -> None:
    """READ_ONLY 模式下 ``_call_model_node`` 调 LLM 时只 bind 只读工具。

    验证图节点真的消费了 ``is_tool_available``：mock 一个 ``bind_tools`` 把
    传入的工具列表原样回吐，断言非 READ_ONLY_TOOLS 中的 ``run_shell`` 不在
    绑定列表里。
    """
    from thumbelina.agent.graph import ThumbelinaAgent

    @tool
    async def run_shell(command: str) -> str:
        """Run a shell command."""
        return command

    bound_model = MagicMock()
    bound_model.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    captured: dict = {}

    def _capture(tools):
        captured["tools"] = tools
        return bound_model

    mock_provider = MagicMock()
    mock_provider.chat_model = MagicMock()
    mock_provider.chat_model.bind_tools.side_effect = _capture

    # READ_ONLY 已是默认，但显式声明意图；同时确保 ``run_shell`` 不会
    # 因为任何上下文副作用漏入。
    set_permission_mode(PermissionMode.READ_ONLY)

    agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[run_shell])
    # ``_call_model_node`` 是图节点；直接调它即可绕开整张图，聚焦 bind_tools
    # 入口。空 messages 让 ensure_tool_pairing 短路，但 bind_tools 仍会被调。
    await agent._call_model_node({"messages": []})

    assert "tools" in captured, "bind_tools should have been invoked"
    bound_names = {t.name for t in captured["tools"]}
    # ``run_shell`` 是变更工具，READ_ONLY 必须过滤掉。
    assert "run_shell" not in bound_names
    # 内置 notify 工具在 READ_ONLY_TOOLS 中，应保留。
    assert "notify_user_by_channel" in bound_names


# ---------------------------------------------------------------------------
# Task 8：执行闸门（_permission_gate）
# ---------------------------------------------------------------------------


@pytest.fixture
def make_agent():
    """构造一个最小 ThumbelinaAgent：只带 ``run_shell`` 工具，无 checkpointer。

    闸门单测不需要真实图/LLM —— 直接调 ``_permission_gate`` 方法。LLM
    provider 用 MagicMock 占位即可，``agent.tools`` 不参与裁决。
    """
    from thumbelina.agent.graph import ThumbelinaAgent

    @tool
    async def run_shell(command: str) -> str:
        """Run a shell command."""
        return command

    mock_provider = MagicMock()
    mock_provider.chat_model = MagicMock()
    mock_provider.chat_model.bind_tools.return_value = mock_provider.chat_model

    def _factory(tools=None):
        return ThumbelinaAgent(llm_provider=mock_provider, tools=list(tools or [run_shell]))

    return _factory


@pytest.mark.asyncio
async def test_gate_denies_run_shell_in_read_only(make_agent) -> None:
    """READ_ONLY + 无审批者：run_shell 拒为 denied ToolMessage；verdict 映射 denied。"""
    agent = make_agent()
    set_permission_mode(PermissionMode.READ_ONLY)
    set_approval_context(False)

    calls = [{"name": "run_shell", "args": {"command": "ls"}, "id": "c1"}]
    exec_calls, verdicts, denied = await agent._permission_gate(calls)

    assert exec_calls == []
    assert len(denied) == 1
    assert denied[0].tool_call_id == "c1"
    assert "权限拒绝" in denied[0].content
    assert verdicts["c1"]["verdict"] == "denied"


@pytest.mark.asyncio
async def test_gate_confirm_unattended_auto_allowed_vs_denied(make_agent) -> None:
    """confirm 命中：AUTO 标 auto_allowed；FULL_ACCESS + 无审批者直接拒绝（绝不 interrupt）。"""
    agent = make_agent()

    calls = [{"name": "run_shell", "args": {"command": "sudo ls"}, "id": "c1"}]

    # AUTO：confirm 自动放行（auto_allowed=True），verdict=auto_allowed。
    set_permission_mode(PermissionMode.AUTO)
    set_approval_context(False)
    _, verdicts, denied = await agent._permission_gate(calls)
    assert denied == []
    assert verdicts["c1"]["verdict"] == "auto_allowed"
    assert verdicts["c1"]["reason"] == "confirm.sudo"

    # FULL_ACCESS + 无审批者（run() 路径）：confirm 直接拒绝，绝不调 interrupt。
    set_permission_mode(PermissionMode.FULL_ACCESS)
    set_approval_context(False)
    _, verdicts, denied = await agent._permission_gate(calls)
    assert len(denied) == 1
    assert denied[0].tool_call_id == "c1"
    assert "权限拒绝" in denied[0].content
    assert verdicts["c1"]["verdict"] == "denied"


@pytest.mark.asyncio
async def test_gate_confirm_attended_interrupts_then_settles(make_agent, monkeypatch) -> None:
    """confirm + 有审批者：首过 interrupt(payload) 上抛 GraphInterrupt。

    Resume 后同一次调用内完成结算。

    用 ``monkeypatch`` 把 ``langgraph.types.interrupt`` 替换为本地 ``fake_interrupt``：
    - 第一次调用时把 payload 存进 state 并抛哨兵异常（模拟 GraphInterrupt 行为）；
    - 第二次调用（resume）返回审批决策列表；闸门据此把 call 加入 exec_calls。

    验证：闸门 payload 里含归一化命令 args_display（spec §4.6），以及首过
    任何执行前上抛（trajectory/record_tool_call 不应在此前触发）。
    """
    import langgraph.types as lt

    agent = make_agent()
    set_permission_mode(PermissionMode.FULL_ACCESS)
    set_approval_context(True)
    calls = [{"name": "run_shell", "args": {"command": "sudo ls"}, "id": "c1"}]

    state: dict = {}

    class _FirstPassError(Exception):
        """模拟 GraphInterrupt：首过任何执行前抛出。"""

    def fake_interrupt(payload):
        if not state:
            state["payload"] = payload
            raise _FirstPassError()
        # resume 值：批准 c1
        return [{"call_id": "c1", "approved": True}]

    # 闸门内部 ``from langgraph.types import interrupt``，monkeypatch
    # ``langgraph.types.interrupt`` 生效。
    monkeypatch.setattr(lt, "interrupt", fake_interrupt)

    # 首过：任何执行前上抛（无 trajectory / 无 tool_start / 无 tool_node）。
    with pytest.raises(_FirstPassError):
        await agent._permission_gate(calls)

    # payload 应含 reason 与归一化命令（spec §4.6）。
    assert state["payload"]["calls"][0]["reason"] == "confirm.sudo"
    assert state["payload"]["calls"][0]["args_display"] == "sudo ls"

    # resume：同一次方法调用内完成结算 —— exec_calls 含 c1，verdict=confirmed。
    exec_calls, verdicts, denied = await agent._permission_gate(calls)
    assert len(exec_calls) == 1
    assert exec_calls[0]["id"] == "c1"
    assert denied == []
    assert verdicts["c1"]["verdict"] == "confirmed"

