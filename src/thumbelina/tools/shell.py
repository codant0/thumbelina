"""Shell execution tool for the Thumbelina agent."""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool

from thumbelina.tools.workspace_context import get_workspace

_TIMEOUT = 30  # seconds


@tool
async def run_shell(command: str) -> str:
    """Execute a shell command and return stdout+stderr. Timeout: 30 seconds."""
    cwd = get_workspace()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            shell=True,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        exit_info = f"\n[exit code: {proc.returncode}]"
        if len(output) > 100_000:
            output = output[:100_000] + "\n... (truncated)"
        return output + exit_info
    except TimeoutError:
        return f"Error: Command timed out after {_TIMEOUT} seconds"
    except OSError as exc:
        return f"Error executing command: {exc}"
