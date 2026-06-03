"""Plugin sandbox for restricting plugin execution.

Provides static analysis of plugin code to detect potentially dangerous
patterns, and optional execution with resource limits. The sandbox is
advisory by default for a personal project -- it validates and warns but
does not hard-block.
"""

from __future__ import annotations

import ast
import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ResourceLimits:
    """Resource limits for sandboxed plugin execution.

    Attributes
    ----------
    max_memory_mb:
        Maximum memory in megabytes the plugin may use (advisory).
    max_cpu_time_seconds:
        Maximum wall-clock seconds the plugin function may run.
    max_file_size_mb:
        Maximum file size in megabytes a plugin may create/read (advisory).
    """

    max_memory_mb: int = 100
    max_cpu_time_seconds: float = 30.0
    max_file_size_mb: int = 10


@dataclass
class SandboxViolation:
    """A single sandbox violation found during validation.

    Attributes
    ----------
    violation_type:
        ``"warning"`` or ``"error"``.
    message:
        Human-readable description of the violation.
    line:
        Source line number where the violation was found, or *None*.
    """

    violation_type: str
    message: str
    line: int | None = None


# ---------------------------------------------------------------------------
# Default module sets
# ---------------------------------------------------------------------------

DEFAULT_ALLOWED_MODULES: frozenset[str] = frozenset({
    "os.path",
    "json",
    "re",
    "math",
    "datetime",
    "typing",
    "collections",
    "functools",
    "itertools",
    "pathlib",
    "urllib.parse",
    "hashlib",
    "base64",
    # Common safe modules for plugins
    "logging",
    "copy",
    "textwrap",
    "string",
    "abc",
    "enum",
    "dataclasses",
    "uuid",
    "time",
    "decimal",
    "statistics",
    "contextlib",
    "io",
    "struct",
})

DEFAULT_BLOCKED_MODULES: frozenset[str] = frozenset({
    "subprocess",
    "shutil",
    "socket",
    "ctypes",
    "importlib",
    "sys",
    "signal",
    "multiprocessing",
    "threading",
    "webbrowser",
    "pty",
    "fcntl",
    "termios",
    "tty",
})

# Patterns that are considered dangerous when called directly
_DANGEROUS_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "exit",
    "quit",
})

# Patterns that are dangerous when used as attribute access
_DANGEROUS_ATTR_COMBINATIONS: frozenset[str] = frozenset({
    "os.system",
    "os.popen",
    "os.exec*",
    "os.spawn*",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.rename",
    "os.replace",
})


# ---------------------------------------------------------------------------
# Static analysis helpers
# ---------------------------------------------------------------------------

