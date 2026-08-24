"""Tests for shell execution tool."""

from __future__ import annotations

import platform

import pytest

from thumbelina.tools.shell import run_shell
from thumbelina.tools.workspace_context import set_workspace


@pytest.mark.asyncio
async def test_run_shell_echo():
    cmd = "echo hello" if platform.system() != "Windows" else "echo hello"
    result = await run_shell.ainvoke({"command": cmd})
    assert "hello" in result
    assert "exit code: 0" in result


@pytest.mark.asyncio
async def test_run_shell_invalid_command():
    result = await run_shell.ainvoke({"command": "nonexistent_command_xyz"})
    assert "exit code" in result or "Error" in result


@pytest.mark.asyncio
async def test_run_shell_uses_workspace_cwd(tmp_path):
    set_workspace(str(tmp_path))
    try:
        result = await run_shell.ainvoke({"command": 'python -c "import os; print(os.getcwd())"'})
        assert str(tmp_path) in result
    finally:
        set_workspace(None)
