"""File operation tools for the Thumbelina agent."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB


@tool
async def read_file(path: str) -> str:
    """Read the contents of a file. Returns up to 1MB of text."""
    p = Path(path).resolve()
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
    p = Path(path).resolve()
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
    p = Path(path).resolve()
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
