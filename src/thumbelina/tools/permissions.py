"""会话权限判定（spec §3/§4/§5.1，单一事实源）。

闸门（agent/graph.py::_tool_node_node）与工具级 security_review 共同消费本模块。
两个 ContextVar 与 workspace_context.py 同模式，默认 fail-closed：
未接线的入口（不调 apply_conversation_runtime）= 只读 + 无审批者。

本模块内容布局：
  - 任务 1：模式枚举、LADDER、ContextVar、effective_mode。
  - 任务 2：shell 分类器上移（含 Windows 规则组 + 写穿收紧），上移自
    tools/execution.py。
"""
from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from thumbelina.tools.workspace_context import get_workspace, resolve_workspace_path


class PermissionMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    GLOBAL_WRITE = "global_write"
    FULL_ACCESS = "full_access"
    AUTO = "auto"


LADDER: tuple[PermissionMode, ...] = (
    PermissionMode.READ_ONLY,
    PermissionMode.WORKSPACE_WRITE,
    PermissionMode.GLOBAL_WRITE,
    PermissionMode.FULL_ACCESS,
    PermissionMode.AUTO,
)


def parse_mode(value: str | None) -> PermissionMode | None:
    if not value:
        return None
    try:
        return PermissionMode(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class PermissionDecision:
    verdict: Literal["allow", "confirm", "deny"]
    risk: Literal["normal", "dangerous"] = "normal"
    reason: str = ""
    auto_allowed: bool = False  # True：auto 模式下本应 confirm 的调用被自动放行


ALLOW = PermissionDecision("allow")


def deny(reason: str, *, dangerous: bool = False) -> PermissionDecision:
    return PermissionDecision("deny", "dangerous" if dangerous else "normal", reason)


def confirm(reason: str) -> PermissionDecision:
    return PermissionDecision("confirm", "dangerous", reason)


_current_mode: contextvars.ContextVar[PermissionMode] = contextvars.ContextVar(
    "current_permission_mode", default=PermissionMode.READ_ONLY
)
_has_approver: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "permission_has_approver", default=False
)


def set_permission_mode(mode: PermissionMode) -> None:
    _current_mode.set(mode)


def get_permission_mode() -> PermissionMode:
    return _current_mode.get()


def set_approval_context(value: bool) -> None:
    _has_approver.set(value)


def has_approver() -> bool:
    return _has_approver.get()


def effective_mode(
    mode: PermissionMode, *, unattended: bool, has_workspace: bool
) -> PermissionMode:
    """无人值守上限 = workspace_write（有工作区）/ read_only（无工作区）；auto 显式豁免。"""
    if not unattended or mode == PermissionMode.AUTO:
        return mode
    ceiling = PermissionMode.WORKSPACE_WRITE if has_workspace else PermissionMode.READ_ONLY
    return min((mode, ceiling), key=LADDER.index)


# ---------------------------------------------------------------------------
# 任务 2：shell 分类（spec §4.2-§4.4；自 tools/execution.py 上移，唯一事实源）
# ---------------------------------------------------------------------------


