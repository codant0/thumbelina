"""Tests for the tool-binding filter (belt) consumed by ``_call_model_node``.

Task 7: ``model.bind_tools()`` 在调 LLM 之前按当前 ``PermissionMode`` 过
滤工具列表。READ_ONLY 只暴露 ``READ_ONLY_TOOLS``；其它模式一律返回 True
（按 spec §6.1，bind 端不重复过滤 KNOWN_TOOLS，避免与闸门冲突）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from thumbelina.tools.permissions import (
    PermissionMode,
    is_tool_available,
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
def _reset_permission_mode():
    """Permissions' ContextVar 是进程级全局；隔离每个测试避免串扰。"""
    set_permission_mode(PermissionMode.READ_ONLY)
    yield
    set_permission_mode(PermissionMode.READ_ONLY)


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

