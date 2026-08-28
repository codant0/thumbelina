"""File operation tools for the Thumbelina agent.

读/列目录/搜索已迁入 :mod:`thumbelina.tools.perception`;
``write_file`` 待 Task 4 迁入 execution.py。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from thumbelina.tools.workspace_context import resolve_workspace_path


def _resolve_target(path: str) -> Path:
    """解析路径；有工作区时按工作区根解析并强制边界，无则保持原行为。"""
    resolved = resolve_workspace_path(path)
    if resolved is None:
        return Path(path).resolve()
    return resolved


@tool
async def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    try:
        p = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except OSError as exc:
        return f"Error writing file: {exc}"
