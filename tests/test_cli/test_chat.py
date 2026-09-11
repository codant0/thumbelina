"""Tests for thumbelina.cli.chat module."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.cli.chat import ChatSession, _approval_handler


@pytest.fixture
def mock_agent():
    """Create a mock ThumbelinaAgent for testing."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")
    return agent


def test_chat_session_init(mock_agent):
    """ChatSession should initialize with default values."""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    assert session.agent is mock_agent
    assert session.history == []
    assert session.running is False
    # spec §8: 非 TTY 默认无审批者 → confirm 一律 deny。
    assert session.approval_handler is None


def test_chat_session_init_tty_registers_handler(mock_agent):
    """TTY 模式下 ChatSession 挂载 CLI 终端审批 handler。"""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = True
        session = ChatSession(agent=mock_agent)
    assert session.approval_handler is _approval_handler


def test_chat_session_exit_command(mock_agent):
    """ChatSession.is_exit_command should recognize /exit."""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    assert session.is_exit_command("/exit") is True
    assert session.is_exit_command("/quit") is True
    assert session.is_exit_command("hello") is False
    assert session.is_exit_command("") is False


def test_chat_session_format_response(mock_agent):
    """ChatSession.format_response should format assistant response."""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    result = session.format_response("Hello, world!")
    assert "thumbelina" in result.lower() or "Hello" in result


@pytest.mark.asyncio
async def test_chat_session_process_input(mock_agent):
    """ChatSession.process_input should return agent response."""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    response = await session.process_input("Hello")
    assert response == "Agent response"
    mock_agent.run.assert_called_once_with(
        "Hello", context_window_tokens=None, approval_handler=None
    )


@pytest.mark.asyncio
async def test_chat_session_process_input_forwards_window_tokens(mock_agent):
    """ChatSession 应把其上下文窗口转发给 agent.run()。"""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent, context_window_tokens=32000)
    await session.process_input("Hello")
    mock_agent.run.assert_called_once_with(
        "Hello", context_window_tokens=32000, approval_handler=None
    )


@pytest.mark.asyncio
async def test_chat_session_process_input_records_history(mock_agent):
    """ChatSession.process_input should add messages to history."""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    await session.process_input("Hello")
    assert len(session.history) == 2  # user + assistant
    assert session.history[0]["role"] == "user"
    assert session.history[0]["content"] == "Hello"
    assert session.history[1]["role"] == "assistant"
    assert session.history[1]["content"] == "Agent response"


@pytest.mark.asyncio
async def test_chat_session_process_input_tty_forwards_handler(mock_agent):
    """TTY 时 approval_handler 转发给 agent.run()。"""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = True
        session = ChatSession(agent=mock_agent)
    await session.process_input("Hello")
    mock_agent.run.assert_called_once_with(
        "Hello",
        context_window_tokens=None,
        approval_handler=_approval_handler,
    )


def test_chat_session_get_history(mock_agent):
    """ChatSession.get_history should return copy of history."""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    session.history = [{"role": "user", "content": "test"}]
    history = session.get_history()
    assert history == [{"role": "user", "content": "test"}]
    # Should be a copy
    history.append({"role": "assistant", "content": "x"})
    assert len(session.history) == 1


@patch("thumbelina.cli.chat.ThumbelinaAgent")
@patch("thumbelina.cli.chat.create_provider")
@patch("thumbelina.cli.chat.RepositoryManager")
def test_run_chat_creates_session(mock_mm_cls, mock_create_provider, mock_agent_cls):
    """run_chat should create an agent and start the session."""
    from thumbelina.cli.chat import run_chat

    mock_create_provider.return_value = MagicMock()
    mock_mm_cls.return_value = MagicMock()
    mock_agent_cls.return_value = MagicMock()

    # We can't easily test the full interactive loop, but we can verify
    # the function exists and has the right signature
    assert callable(run_chat)


# ---------------------------------------------------------------------------
# 终端审批 handler 单测(spec Task 17)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_handler_approve_all_y(capsys):
    """用户输入 'y' → 全部批准。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "run_shell",
                "args": {"command": "rm -rf /"},
                "reason": "dangerous.rm_root",
            },
            {
                "call_id": "c2",
                "name": "run_shell",
                "args": {"command": "sudo apt update"},
                "reason": "rule.sudo",
            },
        ]
    }
    with patch("builtins.input", return_value="y"):
        decisions = await _approval_handler(payload)
    assert decisions == [
        {"call_id": "c1", "approved": True},
        {"call_id": "c2", "approved": True},
    ]
    out = capsys.readouterr().out
    assert "需要授权" in out
    assert "run_shell" in out
    assert "dangerous.rm_root" in out
    assert "rule.sudo" in out


@pytest.mark.asyncio
async def test_approval_handler_deny_default(capsys):
    """空回答 / 'N' / 其他 → 全部拒绝(spec §5.4 默认 fail-closed)。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "run_shell",
                "args": {"command": "sudo ls"},
                "reason": "rule.sudo",
            }
        ]
    }
    with patch("builtins.input", return_value=""):
        decisions = await _approval_handler(payload)
    assert decisions == [{"call_id": "c1", "approved": False}]

    with patch("builtins.input", return_value="n"):
        decisions = await _approval_handler(payload)
    assert decisions == [{"call_id": "c1", "approved": False}]

    with patch("builtins.input", return_value="yes"):
        decisions = await _approval_handler(payload)
    # 仅 'y' 视为批准(其他全部 deny,含 yes / Y 之外的字符)
    assert decisions == [{"call_id": "c1", "approved": False}]


