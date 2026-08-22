"""Tests for workspace context building and runtime injection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thumbelina.agent.graph import build_workspace_context


def test_build_workspace_context_none():
    assert build_workspace_context(None) is None
    assert build_workspace_context("") is None


def test_build_workspace_context_contains_path_and_snapshot(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    ctx = build_workspace_context(str(tmp_path))
    assert ctx is not None
    assert str(tmp_path) in ctx
    assert "pyproject.toml" in ctx
    assert "禁止越界" in ctx


def test_build_workspace_context_missing_dir_degrades_to_path(tmp_path):
    missing = str(tmp_path / "gone")
    ctx = build_workspace_context(missing)
    assert ctx is not None
    assert missing in ctx


@pytest.mark.asyncio
async def test_apply_conversation_runtime_sets_workspace(tmp_path):
    from thumbelina.api.routes.chat import apply_conversation_runtime
    from thumbelina.tools.workspace_context import get_workspace, set_workspace

    repo = SimpleNamespace(
        get_conversation=AsyncMock(return_value={"role": None, "workspace": str(tmp_path)})
    )
    agent = SimpleNamespace(
        repository_manager=repo, role="assistant", role_prompt="x", workspace=None
    )
    context = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(endpoint_manager=None))
    )
    try:
        await apply_conversation_runtime(context, agent, "cid")
        assert agent.workspace == str(tmp_path)
        assert get_workspace() == str(tmp_path)
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_apply_conversation_runtime_without_workspace(tmp_path):
    from thumbelina.api.routes.chat import apply_conversation_runtime
    from thumbelina.tools.workspace_context import get_workspace, set_workspace

    repo = SimpleNamespace(
        get_conversation=AsyncMock(return_value={"role": None, "workspace": None})
    )
    agent = SimpleNamespace(
        repository_manager=repo, role="assistant", role_prompt="x", workspace=None
    )
    context = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(endpoint_manager=None))
    )
    try:
        await apply_conversation_runtime(context, agent, "cid")
        assert agent.workspace is None
        assert get_workspace() is None
    finally:
        set_workspace(None)
