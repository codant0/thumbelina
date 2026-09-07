"""Tests for thumbelina.api.routes.chat.apply_conversation_runtime permission wiring.

Task 6: verify the ``apply_conversation_runtime`` signature change threads the
``unattended`` keyword argument through to ``set_permission_mode`` and
``set_approval_context`` ContextVars per spec §8.

The runtime wiring lives in :mod:`thumbelina.api.routes.chat` (HTTP / WebSocket
/ WeChat share this helper) — the agent layer's gate (Task 8) consumes the
ContextVars this helper populates.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.tools.permissions import (
    PermissionMode,
    get_permission_mode,
    has_approver,
    set_approval_context,
    set_permission_mode,
)


def _make_runtime(
    *,
    permission: str | None = "full_access",
    workspace: str | None = None,
) -> tuple[Any, Any]:
    """Build a minimal ``(context, agent)`` pair for ``apply_conversation_runtime``.

    ``context`` exposes ``app.state`` (matches the contract used by the HTTP
    chat route, the WebSocket handler, and the WeChat channel shim). The
    endpoint/role/workspace helpers fail-soft on ``app.state.endpoint_manager``
    absence — Task 6 only exercises the new ``_apply_conversation_permission``
    path, which only needs ``agent.repository_manager.get_conversation``.
    """
    conv: dict[str, Any] = {"id": "c1"}
    if permission is not None:
        conv["permission"] = permission
    if workspace is not None:
        conv["workspace"] = workspace

    repository = MagicMock()
    repository.get_conversation = AsyncMock(return_value=conv)

    agent = MagicMock()
    agent.repository_manager = repository
    agent.workspace = workspace

    # ``app.state`` shim — only the keys actually consulted by
    # ``apply_conversation_runtime`` are populated. Endpoint/role resolution
    # tolerate None state attributes via early-return guards.
    context = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                endpoint_manager=None,
                config=None,
            )
        )
    )
    return context, agent


@pytest.fixture(autouse=True)
def _reset_context_vars():
    """Restore fail-closed defaults around each test.

    Permissions' ContextVars are process-global; without this fixture, a test
    that flips the mode would leak into siblings.
    """
    set_permission_mode(PermissionMode.READ_ONLY)
    set_approval_context(False)
    yield
    set_permission_mode(PermissionMode.READ_ONLY)
    set_approval_context(False)


@pytest.mark.asyncio
async def test_attended_keeps_full_access_and_grants_approver():
    """WS-style invocation: unattended=False keeps the requested mode + grants
    an approver so the gate may ``interrupt()`` on confirm-level calls.
    """
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(permission="full_access", workspace=None)

    await apply_conversation_runtime(context, agent, "c1", unattended=False)

    # full_access + no workspace → no unattended ceiling drop.
    assert get_permission_mode() is PermissionMode.FULL_ACCESS
    assert has_approver() is True


@pytest.mark.asyncio
async def test_unattended_no_workspace_drops_to_read_only():
    """无人值守 + 无工作区 → 全部模式降级到 read_only（spec §8 规则 2）。"""
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(permission="full_access", workspace=None)

    await apply_conversation_runtime(context, agent, "c1", unattended=True)

    assert get_permission_mode() is PermissionMode.READ_ONLY
    assert has_approver() is False


@pytest.mark.asyncio
async def test_unattended_with_workspace_caps_at_workspace_write():
    """无人值守 + 有工作区 → 全部模式上限为 workspace_write。"""
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(
        permission="global_write", workspace="C:/w/work"
    )

    await apply_conversation_runtime(context, agent, "c1", unattended=True)

    assert get_permission_mode() is PermissionMode.WORKSPACE_WRITE
    assert has_approver() is False


@pytest.mark.asyncio
async def test_unattended_auto_is_exempt():
    """auto 模式对无人值守上限显式豁免（spec §8 规则 2）。"""
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(permission="auto", workspace=None)

    await apply_conversation_runtime(context, agent, "c1", unattended=True)

    assert get_permission_mode() is PermissionMode.AUTO
    assert has_approver() is False


@pytest.mark.asyncio
async def test_unknown_mode_falls_back_to_full_access():
    """会话 permission 列为垃圾值时回退 full_access（plan Task 6 用例）。

    无审批者的入口用回退后的 full_access + 无工作区降级，最后仍是
    read_only；attended 入口则保留 full_access 以便前端历史值恢复路径。
    """
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(permission="bogus", workspace=None)

    await apply_conversation_runtime(context, agent, "c1", unattended=False)

    assert get_permission_mode() is PermissionMode.FULL_ACCESS
    assert has_approver() is True


@pytest.mark.asyncio
async def test_attended_full_access_with_workspace_stays_full_access():
    """attended 入口不做上限降级：有工作区的 full_access 仍为 full_access。"""
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(
        permission="full_access", workspace="C:/w/work"
    )

    await apply_conversation_runtime(context, agent, "c1", unattended=False)

    assert get_permission_mode() is PermissionMode.FULL_ACCESS
    assert has_approver() is True


@pytest.mark.asyncio
async def test_default_unattended_is_true_fail_closed():
    """未显式传 unattended 时默认为 True（plan Task 6 fail-closed 默认值）。"""
    from thumbelina.api.routes.chat import apply_conversation_runtime

    context, agent = _make_runtime(permission="full_access", workspace=None)

    # Intentionally omit the keyword: default must be True.
    await apply_conversation_runtime(context, agent, "c1")

    assert get_permission_mode() is PermissionMode.READ_ONLY
    assert has_approver() is False


@pytest.mark.asyncio
async def test_repository_exception_falls_back_to_full_access():
    """仓库异常时：默认 full_access + 未审批（无人值守降级），
    不会向上传播破坏本轮。"""
    from thumbelina.api.routes.chat import apply_conversation_runtime

    repository = MagicMock()
    repository.get_conversation = AsyncMock(side_effect=RuntimeError("db down"))
    agent = MagicMock()
    agent.repository_manager = repository
    agent.workspace = None
    context = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    await apply_conversation_runtime(context, agent, "c1", unattended=False)

    assert get_permission_mode() is PermissionMode.FULL_ACCESS
    assert has_approver() is True