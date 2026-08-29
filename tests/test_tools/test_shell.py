"""Tests for shell execution tool."""

from __future__ import annotations

import platform

import pytest

from thumbelina.tools.execution import RunShellTool
from thumbelina.tools.workspace_context import set_workspace

run_shell = RunShellTool()


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
        # 本机 shell 为 cmd.exe:外层单引号不是引用符,内层须用双引号包裹 -c 参数。
        result = await run_shell.ainvoke({"command": 'python -c "import os; print(os.getcwd())"'})
        assert str(tmp_path) in result
    finally:
        set_workspace(None)