def normalize_shell_command(command: str) -> str:
    """把 shell 输入折成单行：折续行（\\\\<newline>）、剥 # 注释、合并空白。

    审批卡展示归一化命令用（spec §4.6），也是分类器的实际输入（防止
    ``rm -rf \\\\n/`` 通过续行绕过黑名单）。
    """
    folded = re.sub(r"\\\r?\n", " ", command)
    lines = [ln.split("#", 1)[0] for ln in folded.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _rm_root_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """rm 递归+强制删除任意绝对路径(/、/*、/etc)的黑名单正则(终审 I-1)。

    语义:rm 后跟一串选项 token(r/f 可合写 ``-rf``/``-fr``、拆写 ``-r -f``,
    长参数 ``--recursive``/``--force`` 各算一个标志;``-(?!-)`` 保证短选项
    按字母匹配、长选项按词面匹配),目标以 ``/`` 开头 → 拒绝。
    ``rm -rf ./build``、``rm file.txt`` 等相对/无标志命令不误伤;
    仅含 r 或仅含 f 不构成危险组合。两条正则分别处理「合写」与「拆写」,
    拆写两条枚举 r→f 与 f→r 顺序(可读优先)。

    上移自 ``tools/execution.py::_rm_root_patterns``；reason 由中文短名
    改为稳定规则键 ``dangerous.rm_root``。
    """
    both = r"(?:\s+-\w*r\w*f\w*|\s+-\w*f\w*r\w*)"
    skip = r"(?:\s+-\w+)*"
    r_tok = r"\s+-(?!-)\w*r\w*"
    f_tok = r"\s+-(?!-)\w*f\w*"
    r_long = r"\s+--recursive"
    f_long = r"\s+--force"
    target = r"\s+(/\S*)(?:\s|$)"
    key = "dangerous.rm_root"
    return [
        (key, re.compile(rf"\brm{both}{skip}{target}", re.I)),
        (key, re.compile(rf"\brm{r_tok}{skip}{f_tok}{skip}{target}", re.I)),
        (key, re.compile(rf"\brm{f_tok}{skip}{r_tok}{skip}{target}", re.I)),
        (key, re.compile(rf"\brm{r_long}{skip}{f_long}{skip}{target}", re.I)),
        (key, re.compile(rf"\brm{f_long}{skip}{r_long}{skip}{target}", re.I)),
    ]


POSIX_DANGEROUS: list[tuple[str, re.Pattern[str]]] = [
    *_rm_root_patterns(),
    ("dangerous.mkfs", re.compile(r"\bmkfs\b", re.I)),
    ("dangerous.dd_block", re.compile(r"\bdd\b[^\n]*\bof=/dev/(?!null\b)", re.I)),
    ("dangerous.fork_bomb", re.compile(r":\(\)\s*{", re.I)),
    (
        "dangerous.shutdown",
        re.compile(r"\bshutdown\b|\breboot\b|\bpoweroff\b", re.I),
    ),
    (
        "dangerous.pipe_remote",
        re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh", re.I),
    ),
    ("dangerous.redirect_block", re.compile(r">\s*/dev/(?!null\b)[a-z]", re.I)),
    ("dangerous.chmod_root", re.compile(r"\bchmod\s+(-R\s+)?777\s+/(\s|$)", re.I)),
]

WINDOWS_DANGEROUS: list[tuple[str, re.Pattern[str]]] = [
    (
        "dangerous.rd_recursive",
        re.compile(r"\brd\s+(?:/q\s+)?/s\b|\brd\s+/s(?:\s+/q)?\b", re.I),
    ),
    (
        "dangerous.ri_recursive",
        re.compile(r"\bRemove-Item\b[^\n]*-Recurse[^\n]*[\"']?[A-Za-z]:\\", re.I),
    ),
    ("dangerous.format", re.compile(r"\bformat\s+[A-Za-z]:", re.I)),
    ("dangerous.cipher_w", re.compile(r"\bcipher\s+/w\b", re.I)),
    (
        "dangerous.vssadmin",
        re.compile(r"\bvssadmin\b[^\n]*delete\s+shadows", re.I),
    ),
    ("dangerous.bcdedit", re.compile(r"\bbcdedit\b", re.I)),
    (
        "dangerous.ps_encoded",
        re.compile(r"\bpowershell\b[^\n]*-enc(?:oded)?\b", re.I),
    ),
]

DANGEROUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = POSIX_DANGEROUS + WINDOWS_DANGEROUS

POSIX_CONFIRM: list[tuple[str, re.Pattern[str]]] = [
    (
        "confirm.git_force_push",
        re.compile(r"\bgit\s+push\s+--force|\bgit\s+push\s+-f\b", re.I),
    ),
    ("confirm.npm_publish", re.compile(r"\bnpm\s+publish\b", re.I)),
    ("confirm.docker_remove", re.compile(r"\bdocker\s+(rm|rmi)\b", re.I)),
    ("confirm.sudo", re.compile(r"\bsudo\b", re.I)),
    ("confirm.system_path_write", re.compile(r">\s*/etc/|/usr/bin/|/boot/", re.I)),
]

WINDOWS_CONFIRM: list[tuple[str, re.Pattern[str]]] = [
    (
        "confirm.system_dir_windows",
        re.compile(
            r"[A-Za-z]:\\+(?:Windows|Program Files(?: \(x86\))?|ProgramData)\b"
            r"|\\System32\\",
            re.I,
        ),
    ),
    ("confirm.drive_root_redirect", re.compile(r">\s*[A-Za-z]:\\", re.I)),
    ("confirm.reg_add", re.compile(r"\breg\s+add\b|\bregedit\s+/s\b", re.I)),
    ("confirm.schtasks", re.compile(r"\bschtasks\s+/create\b", re.I)),
    (
        "confirm.windows_service",
        re.compile(
            r"\bsc(?:\.exe)?\s+(?:config|delete|stop)\b"
            r"|\bSet-Service\b|\bStop-Service\b",
            re.I,
        ),
    ),
]

CONFIRM_PATTERNS: list[tuple[str, re.Pattern[str]]] = POSIX_CONFIRM + WINDOWS_CONFIRM

# 写穿收紧（spec §4.4）：写意图（重定向/写命令）+ 绝对路径目标 → confirm
_WRITE_CMD_RE = re.compile(
    r"\b(cp|mv|copy|move|xcopy|robocopy|tee|touch|Set-Content|Add-Content|Out-File)\b",
    re.I,
)
_WRITE_REDIRECT_RE = re.compile(r"\s>>?\s*\S")
_ABSOLUTE_TARGET_RE = re.compile(
    r"[A-Za-z]:\\[^\s]|\\\\[^\s]|>\s*/(?!dev/null)[A-Za-z]"
)


def _absolute_write(cmd: str) -> bool:
    if not (_WRITE_REDIRECT_RE.search(cmd) or _WRITE_CMD_RE.search(cmd)):
        return False
    return bool(_ABSOLUTE_TARGET_RE.search(cmd))


def classify_shell_command(
    command: str, *, auto: bool = False
) -> PermissionDecision:
    """对 shell 命令做两级裁决（spec §4.2-§4.4）：

    1. 空命令 → deny ``rule.empty_command``；
    2. 命中 ``DANGEROUS_PATTERNS`` → deny（硬底线，spec §4.2）；
    3. 命中 ``CONFIRM_PATTERNS`` 或绝对路径写穿 → confirm；
    4. 其余 → allow。

    参数 ``auto`` 用于任务 4 的 ``evaluate_tool_call``：当 ``auto=True``
    时 CONFIRM 命中不阻塞、转为 ``auto_allowed=True`` 的 allow。
    """
    cmd = normalize_shell_command(command)
    if not cmd:
        return deny("rule.empty_command")
    for key, pat in DANGEROUS_PATTERNS:
        if pat.search(cmd):
            return deny(key, dangerous=True)
    # 写穿收紧先于 CONFIRM_PATTERNS：``echo x > /etc/hosts`` 同时命中
    # ``confirm.system_path_write`` 与 ``confirm.absolute_write``，按 spec
    # §4.4 设计意图以更具体的「写意图 + 绝对路径」为准（plan Task 2 用例）。
    if _absolute_write(cmd):
        if auto:
            return PermissionDecision(
                "allow", "dangerous", "confirm.absolute_write", True
            )
        return confirm("confirm.absolute_write")
    for key, pat in CONFIRM_PATTERNS:
        if pat.search(cmd):
            if auto:
                return PermissionDecision("allow", "dangerous", key, True)
            return confirm(key)
    return ALLOW


# ---------------------------------------------------------------------------
# 任务 3：写路径分类与保护路径第二锚点（spec §4.5）
# ---------------------------------------------------------------------------


PROTECTED_PATH_PATTERNS: list[str] = [
    "thumbelina.db",
    "MEMORY/",
    "prompts/roles/",
    "plugins/",
    ".env",
    "TODO/",          # v3 新增（spec §4.5）：任务清单被改写可社会工程用户
    "attachments/",     # v3 新增：覆盖后经 WS→WeChat 转发链注入对端内容
]


# 启动时由 app.py lifespan 经 _register_app_anchors 注册的绝对锚点
# （spec §4.5：workspace≠CWD 时目录类守卫存在锚定盲区）。
_app_anchors: dict[str, str] = {}


def set_app_anchor(guard: str, absolute_path: str) -> None:
    """注册守卫名（如 ``"MEMORY/"``）对应的解析后绝对路径（第二锚点）。"""
    _app_anchors[guard] = str(Path(absolute_path).resolve())


def get_app_anchors() -> dict[str, str]:
    """返回当前已注册的应用锚点映射（供调试/测试观察）。"""
    return dict(_app_anchors)


def _is_protected(raw: str) -> str | None:
    """命中保护路径则返回该模式，否则 None。

    目录类守卫双锚定（修复 spec §4.5 锚定盲区）：
    1) 工作区相对前缀分段（原行为，深层同名目录不误伤）；
    2) 启动注册的绝对路径第二锚点（解决 workspace≠CWD 时绝对路径
       ``F:\\…\\MEMORY\\x.md`` 不命中目录类守卫的问题）。

    文件名类守卫（thumbelina.db、.env）任意层级分段匹配，数据/秘密
    放到哪都危险。
    """
    posix = raw.replace("\\", "/").lower()
    parts = [seg for seg in posix.split("/") if seg]
    ws = get_workspace()
    base = (ws or "").replace("\\", "/").rstrip("/").lower()
    base_parts = [seg for seg in base.split("/") if seg]
    rel = parts
    if base_parts and parts[: len(base_parts)] == base_parts:
        rel = parts[len(base_parts) :]
    for guard in PROTECTED_PATH_PATTERNS:
        g = guard.lower()
        if g.endswith("/"):
            dirs = [seg for seg in g.rstrip("/").split("/") if seg]
            if rel[: len(dirs)] == dirs:
                return guard
            anchor = _app_anchors.get(guard)
            if anchor:
                a = anchor.replace("\\", "/").lower().rstrip("/").split("/")
                if parts[: len(a)] == a:
                    return guard
        else:
            for seg in parts:
                if seg == g or seg.startswith(g):
                    return guard
    return None


PathKind = Literal["in_workspace", "escape", "unbounded", "protected"]


def classify_write_path(path: str) -> PathKind:
    """写路径分类（闸门与工具 security_review 共用）。

    优先级：protected > escape > in_workspace > unbounded（无工作区兜底）。
    """
    if _is_protected(path):
        return "protected"
    try:
        resolved = resolve_workspace_path(path)
    except ValueError:
        return "escape"
    return "unbounded" if resolved is None else "in_workspace"


def evaluate_write_file(mode: PermissionMode, path: str) -> PermissionDecision:
    """按 spec §3.3 矩阵 + §4.5 保护路径裁决 write_file 调用。

    =========== ================== ================ =================
    kind         workspace_write    global_write     full_access/auto
    =========== ================== ================ =================
    protected    deny(dangerous)    confirm          allow
    escape       deny               allow            allow
    in_workspace allow              allow            allow
    unbounded    deny(no_workspace)  allow            allow
    =========== ================== ================ =================

    注：READ_ONLY 不在此处处理 —— 闸门（Task 8 evaluate_tool_call）已先
    拒绝全部写工具；本函数仅供 gate 通过后 mode≥WORKSPACE_WRITE 路径
    复用。工具级 security_review 在委托前自行读 ContextVar 兜底拒绝。
    """
    kind = classify_write_path(path)
    if kind == "protected":
        if mode is PermissionMode.WORKSPACE_WRITE:
            return deny("rule.protected_path", dangerous=True)
        if mode is PermissionMode.GLOBAL_WRITE:
            return confirm("rule.protected_path")
        return ALLOW  # full_access / auto
    if kind == "escape":
        if mode is PermissionMode.WORKSPACE_WRITE:
            return deny("rule.workspace_escape")
        return ALLOW  # global_write 起（write_file 的执行期二次复核同步放开）
    if kind == "in_workspace":
        return ALLOW
    # unbounded（无工作区）：workspace_write 等效只读兜底
    if mode is PermissionMode.WORKSPACE_WRITE:
        return deny("rule.no_workspace")
    return ALLOW


def _register_app_anchors(config: object | None = None) -> None:
    """按 config 实际值解析应用内部目录为绝对锚点。

    典型调用点（Task 6 接线，在 app.py lifespan 装配完 memory/todo/
    attachments 服务之后）：

        from thumbelina.tools.permissions import (
            set_app_anchor,
            _register_app_anchors,
        )
        _register_app_anchors(config)

    解析失败的守卫仅记录 WARNING 日志，不抛 —— 启动必须继续，无锚点
    退化为"workspace 相对前缀"单一锚点（深层保护路径仍生效）。
    """
    import logging

    logger = logging.getLogger(__name__)

    def _resolve_memory(default: str) -> str:
        if config is None:
            return default
        mem = getattr(config, "memory", None)
        if mem is None:
            return default
        return str(getattr(mem, "directory", None) or default)

    mapping: dict[str, str] = {
        "MEMORY/": _resolve_memory("MEMORY"),
        "TODO/": "TODO",
        "attachments/": "attachments",
        "prompts/roles/": str(Path("prompts") / "roles"),
        "plugins/": "plugins",
    }
    for guard, raw in mapping.items():
        try:
            set_app_anchor(guard, raw)
        except OSError:
            logger.warning("permission anchor resolve failed: %s", guard)
