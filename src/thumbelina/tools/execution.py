"""执行工具:副作用 + 强制安全审查/结果自验证(spec §4.3/§5)。

本模块的防护体系(分层概览):

1. **执行前——安全审查**(``security_review``,三态裁决,由基类模板方法
   ``_arun`` 在 ``_execute`` 之前强制调用):
   - ``Reject``:命中即拒绝执行,返回 ``Error: ... 安全审查拒绝: <规则短名>``;
   - ``Confirm``:高危但可能有合法用途——本期**放行 + WARNING 日志**(无
     人在环回路,枚举留作 HITL 接线点,见 spec §9);
   - ``Allow``:默认通过。
2. **执行中——兜底护栏**(``_execute`` 内):超时 kill、输出截断、
   工作区边界、字节精确写。
3. **执行后——结果自验证**(``self_verify``):对已发生的副作用做一致性
   检查,可疑时追加 ``[warn]`` 提醒(不推翻副作用)。

定位声明(spec §11):正则黑名单是**行为塑形层(防误操作)+ 纵深防御最
外层,不是对抗性边界**——嵌套解释器(``bash -c``/``python -c``)、变量
展开、引号变形等文本层绕过不设防,对抗性隔离由沙箱层承担(§9 后续)。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
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
from thumbelina.tools.permissions import (
    CONFIRM_PATTERNS,
    DANGEROUS_PATTERNS,
    PermissionMode,
    classify_shell_command,
    classify_write_path,
    evaluate_write_file,
    get_permission_mode,
)  # noqa: F401  # 旧测试/外部代码 re-export
from thumbelina.tools.workspace_context import (
    get_workspace,
    resolve_workspace_path,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 30

_fallback_warned = False


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """杀掉 shell 进程及其整棵子进程树。

    Windows 上 ``shell=True`` 产生的 cmd.exe 被单独 kill 时,其孙子进程
    (如 ping)仍持有继承的 stdout 管道,``communicate`` 会一直阻塞到孤儿
    跑完 —— 必须用 ``taskkill /T`` 连树一起杀;POSIX 直接 kill 即可。
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        proc.kill()