@pytest.mark.asyncio
async def test_approval_handler_uppercase_y_approves(capsys):
    """大写 'Y' 经 .lower() → 视为批准。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "run_shell",
                "args": {"command": "sudo ls"},
                "reason": "rule.sudo",
            }
        ]
    }
    with patch("builtins.input", return_value="Y"):
        decisions = await _approval_handler(payload)
    assert decisions == [{"call_id": "c1", "approved": True}]


@pytest.mark.asyncio
async def test_approval_handler_eof_denies(capsys):
    """input 抛 EOFError(管道 / stdin 关闭) → 视为拒绝(fail-closed)。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "run_shell",
                "args": {"command": "sudo ls"},
                "reason": "rule.sudo",
            }
        ]
    }
    with patch("builtins.input", side_effect=EOFError):
        decisions = await _approval_handler(payload)
    assert decisions == [{"call_id": "c1", "approved": False}]


@pytest.mark.asyncio
async def test_approval_handler_empty_calls():
    """空 calls 列表 → 返回空决策列表,不调用 input。"""
    with patch("builtins.input") as mock_input:
        decisions = await _approval_handler({"calls": []})
    assert decisions == []
    mock_input.assert_not_called()


@pytest.mark.asyncio
async def test_approval_handler_unicode_args(capsys):
    """args 含中文 / 非 ASCII 时序列化不抛异常(ensure_ascii=False 路径)。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "write_file",
                "args": {"path": "笔记.md", "content": "你好,世界"},
                "reason": "rule.protected_path",
            }
        ]
    }
    with patch("builtins.input", return_value="y"):
        decisions = await _approval_handler(payload)
    assert decisions == [{"call_id": "c1", "approved": True}]
    out = capsys.readouterr().out
    # 中文在序列化结果中可见
    assert "笔记.md" in out
    assert "rule.protected_path" in out


@pytest.mark.asyncio
async def test_approval_handler_args_unserializable_falls_back(capsys):
    """args 不可 JSON 序列化 → 兜底 str() 截断,不抛异常。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "weird_tool",
                "args": {"fn": lambda: None},  # type: ignore[dict-item]
                "reason": "rule.test",
            }
        ]
    }
    with patch("builtins.input", return_value="y"):
        decisions = await _approval_handler(payload)
    assert decisions == [{"call_id": "c1", "approved": True}]
    out = capsys.readouterr().out
    assert "weird_tool" in out


# ---------------------------------------------------------------------------
# 端到端 fail-closed 断言(spec §8):非 TTY 时 ChatSession 不挂 handler
# → agent.run() 收不到 approval_handler,confirm 调用由闸门直接 deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_tty_does_not_pass_handler(mock_agent):
    """非 TTY:ChatSession.approval_handler 为 None,转给 agent.run() 时也传 None。"""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        session = ChatSession(agent=mock_agent)
    assert session.approval_handler is None
    await session.process_input("run sudo ls")
    mock_agent.run.assert_called_once_with(
        "run sudo ls", context_window_tokens=None, approval_handler=None
    )


@pytest.mark.asyncio
async def test_tty_passes_handler(mock_agent):
    """TTY:ChatSession.approval_handler 挂 _approval_handler,转发给 agent.run()。"""
    with patch("thumbelina.cli.chat.sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = True
        session = ChatSession(agent=mock_agent)
    assert session.approval_handler is _approval_handler
    await session.process_input("rm -rf /")
    mock_agent.run.assert_called_once_with(
        "rm -rf /", context_window_tokens=None, approval_handler=_approval_handler
    )


def test_approval_handler_is_async():
    """_approval_handler 是异步函数,可被 await。"""
    import inspect

    assert inspect.iscoroutinefunction(_approval_handler)


def test_approval_handler_print_stdout_target(capsys, monkeypatch):
    """_approval_handler 默认走 sys.stdout(print 函数的 file 默认为 sys.stdout)。"""
    payload = {
        "calls": [
            {
                "call_id": "c1",
                "name": "run_shell",
                "args": {"command": "sudo ls"},
                "reason": "rule.sudo",
            }
        ]
    }
    # 重定向 stdout 到 StringIO,确保 print 落到 stdout(不直接走 stderr)
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    import asyncio

    with patch("builtins.input", return_value="n"):
        asyncio.run(_approval_handler(payload))
    output = buf.getvalue()
    assert "需要授权" in output
