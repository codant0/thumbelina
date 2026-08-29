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


def _rm_root_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """rm 递归+强制删除任意绝对路径(/、/*、/etc)的黑名单正则(终审 I-1)。

    语义:rm 后跟一串选项 token(r/f 可合写 ``-rf``/``-fr``、拆写 ``-r -f``,
    长参数 ``--recursive``/``--force`` 各算一个标志;``-(?!-)`` 保证短选项
    按字母匹配、长选项按词面匹配),目标以 ``/`` 开头 → Reject。
    ``rm -rf ./build``、``rm file.txt`` 等相对/无标志命令不误伤;
    仅含 r 或仅含 f 不构成危险组合。两条正则分别处理「合写」与「拆写」,
    拆写两条枚举 r→f 与 f→r 顺序(可读优先)。
    """
    both = r"(?:\s+-\w*r\w*f\w*|\s+-\w*f\w*r\w*)"  # 合写:同一短选项含 r 与 f
    skip = r"(?:\s+-\w+)*"  # 夹带的中性选项
    r_tok = r"\s+-(?!-)\w*r\w*"  # 递归短选项(含 r 字母)
    f_tok = r"\s+-(?!-)\w*f\w*"  # 强制短选项(含 f 字母)
    r_long = r"\s+--recursive"  # 长参数等价形式
    f_long = r"\s+--force"
    target = r"\s+(/\S*)(?:\s|$)"  # 以 / 开头的目标(/、/*、/etc/...)
    return [
        ("rm 递归强删绝对路径", re.compile(rf"\brm{both}{skip}{target}", re.I)),
        ("rm 递归强删绝对路径", re.compile(rf"\brm{r_tok}{skip}{f_tok}{skip}{target}", re.I)),
        ("rm 递归强删绝对路径", re.compile(rf"\brm{f_tok}{skip}{r_tok}{skip}{target}", re.I)),
        ("rm 递归强删绝对路径", re.compile(rf"\brm{r_long}{skip}{f_long}{skip}{target}", re.I)),
        ("rm 递归强删绝对路径", re.compile(rf"\brm{f_long}{skip}{r_long}{skip}{target}", re.I)),
    ]


# 审核修复 B-7:每条规则为 (人类可读短名, 编译正则)。Reject/Confirm reason
# 只输出短名——正则源码上百字符进 ToolMessage/日志会污染 LLM 上下文,
# 且向模型披露完整规则。
DANGEROUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    *_rm_root_patterns(),
    ("格式化文件系统(mkfs)", re.compile(r"\bmkfs\b", re.I)),
    # 审核修复 B-5:`dd of=/dev/null` 是合法丢弃写法,负向前瞻排除 null。
    ("dd 写入块设备", re.compile(r"\bdd\b[^\n]*\bof=/dev/(?!null\b)", re.I)),
    ("fork 炸弹", re.compile(r":\(\)\s*{", re.I)),
    # 已知 best-effort 局限(审核 B-8,见 spec §11):无命令位概念,
    # `grep -r shutdown src/` 会误杀;引入命令位置解析属过度设计,不修。
    ("关机/重启/断电", re.compile(r"\bshutdown\b|\breboot\b|\bpoweroff\b", re.I)),
    ("管道执行远程脚本", re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh", re.I)),
    # 无 \b:兼容「空格 + >」重定向(如 echo x > /dev/sda);审核修复 B-5:
    # `(?!null\b)` 放行 `> /dev/null`、`2>/dev/null` 等丢弃输出的惯用法。
    ("重定向写入块设备", re.compile(r">\s*/dev/(?!null\b)[a-z]", re.I)),
    ("chmod 777 根目录", re.compile(r"\bchmod\s+(-R\s+)?777\s+/(\s|$)", re.I)),
]

CONFIRM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("git 强推", re.compile(r"\bgit\s+push\s+--force|\bgit\s+push\s+-f\b", re.I)),
    ("npm 发布", re.compile(r"\bnpm\s+publish\b", re.I)),
    ("docker 删除", re.compile(r"\bdocker\s+(rm|rmi)\b", re.I)),
    ("sudo 提权", re.compile(r"\bsudo\b", re.I)),
    ("写系统路径", re.compile(r">\s*/etc/|/usr/bin/|/boot/", re.I)),
]

PROTECTED_PATH_PATTERNS: list[str] = [
    "thumbelina.db",
    "MEMORY/",
    "prompts/roles/",
    "plugins/",
    ".env",
]


def _is_protected(raw: str, workspace: str | None = None) -> str | None:
    """命中保护路径则返回该模式,否则 None。

    终审 I-2:目录类守卫(带尾斜杠,如 MEMORY/、plugins/)只锚定工作区
    相对路径的开头分段——深层同名目录(src/memory/util.py、app/plugins/
    views.py)是普通代码,不应误伤;文件名类守卫(thumbelina.db*、.env*)
    保持任意层级分段匹配(数据/秘密文件放到哪都危险)。
    绝对路径先以 workspace(无 workspace 时退到 CWD)前缀相对化再取分段;
    前缀不匹配时保守地按原分段锚定。
    """
    posix = raw.replace("\\", "/").lower()
    parts = [seg for seg in posix.split("/") if seg]
    base = (workspace or os.getcwd()).replace("\\", "/").rstrip("/").lower()
    base_parts = [seg for seg in base.split("/") if seg]
    if base_parts and parts[: len(base_parts)] == base_parts:
        parts = parts[len(base_parts) :]
    for guard in PROTECTED_PATH_PATTERNS:
        g = guard.lower()
        if g.endswith("/"):
            # 目录类:仅锚定开头分段
            dirs = [seg for seg in g.rstrip("/").split("/") if seg]
            if parts[: len(dirs)] == dirs:
                return guard
        else:
            # 文件名类:任意层级
            for seg in parts:
                if seg == g or seg.startswith(g):
                    return guard
    return None


