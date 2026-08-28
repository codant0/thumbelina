"""执行工具:副作用 + 强制安全审查/结果自验证(spec §4.3/§5)。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from abc import abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from thumbelina.tools.base import (
    Allow,
    Confirm,
    Ok,
    Reject,
    Suspect,
    ThumbelinaBaseTool,
    ToolCategory,
)
from thumbelina.tools.workspace_context import (
    get_workspace,
    resolve_workspace_path,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 30

DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|--recursive)\s+/(\s|$)", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bdd\b[^\n]*\bof=/dev/", re.I),
    re.compile(r":\(\)\s*{", re.I),                      # fork 炸弹头部
    re.compile(r"\bshutdown\b|\breboot\b|\bpoweroff\b", re.I),
    re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh", re.I),  # 管道执行
    re.compile(r">\s*/dev/[a-z]", re.I),  # 无 \b:兼容「空格 + >」重定向(如 echo x > /dev/sda)
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/(\s|$)", re.I),
]

CONFIRM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bgit\s+push\s+--force|\bgit\s+push\s+-f\b", re.I),
    re.compile(r"\bnpm\s+publish\b", re.I),
    re.compile(r"\bdocker\s+(rm|rmi)\b", re.I),
    re.compile(r"\bsudo\b", re.I),
    re.compile(r">\s*/etc/|/usr/bin/|/boot/", re.I),
]

PROTECTED_PATH_PATTERNS: list[str] = [
    "thumbelina.db", "MEMORY/", "prompts/roles/", "plugins/", ".env",
]


def _is_protected(raw: str) -> str | None:
    """命中保护路径则返回该模式,否则 None。以路径分段做前缀/相等匹配,避免误伤。"""
    posix = raw.replace("\\", "/").lower()
    parts = [seg for seg in posix.split("/") if seg]
    for guard in PROTECTED_PATH_PATTERNS:
        g = guard.lower()
        if g.endswith("/"):
            dirs = g.rstrip("/").split("/")
            for i in range(len(parts) - len(dirs) + 1):
                if parts[i : i + len(dirs)] == dirs:
                    return guard
        else:
            for seg in parts:
                if seg == g or seg.startswith(g):
                    return guard
    return None


_ERROR_HINTS = re.compile(
    r"\berror\b|denied|not found|Traceback|command not found", re.I
)


def _normalize_command(command: str) -> str:
    lines = [ln.split("#", 1)[0] for ln in command.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


class _RunShellArgs(BaseModel):
    command: str = Field(..., description="Shell command to execute.")


class _WriteFileArgs(BaseModel):
    path: str = Field(..., description="Path of the file to write.")
    content: str = Field(..., description="Content to write to the file.")


class ExecutionTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.EXECUTION

    @abstractmethod
    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        """执行工具必须实现真实审查。"""

    @abstractmethod
    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        """执行工具必须实现真实自验证。"""

    security_review.__isabstractmethod__ = True  # 覆盖基类默认,强制子类实现
    self_verify.__isabstractmethod__ = True


class RunShellTool(ExecutionTool):
    name: str = "run_shell"
    description: str = (
        "Execute a shell command and return stdout+stderr. Timeout: 30 seconds."
    )
    args_schema: type[BaseModel] = _RunShellArgs

    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        cmd = _normalize_command(str(args.get("command", "")))
        if not cmd:
            return Reject("空命令")
        for pat in DANGEROUS_PATTERNS:
            if pat.search(cmd):
                return Reject(f"危险命令模式 {pat.pattern!r}")
        for pat in CONFIRM_PATTERNS:
            if pat.search(cmd):
                return Confirm(f"建议人工确认: {pat.pattern!r}")
        return Allow()

    async def _execute(self, command: str) -> str:
        cwd = get_workspace() or os.getcwd()
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            shell=True,
            cwd=cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: Command timed out after {_TIMEOUT} seconds"
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        if len(output) > 100_000:
            output = output[:100_000] + "\n... (truncated)"
        return output + f"\n[exit code: {proc.returncode}]"

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        ms = list(re.finditer(r"\[exit code: (-?\d+)\]", result))
        m = ms[-1] if ms else None  # 取末尾匹配:防程序伪造 [exit code: 0] 抢先
        if m and m.group(1) != "0":
            if _ERROR_HINTS.search(result) or m.group(1) not in ("",):
                return Suspect(f"命令退出码非零: {m.group(1)}")
        return Ok()


class WriteFileTool(ExecutionTool):
    name: str = "write_file"
    description: str = "Write content to a file. Creates parent directories if needed."
    args_schema: type[BaseModel] = _WriteFileArgs

    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        raw = str(args.get("path", ""))
        # 第一道:复用工作区边界检查(越界相对路径/绝对路径直接拒绝)
        try:
            resolve_workspace_path(raw)
        except ValueError as exc:
            return Reject(str(exc))
        # 第二道:保护路径(含 resolve 前的原始相对路径与解析后的绝对路径)
        guard = _is_protected(raw)
        if guard:
            return Reject(f"受保护路径: {guard}")
        return Allow()

    async def _execute(self, path: str, content: str) -> str:
        try:
            resolved = resolve_workspace_path(path)
            p = Path(resolved) if resolved is not None else Path(path).resolve()
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

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        if not result.startswith("Successfully wrote"):
            return Ok()  # 已在 _execute 中返回 Error:,无副作用可验证
        content = str(args.get("content", ""))
        try:
            resolved = resolve_workspace_path(str(args.get("path", "")))
            p = Path(resolved) if resolved is not None else Path(str(args.get("path", ""))).resolve()
            actual = p.stat().st_size
        except OSError:
            return Suspect("写入后无法回读校验")
        if actual != len(content.encode("utf-8")):
            return Suspect("写入字节数与内容不符")
        return Ok()