def _run_blocking(command: str, cwd: str) -> str:
    """线程池兜底执行:与 asyncio 路径同契约(stderr 合并、100KB 截断、
    超时文案、exit code 标记)。仅当运行中的事件循环不支持 asyncio 子进程
    时被使用(Windows 下 uvicorn --reload 强制 SelectorEventLoop)。
    """
    popen = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        stdout, _ = popen.communicate(timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_process_tree(popen)
        try:
            popen.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            logger.warning("RunShellTool fallback: child process did not exit after tree kill")
        return f"Error: Command timed out after {_TIMEOUT} seconds"
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    if len(output) > 100_000:
        output = output[:100_000] + "\n... (truncated)"
    return output + f"\n[exit code: {popen.returncode}]"


# DANGEROUS_PATTERNS / CONFIRM_PATTERNS / PROTECTED_PATH_PATTERNS 已于任务 2/3
# 上移至 thumbelina.tools.permissions（spec §4.2 单一事实源）。
# 中-2 修复：删除 execution.py 旧副本（无 TODO/attachments/、无第二锚点），
# 改由 ``from thumbelina.tools.permissions import DANGEROUS_PATTERNS,
# CONFIRM_PATTERNS, PROTECTED_PATH_PATTERNS`` re-export 给旧测试/外部
# 调用方继续使用。旧 _is_protected 副本不再保留——分类已迁至
# permissions._is_protected（含双锚点）。
__all__ = [
    "ExecutionTool",
    "RunShellTool",
    "WriteFileTool",
    "DANGEROUS_PATTERNS",
    "CONFIRM_PATTERNS",
    "PROTECTED_PATH_PATTERNS",
]


_ERROR_HINTS = re.compile(r"\berror\b|denied|not found|Traceback|command not found", re.I)


class _RunShellArgs(BaseModel):
    command: str = Field(..., description="Shell command to execute.")


class _WriteFileArgs(BaseModel):
    path: str = Field(..., description="Path of the file to write.")
    content: str = Field(..., description="Content to write to the file.")


class ExecutionTool(ThumbelinaBaseTool):
    """执行类工具基类:把「安全审查 + 结果自验证」钉成构造期不可绕过的契约。

    防护策略:
    - ``security_review``/``self_verify`` 用 ``__isabstractmethod__`` 猴补丁
      重声明为抽象——基类虽提供默认实现(全放行),执行类子类**必须**各自
      覆写,否则 pydantic/ABCMeta 在实例化时直接抛 ``TypeError``
      (回归见 tests/test_tools/test_execution_review.py::
      test_execution_tool_is_abstract)。
    - 生命周期顺序由基类 ``ThumbelinaBaseTool._arun`` 模板强制:
      审查(拒绝则不执行) → 执行 → 自验证(可疑则追加 [warn])。
    """

    category: ToolCategory = ToolCategory.EXECUTION

    @abstractmethod
    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        """执行工具必须实现真实审查。"""

    @abstractmethod
    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        """执行工具必须实现真实自验证。"""

    # 覆盖基类默认,强制子类实现(猴补丁;mypy 无法建模该动态属性)
    security_review.__isabstractmethod__ = True  # type: ignore[attr-defined]
    self_verify.__isabstractmethod__ = True  # type: ignore[attr-defined]


class RunShellTool(ExecutionTool):
    name: str = "run_shell"
    description: str = "Execute a shell command and return stdout+stderr. Timeout: 30 seconds."
    args_schema: type[BaseModel] = _RunShellArgs

    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        """执行前安全审查（spec §4.2-§4.4）：委托共享分类器。

        任务 2 起把两级规则表与归一化逻辑上移至
        ``thumbelina.tools.permissions.classify_shell_command``（单一事实源），
        reason 由中文短名改为稳定规则键（``dangerous.*`` / ``confirm.*``）。
        本方法保留 ``auto=False``：Task 6 接线 ``auto=(mode is AUTO)`` 后，
        自动模式下 CONFIRM 命中转为 ``auto_allowed=True`` 放行（任务 4 范围）。
        """
        from thumbelina.tools.permissions import get_permission_mode

        decision = classify_shell_command(
            str(args.get("command", "")),
            auto=(get_permission_mode() == PermissionMode.AUTO),
        )
        if decision.verdict == "deny":
            return Reject(decision.reason)
        if decision.verdict == "confirm":
            return Confirm(decision.reason)
        return Allow()

    async def _execute(self, command: str) -> str:
        """执行命令。防护清单(执行中兜底护栏,审查之后的第二层):

        - 超时熔断:30s(``_TIMEOUT``)无输出即 ``proc.kill()`` 并返回
          Error 串——防挂死进程占住 agent 循环。
        - 输出截断:stdout+stderr 合并捕获,超 100KB 截断——防海量输出
          撑爆 LLM 上下文。
        - 工作目录锚定:coder 会话在绑定的 workspace 下执行(cwd 仅是
          起点约束,非沙箱;逃逸靠黑名单与部署边界兜,见模块 docstring)。
        """
        cwd = get_workspace() or os.getcwd()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                shell=True,
                cwd=cwd,
            )
        except NotImplementedError:
            # Windows 下 uvicorn --reload 让 uvicorn 强制选用
            # SelectorEventLoop(uvicorn/loops/asyncio.py 对
            # use_subprocess=True 的既定行为),而 Selector 循环不实现
            # asyncio 子进程 —— 降级到线程池跑阻塞 subprocess,契约不变。
            global _fallback_warned
            if not _fallback_warned:
                logger.warning(
                    "Event loop lacks asyncio subprocess support (Windows "
                    "SelectorEventLoop under uvicorn --reload); RunShellTool "
                    "falling back to thread-pool subprocess"
                )
                _fallback_warned = True
            return await asyncio.to_thread(_run_blocking, command, cwd)
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except TimeoutError:
            proc.kill()
            return f"Error: Command timed out after {_TIMEOUT} seconds"
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        if len(output) > 100_000:
            output = output[:100_000] + "\n... (truncated)"
        return output + f"\n[exit code: {proc.returncode}]"

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        """执行后自验证:命令已完成,对结果负责。

        防护清单:
        - 退出码哨兵:取输出**末尾**的 ``[exit code: N]`` 标记(本工具
          追加的真标记;取最后匹配是为防被命令自身打印伪造的
          ``[exit code: 0]`` 抢先);非零退出 → Suspect 追加
          ``[warn] 命令退出码非零: N``,提示 LLM 检查失败原因/重试。
        - 不推翻副作用:命令已真实执行,验证只提醒不回滚。
        """
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
        """执行前安全审查:委托 ``permissions.evaluate_write_file``(Task 3)。

        单一事实源——与闸门 ``evaluate_tool_call`` 共用 ``classify_write_path``,
        保证保护路径第二锚点(MEMORY/TODO/attachments 等)裁决一致。

        委托前读 ContextVar:READ_ONLY 默认拒绝全部写(spec §3.3 矩阵);其余
        模式走 mode-aware 裁决——workspace_write 越界/保护路径 deny,
        global_write 保护路径 confirm,full_access/auto 放行。
        """
        raw = str(args.get("path", ""))
        mode = get_permission_mode()
        if mode is PermissionMode.READ_ONLY:
            return Reject("rule.read_only")
        decision = evaluate_write_file(mode, raw)
        if decision.verdict == "deny":
            return Reject(decision.reason)
        if decision.verdict == "confirm":
            return Confirm(decision.reason)
        return Allow()

    async def _execute(self, path: str, content: str) -> str:
        """落盘写入。防护清单(执行中兜底护栏):

        - 边界二次校验:再走一次 ``resolve_workspace_path``——与审查
          独立复核,防绕过入口直接调用(纵深)。
        - mode-aware 越界放行(Task 3,spec §3.3 矩阵 GLOBAL_WRITE+)：
          当闸门已裁决 allow 但 ``resolve_workspace_path`` 仍抛
          ``ValueError``(越界相对路径/绝对路径)时,GLOBAL_WRITE/
          FULL_ACCESS/AUTO 模式落到 ``Path(path).resolve()`` 继续,
          允许越界写——与闸门裁决保持一致;WORKSPACE_WRITE 维持原
          ``Error:`` 行为。
        - 字节精确写:``newline=""`` 关闭平台换行转译(终审 I-3),
          使"Successfully wrote N bytes"文案与自验证的字节比对同时为真。
        - 失败不抛:权限/OS 错误转 ``Error:`` 字符串返回。
        """
        try:
            resolved = resolve_workspace_path(path)
            p = Path(resolved) if resolved is not None else Path(path).resolve()
        except ValueError as exc:
            mode = get_permission_mode()
            if (
                mode
                in (
                    PermissionMode.GLOBAL_WRITE,
                    PermissionMode.FULL_ACCESS,
                    PermissionMode.AUTO,
                )
                and classify_write_path(path) == "escape"
            ):
                # 闸门已裁决 allow，越界路径按无边界模式放行
                p = Path(path).resolve()
            else:
                return f"Error: {exc}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # 终审 I-3:newline="" 关闭平台换行转译,字节精确落盘——
            # Windows 下文本模式会把 \n 转成 \r\n,导致 st_size 与
            # len(content.encode()) 不符,自验证每次误报 [warn]。
            p.write_text(content, encoding="utf-8", newline="")
            return f"Successfully wrote {len(content.encode('utf-8'))} bytes to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except OSError as exc:
            return f"Error writing file: {exc}"

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        """执行后自验证:写完回读校验,确认副作用与意图一致。

        防护清单:
        - 失败短路:``_execute`` 已返回 Error 串时不验证(无副作用发生)。
        - 字节数回读:``stat().st_size`` 对比 ``len(content.encode())``,
          不符(并发覆盖/半途失败/转译差异)→ Suspect
          ``[warn] 写入字节数与内容不符``;文件消失/不可读 → Suspect
          ``[warn] 写入后无法回读校验``。
        - 只提醒不回滚:内容已落盘,由 LLM 决定重试策略。
        """
        if not result.startswith("Successfully wrote"):
            return Ok()  # 已在 _execute 中返回 Error:,无副作用可验证
        content = str(args.get("content", ""))
        try:
            resolved = resolve_workspace_path(str(args.get("path", "")))
            p = (
                Path(resolved)
                if resolved is not None
                else Path(str(args.get("path", ""))).resolve()
            )
            actual = p.stat().st_size
        except OSError:
            return Suspect("写入后无法回读校验")
        if actual != len(content.encode("utf-8")):
            return Suspect("写入字节数与内容不符")
        return Ok()
