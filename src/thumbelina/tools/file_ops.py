"""File operation tools for the Thumbelina agent."""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from thumbelina.tools.workspace_context import resolve_workspace_path

_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
_SEARCH_MAX_HITS = 50
_SEARCH_MAX_LINE = 500
_SEARCH_MAX_FILE = 1 * 1024 * 1024


def _resolve_target(path: str) -> Path:
    """解析路径；有工作区时按工作区根解析并强制边界，无则保持原行为。"""
    resolved = resolve_workspace_path(path)
    if resolved is None:
        return Path(path).resolve()
    return resolved


@tool
async def read_file(path: str) -> str:
    """Read the contents of a file. Returns up to 1MB of text."""
    try:
        p = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    if not p.exists():
        return f"Error: File not found: {path}"
    if not p.is_file():
        return f"Error: Not a file: {path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > _MAX_FILE_SIZE:
            return content[:_MAX_FILE_SIZE] + "\n... (truncated at 1MB)"
        return content
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except OSError as exc:
        return f"Error reading file: {exc}"


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


@tool
async def list_directory(path: str = ".") -> str:
    """List files and directories in the given path."""
    try:
        p = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    if not p.exists():
        return f"Error: Directory not found: {path}"
    if not p.is_dir():
        return f"Error: Not a directory: {path}"
    try:
        entries = sorted(p.iterdir())
        lines = []
        for entry in entries:
            kind = "d" if entry.is_dir() else "f"
            lines.append(f"[{kind}] {entry.name}")
        if not lines:
            return "(empty directory)"
        return "\n".join(lines)
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except OSError as exc:
        return f"Error listing directory: {exc}"


@tool
async def search_files(pattern: str, path: str = ".") -> str:
    """Search for a regex pattern in files under the given path.

    Returns up to 50 matches as 'path:line: content' lines. Binary files
    and files larger than 1MB are skipped.
    """
    try:
        root = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    if not root.exists():
        return f"Error: Directory not found: {path}"
    if not root.is_dir():
        return f"Error: Not a directory: {path}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: Invalid pattern: {exc}"
    hits: list[str] = []
    try:
        for entry in root.rglob("*"):
            # Symlinks are untrusted: they can point outside the workspace,
            # leaking external content through rglob. Skip them entirely.
            if entry.is_symlink():
                continue
            if not entry.is_file():
                continue
            if entry.stat().st_size > _SEARCH_MAX_FILE:
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="ignore")
            except (PermissionError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{entry}:{lineno}: {line[:_SEARCH_MAX_LINE]}")
                if len(hits) >= _SEARCH_MAX_HITS:
                    break
            if len(hits) >= _SEARCH_MAX_HITS:
                break
    except (PermissionError, OSError) as exc:
        return f"Error searching: {exc}"
    if not hits:
        return f"No matches for {pattern!r} under {path}"
    return "\n".join(hits)
