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


@pytest.mark.asyncio
async def test_run_shell_falls_back_to_thread_when_loop_lacks_subprocess(monkeypatch):
    """Windows 下 uvicorn --reload 强制 SelectorEventLoop(不支持 asyncio
    子进程):create_subprocess_shell 抛 NotImplementedError 时应兜底到
    线程池执行,输出契约(echo 结果 + exit code 标记)不变。"""
    import asyncio

    async def _raise(*args, **kwargs):
        raise NotImplementedError

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _raise)
    result = await run_shell._execute("echo hello")
    assert "hello" in result
    assert "exit code: 0" in result


@pytest.mark.asyncio
async def test_run_shell_fallback_timeout_still_kills(monkeypatch):
    """线程池兜底路径同样有超时熔断,且文案与 asyncio 路径一致。"""
    import asyncio

    from thumbelina.tools import execution

    async def _raise(*args, **kwargs):
        raise NotImplementedError

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _raise)
    monkeypatch.setattr(execution, "_TIMEOUT", 1)
    cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
    result = await run_shell._execute(cmd)
    assert "timed out after 1 seconds" in result