_ERROR_HINTS = re.compile(r"\berror\b|denied|not found|Traceback|command not found", re.I)


def _normalize_command(command: str) -> str:
    # 审核修复 B-6:shell 会把「反斜杠+换行」拼成续行,若只折叠空白会残留字面
    # `\`,使 `rm -rf \<newline>/` 绕过黑名单——先把续行折成空格再走原逻辑。
    folded = re.sub(r"\\\r?\n", " ", command)
    lines = [ln.split("#", 1)[0] for ln in folded.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


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
        """执行前安全审查:命令文本归一化后过两级规则表。

        防护清单(按裁决顺序):
        1. 空命令 → Reject(无信息量的调用不放行)。
        2. ``DANGEROUS_PATTERNS`` 任一命中 → Reject,不可执行。防护的
           破坏性操作类别:
           - rm 递归强删绝对路径(``-rf``/``-fr``/``-r -f``/``--recursive
             --force`` 各合写拆写顺序 × 目标 ``/`` 开头任意路径,含 ``/*``)
           - mkfs 格式化文件系统
           - dd 写入块设备(``of=/dev/`` 族,``of=/dev/null`` 放行)
           - fork 炸弹(``:(){`` 递归函数定义头)
           - shutdown/reboot/poweroff 断电重启
           - curl/wget 管道给 sh/bash 执行远程脚本
           - ``> /dev/X`` 重定向写块设备(``> /dev/null`` 放行)
           - chmod 777 根目录
        3. ``CONFIRM_PATTERNS`` 任一命中 → Confirm:本期**放行 + WARNING
           日志**(由基类模板执行),覆盖不可逆/外泄类操作:git 强推、
           npm 发布、docker rm/rmi 删除、sudo 提权、写系统路径。
        4. 其余 → Allow。

        审查对象是**归一化后的文本**(``_normalize_command``:折续行、剥
        ``#`` 注释、折叠空白),不解析引号/变量/管道结构——故本防线是
        行为塑形而非对抗性边界(见模块 docstring 定位声明;已知绕过形态
        列举于 spec §11)。命中 reason 只输出规则短名,不外泄正则源码。
        """
        cmd = _normalize_command(str(args.get("command", "")))
        if not cmd:
            return Reject("空命令")
        for name, pat in DANGEROUS_PATTERNS:
            if pat.search(cmd):
                return Reject(name)
        for name, pat in CONFIRM_PATTERNS:
            if pat.search(cmd):
                return Confirm(name)
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
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            shell=True,
            cwd=cwd,
        )
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
        """执行前安全审查:两道独立闸门,任一命中即 Reject。

        防护清单:
        1. 工作区边界:复用 ``resolve_workspace_path``——coder 会话下
           绝对路径或解析后越出 workspace 的相对路径(``../`` 等)直接
           拒绝;普通会话无 workspace 时此闸不生效(legacy 行为)。
        2. 保护路径(``_is_protected``,分两类策略):
           - 目录类(锚定 workspace 根分段,深层同名目录不误伤):
             ``MEMORY/``——记忆库唯一写路径是抽取器,阻断 agent 绕过
             配额/审计直写;``prompts/roles/``——角色系统提示词,防
             自我改写提权;``plugins/``——插件加载目录,防注入代码。
           - 文件名类(任意层级分段匹配,放到哪都危险):
             ``thumbelina.db*``——会话/检查点/配置数据库(含 -wal/-shm);
             ``.env``*——环境变量秘密文件。
        3. 其余 → Allow(本工具无 Confirm 档:写文件的影响已由边界+
           保护路径穷举,其余写操作视为正常职能)。

        reason 只输出命中的守卫名;审查在落盘之前拦截,恶意路径不触盘。
        """
        raw = str(args.get("path", ""))
        # 第一道:复用工作区边界检查(越界相对路径/绝对路径直接拒绝)
        try:
            resolve_workspace_path(raw)
        except ValueError as exc:
            return Reject(str(exc))
        # 第二道:保护路径(含 resolve 前的原始相对路径与解析后的绝对路径)
        guard = _is_protected(raw, get_workspace())
        if guard:
            return Reject(f"受保护路径: {guard}")
        return Allow()

    async def _execute(self, path: str, content: str) -> str:
        """落盘写入。防护清单(执行中兜底护栏):

        - 边界二次校验:再走一次 ``resolve_workspace_path``——与审查
          独立复核,防绕过入口直接调用(纵深)。
        - 字节精确写:``newline=""`` 关闭平台换行转译(终审 I-3),
          使"Successfully wrote N bytes"文案与自验证的字节比对同时为真。
        - 失败不抛:权限/OS 错误转 ``Error:`` 字符串返回。
        """
        try:
            resolved = resolve_workspace_path(path)
            p = Path(resolved) if resolved is not None else Path(path).resolve()
        except ValueError as exc:
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