def _get_imported_modules(tree: ast.AST) -> list[tuple[str, int | None]]:
    """Extract all imported module names from an AST.

    Returns a list of ``(module_name, line_number)`` tuples.
    """
    modules: list[tuple[str, int | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            modules.append((module, node.lineno))
    return modules


def _get_dangerous_calls(tree: ast.AST) -> list[tuple[str, int | None]]:
    """Find calls to dangerous built-in functions.

    Returns a list of ``(function_name, line_number)`` tuples.
    """
    calls: list[tuple[str, int | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Direct call: eval(...)
            if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_CALLS:
                calls.append((node.func.id, node.lineno))
            # Attribute call: os.system(...)
            elif isinstance(node.func, ast.Attribute):
                # Check if it's a method call on a dangerous pattern
                attr_name = node.func.attr
                if attr_name in {"system", "popen", "remove", "unlink", "rmdir",
                                 "rename", "replace", "exec*", "spawn*"}:
                    if isinstance(node.func.value, ast.Name):
                        calls.append(
                            (f"{node.func.value.id}.{attr_name}", node.lineno)
                        )
    return calls


def _check_open_write_mode(tree: ast.AST) -> list[tuple[str, int | None]]:
    """Find ``open()`` calls that use write/append modes.

    Returns a list of ``(description, line_number)`` tuples.
    """
    issues: list[tuple[str, int | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Check for open() calls
        is_open_call = False
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            is_open_call = True
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            is_open_call = True

        if not is_open_call:
            continue

        # Look for write mode in arguments
        for arg in node.args[1:]:  # Skip the filename argument
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if any(m in arg.value for m in ("w", "a", "x", "+")):
                    issues.append(
                        (f"open() with write mode '{arg.value}'", node.lineno)
                    )
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    if any(m in kw.value.value for m in ("w", "a", "x", "+")):
                        issues.append(
                            (f"open() with write mode '{kw.value.value}'", kw.value.lineno)
                        )
    return issues


def _check_dangerous_patterns(tree: ast.AST) -> list[tuple[str, int | None]]:
    """Check for other dangerous patterns beyond imports and calls.

    Returns a list of ``(description, line_number)`` tuples.
    """
    issues: list[tuple[str, int | None]] = []

    for node in ast.walk(tree):
        # Check for string-based attribute access that could be dangerous
        # e.g., getattr(obj, '__subclasses__')
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                if len(node.args) >= 2:
                    second_arg = node.args[1]
                    if isinstance(second_arg, ast.Constant) and isinstance(
                        second_arg.value, str
                    ):
                        if second_arg.value.startswith("__") and second_arg.value.endswith(
                            "__"
                        ):
                            issues.append(
                                (
                                    f"getattr() with dunder attribute '{second_arg.value}'",
                                    node.lineno,
                                )
                            )

    return issues


# ---------------------------------------------------------------------------
# PluginSandbox
# ---------------------------------------------------------------------------

class PluginSandbox:
    """Sandbox for validating and restricting plugin execution.

    Parameters
    ----------
    allowed_modules:
        Set of module names plugins are allowed to import.
        Defaults to :data:`DEFAULT_ALLOWED_MODULES`.
    blocked_modules:
        Set of module names explicitly blocked for plugins.
        Defaults to :data:`DEFAULT_BLOCKED_MODULES`.
    resource_limits:
        Resource limits for sandboxed execution.
    strict:
        If *True*, ``validate_plugin`` returns ``False`` when violations
        are found.  If *False* (default, advisory mode), validation
        always returns ``True`` but still reports violations.
    """

    def __init__(
        self,
        allowed_modules: set[str] | frozenset[str] | None = None,
        blocked_modules: set[str] | frozenset[str] | None = None,
        resource_limits: ResourceLimits | None = None,
        strict: bool = False,
    ) -> None:
        self.allowed_modules: frozenset[str] = (
            frozenset(allowed_modules) if allowed_modules is not None else DEFAULT_ALLOWED_MODULES
        )
        self.blocked_modules: frozenset[str] = (
            frozenset(blocked_modules) if blocked_modules is not None else DEFAULT_BLOCKED_MODULES
        )
        self.resource_limits = resource_limits or ResourceLimits()
        self.strict = strict

    # ---- Validation -------------------------------------------------------

    def validate_plugin(self, plugin_code: str) -> tuple[bool, list[SandboxViolation]]:
        """Validate plugin source code against sandbox rules.

        Uses Python's ``ast`` module to statically analyse the source.

        Parameters
        ----------
        plugin_code:
            The Python source code of the plugin.

        Returns
        -------
        tuple[bool, list[SandboxViolation]]
            ``(is_valid, violations)`` -- *is_valid* is ``True`` when the
            plugin passes all checks (or when in advisory mode even with
            warnings).
        """
        violations: list[SandboxViolation] = []

        # Handle empty code
        if not plugin_code or not plugin_code.strip():
            return True, violations

        # Parse the AST
        try:
            tree = ast.parse(plugin_code)
        except SyntaxError as exc:
            violations.append(
                SandboxViolation(
                    violation_type="error",
                    message=f"Syntax error: {exc}",
                    line=exc.lineno,
                )
            )
            return False, violations

        # Check imports
        for module_name, lineno in _get_imported_modules(tree):
            # Check blocked modules (highest priority)
            top_level = module_name.split(".")[0]
            if top_level in self.blocked_modules:
                violations.append(
                    SandboxViolation(
                        violation_type="error",
                        message=f"Blocked module import: '{module_name}'",
                        line=lineno,
                    )
                )
            # Check if the module (or its top-level) is in allowed list
            elif (
                module_name not in self.allowed_modules
                and top_level not in self.allowed_modules
            ):
                violations.append(
                    SandboxViolation(
                        violation_type="warning",
                        message=f"Import of non-whitelisted module: '{module_name}'",
                        line=lineno,
                    )
                )

        # Check dangerous function calls
        for call_name, lineno in _get_dangerous_calls(tree):
            violations.append(
                SandboxViolation(
                    violation_type="warning",
                    message=f"Dangerous function call: '{call_name}'",
                    line=lineno,
                )
            )

        # Check open() with write mode
        for desc, lineno in _check_open_write_mode(tree):
            violations.append(
                SandboxViolation(
                    violation_type="warning",
                    message=f"Potentially dangerous file operation: {desc}",
                    line=lineno,
                )
            )

        # Check other dangerous patterns
        for desc, lineno in _check_dangerous_patterns(tree):
            violations.append(
                SandboxViolation(
                    violation_type="warning",
                    message=desc,
                    line=lineno,
                )
            )

        # Determine validity
        has_errors = any(v.violation_type == "error" for v in violations)
        if self.strict and violations:
            return False, violations
        if has_errors:
            # Even in advisory mode, syntax errors and blocked modules
            # are always considered failures.
            return False, violations
        return True, violations

    # ---- Sandboxed execution ----------------------------------------------

    def execute_sandboxed(
        self,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *func* with resource limits.

        Runs *func* in a separate thread with a wall-clock timeout.  If the
        function does not finish within ``resource_limits.max_cpu_time_seconds``
        a ``TimeoutError`` is raised.

        Parameters
        ----------
        func:
            The callable to execute.
        *args:
            Positional arguments forwarded to *func*.
        **kwargs:
            Keyword arguments forwarded to *func*.

        Returns
        -------
        Any
            The return value of *func*.

        Raises
        ------
        TimeoutError
            If *func* does not complete within the allowed time.
        Exception
            Any exception raised by *func* is propagated.
        """
        result: list[Any] = []
        exception: list[BaseException | None] = [None]

        def _target() -> None:
            try:
                result.append(func(*args, **kwargs))
            except BaseException as exc:
                exception[0] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self.resource_limits.max_cpu_time_seconds)

        if thread.is_alive():
            # Thread is still running -- timeout exceeded.
            # We cannot forcibly kill a thread in Python, but we can
            # signal the caller that the operation timed out.
            raise TimeoutError(
                f"Plugin execution exceeded the "
                f"{self.resource_limits.max_cpu_time_seconds}s timeout"
            )

        if exception[0] is not None:
            raise exception[0]

        return result[0] if result else None
