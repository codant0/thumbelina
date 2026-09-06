"""Per-conversation workspace context for built-in tools.

工作区通过 ``ContextVar`` 注入：``apply_conversation_runtime`` 在每个
会话各自的 asyncio 任务开头设置，工具函数内部读取；对 LLM 不可见，
也不会出现在工具 schema 中。无工作区（普通会话）时所有行为与既有一致。

当前会话 id 同样经 ``ContextVar`` 注入：``_run_generation`` 在每轮生成
任务开头设置，``CreateSubagentTool`` 读取并传给子 agent，使子 agent
生命周期事件能正确归属到发起会话（生成与连接解耦后必需）。
"""

from __future__ import annotations

import contextvars
from pathlib import Path

_current_workspace: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_workspace", default=None
)

_current_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_conversation_id", default=None
)


def set_workspace(workspace: str | None) -> None:
    """Set the workspace path for the current execution context."""
    _current_workspace.set(workspace)


def get_workspace() -> str | None:
    """Return the workspace path active in the current context, if any."""
    return _current_workspace.get()


def set_current_conversation_id(conversation_id: str | None) -> None:
    """Set the conversation id owning the current execution context."""
    _current_conversation_id.set(conversation_id)


def get_current_conversation_id() -> str | None:
    """Return the conversation id active in the current context, if any."""
    return _current_conversation_id.get()


def resolve_workspace_path(path: str) -> Path | None:
    """Resolve *path* against the active workspace, enforcing its boundary.

    With an active workspace only relative paths are accepted; they are
    resolved against the workspace root, and escapes are rejected.
    Returns ``None`` when no workspace is active (legacy behavior).
    Raises ``ValueError`` (message starts with 路径超出工作区) when the
    path is absolute or resolves outside the workspace.
    """
    workspace = _current_workspace.get()
    if not workspace:
        return None
    workspace_root = Path(workspace).resolve()
    target = Path(path)
    if target.is_absolute():
        raise ValueError(f"路径超出工作区 {workspace_root}: {path}")
    resolved = (workspace_root / target).resolve()
    if not resolved.is_relative_to(workspace_root):
        raise ValueError(f"路径超出工作区 {workspace_root}: {path}")
    return resolved
