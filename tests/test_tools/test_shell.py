"""Tests for shell execution tool."""

from __future__ import annotations

import platform

import pytest

from thumbelina.tools.shell import run_shell


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
