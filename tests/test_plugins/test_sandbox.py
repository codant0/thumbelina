"""Tests for plugin sandbox."""

from __future__ import annotations

import textwrap

import pytest

from thumbelina.plugins.manager import PluginManager
from thumbelina.plugins.sandbox import PluginSandbox, ResourceLimits, SandboxViolation
from thumbelina.plugins.sandboxed_loader import SandboxedPluginLoader

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox():
    """Create a default PluginSandbox in advisory mode."""
    return PluginSandbox()


@pytest.fixture
def strict_sandbox():
    """Create a PluginSandbox in strict mode."""
    return PluginSandbox(strict=True)


@pytest.fixture
def loader():
    """Create a SandboxedPluginLoader in advisory mode."""
    return SandboxedPluginLoader()


@pytest.fixture
def strict_loader():
    """Create a SandboxedPluginLoader in strict mode."""
    return SandboxedPluginLoader(strict_mode=True)


# ---------------------------------------------------------------------------
# ResourceLimits tests
# ---------------------------------------------------------------------------


class TestResourceLimits:
    """Tests for ResourceLimits dataclass."""

    def test_defaults(self):
        """ResourceLimits should have sensible defaults."""
        limits = ResourceLimits()
        assert limits.max_memory_mb == 100
        assert limits.max_cpu_time_seconds == 30.0
        assert limits.max_file_size_mb == 10

    def test_custom_values(self):
        """ResourceLimits should accept custom values."""
        limits = ResourceLimits(max_memory_mb=256, max_cpu_time_seconds=60.0, max_file_size_mb=50)
        assert limits.max_memory_mb == 256
        assert limits.max_cpu_time_seconds == 60.0
        assert limits.max_file_size_mb == 50


# ---------------------------------------------------------------------------
# PluginSandbox validation tests
# ---------------------------------------------------------------------------


class TestPluginSandboxValidation:
    """Tests for PluginSandbox.validate_plugin()."""

    def test_safe_plugin_passes(self, sandbox):
        """A safe plugin with only allowed imports should pass."""
        code = textwrap.dedent("""\
            import json
            import re
            from datetime import datetime
            from pathlib import Path

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert is_valid is True
        assert violations == []

    def test_empty_code_passes(self, sandbox):
        """Empty plugin code should pass validation."""
        is_valid, violations = sandbox.validate_plugin("")
        assert is_valid is True
        assert violations == []

    def test_whitespace_only_passes(self, sandbox):
        """Whitespace-only plugin code should pass validation."""
        is_valid, violations = sandbox.validate_plugin("   \n\n  ")
        assert is_valid is True
        assert violations == []

    def test_blocked_import_fails(self, sandbox):
        """Importing a blocked module should produce an error violation."""
        code = textwrap.dedent("""\
            import subprocess
            import json

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        # Advisory mode: still valid overall, but violations reported
        assert any(v.violation_type == "error" for v in violations)
        assert any("subprocess" in v.message for v in violations)

    def test_eval_call_flagged(self, sandbox):
        """Using eval() should produce a warning violation."""
        code = textwrap.dedent("""\
            import json

            def register(manager):
                result = eval("1 + 1")
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("eval" in v.message for v in violations)
        assert any(v.violation_type == "warning" for v in violations)

    def test_exec_call_flagged(self, sandbox):
        """Using exec() should produce a warning violation."""
        code = textwrap.dedent("""\
            def register(manager):
                exec("x = 1")
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("exec" in v.message for v in violations)

    def test_open_write_flagged(self, sandbox):
        """Using open() with write mode should produce a warning violation."""
        code = textwrap.dedent("""\
            def register(manager):
                with open("/tmp/test.txt", "w") as f:
                    f.write("hello")
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("open()" in v.message for v in violations)

    def test_open_append_flagged(self, sandbox):
        """Using open() with append mode should produce a warning violation."""
        code = textwrap.dedent("""\
            def register(manager):
                f = open("/tmp/test.txt", "a")
                f.close()
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("open()" in v.message for v in violations)

    def test_non_whitelisted_import_warning(self, sandbox):
        """Importing a non-whitelisted (but not blocked) module produces a warning."""
        code = textwrap.dedent("""\
            import requests

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("non-whitelisted" in v.message for v in violations)
        assert any("requests" in v.message for v in violations)

    def test_syntax_error_fails(self, sandbox):
        """Invalid Python syntax should fail validation."""
        code = "def register(manager):\n    if True\n"
        is_valid, violations = sandbox.validate_plugin(code)
        assert is_valid is False
        assert any(v.violation_type == "error" for v in violations)
        assert any("Syntax error" in v.message for v in violations)

    def test_multiple_violations_detected(self, sandbox):
        """Multiple violations in a single plugin should all be detected."""
        code = textwrap.dedent("""\
            import subprocess
            import socket

            def register(manager):
                eval("x")
                exec("y")
                with open("/tmp/f", "w") as f:
                    f.write("z")
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert len(violations) >= 5  # 2 blocked + eval + exec + open

    def test_getattr_dunder_flagged(self, sandbox):
        """getattr() with dunder attribute should be flagged."""
        code = textwrap.dedent("""\
            def register(manager):
                obj = object()
                subclasses = getattr(obj, "__subclasses__")
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("dunder" in v.message for v in violations)

    def test_compile_flagged(self, sandbox):
        """Using compile() should produce a warning violation."""
        code = textwrap.dedent("""\
            def register(manager):
                code = compile("x = 1", "<string>", "exec")
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("compile" in v.message for v in violations)

    def test_importlib_flagged(self, sandbox):
        """Importing importlib should be blocked."""
        code = textwrap.dedent("""\
            import importlib

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any(v.violation_type == "error" for v in violations)
        assert any("importlib" in v.message for v in violations)

    def test_allowed_modules_set(self):
        """Custom allowed_modules should override defaults."""
        sandbox = PluginSandbox(allowed_modules={"my_module"})
        code = textwrap.dedent("""\
            import json

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        # json is NOT in the custom allowed set, so it's flagged
        assert any("non-whitelisted" in v.message for v in violations)

    def test_custom_blocked_modules(self):
        """Custom blocked_modules should override defaults."""
        sandbox = PluginSandbox(blocked_modules={"my_danger_module"})
        code = textwrap.dedent("""\
            import my_danger_module

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert any("my_danger_module" in v.message for v in violations)

    def test_strict_mode_with_warnings_fails(self, strict_sandbox):
        """In strict mode, any violation (including warnings) should fail."""
        code = textwrap.dedent("""\
            import requests

            def register(manager):
                pass
        """)
        is_valid, violations = strict_sandbox.validate_plugin(code)
        assert is_valid is False
        assert len(violations) > 0

    def test_advisory_mode_with_warnings_passes(self, sandbox):
        """In advisory mode, warnings should not cause failure."""
        code = textwrap.dedent("""\
            import requests

            def register(manager):
                pass
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        assert is_valid is True
        assert len(violations) > 0

    def test_line_numbers_reported(self, sandbox):
        """Violations should include line numbers."""
        code = textwrap.dedent("""\
            import json

            def register(manager):
                eval("1")  # line 4
        """)
        is_valid, violations = sandbox.validate_plugin(code)
        eval_violations = [v for v in violations if "eval" in v.message]
        assert len(eval_violations) == 1
        assert eval_violations[0].line == 4


# ---------------------------------------------------------------------------
# PluginSandbox.execute_sandboxed tests
# ---------------------------------------------------------------------------


class TestExecuteSandboxed:
    """Tests for PluginSandbox.execute_sandboxed()."""

    def test_execute_simple_function(self, sandbox):
        """Should execute a simple function and return result."""

        def add(a, b):
            return a + b

        result = sandbox.execute_sandboxed(add, 2, 3)
        assert result == 5

    def test_execute_with_kwargs(self, sandbox):
        """Should pass kwargs to the function."""

        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = sandbox.execute_sandboxed(greet, "World", greeting="Hi")
        assert result == "Hi, World!"

    def test_execute_timeout(self):
        """Should raise TimeoutError when function exceeds time limit."""
        import time

        limits = ResourceLimits(max_cpu_time_seconds=0.1)
        sandbox = PluginSandbox(resource_limits=limits)

        def slow():
            time.sleep(1.0)

        with pytest.raises(TimeoutError, match="timeout"):
            sandbox.execute_sandboxed(slow)

    def test_execute_propagates_exceptions(self, sandbox):
        """Should propagate exceptions from the function."""

        def bad():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            sandbox.execute_sandboxed(bad)

    def test_execute_returns_none(self, sandbox):
        """Should return None when function returns None."""

        def noop():
            return None

        result = sandbox.execute_sandboxed(noop)
        assert result is None


# ---------------------------------------------------------------------------
# SandboxedPluginLoader tests
# ---------------------------------------------------------------------------


class TestSandboxedPluginLoader:
    """Tests for SandboxedPluginLoader."""

    def test_validate_safe_file(self, loader, tmp_path):
        """Should validate a safe plugin file as valid."""
        plugin_file = tmp_path / "safe_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            import json
            import re

            def register(manager):
                pass
        """)
        )
        result = loader.validate_file(str(plugin_file))
        assert result.is_valid is True
        assert result.violations == []
        assert result.plugin_name == "safe_plugin"

    def test_validate_unsafe_file(self, loader, tmp_path):
        """Should detect violations in an unsafe plugin file."""
        plugin_file = tmp_path / "unsafe_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            import subprocess

            def register(manager):
                eval("x")
        """)
        )
        result = loader.validate_file(str(plugin_file))
        assert len(result.violations) >= 2

    def test_validate_nonexistent_file(self, loader):
        """Should handle nonexistent files gracefully."""
        result = loader.validate_file("/nonexistent/path/plugin.py")
        assert result.is_valid is False
        assert any("Could not read" in v.message for v in result.violations)

    def test_strict_mode_rejects_warnings(self, strict_loader, tmp_path):
        """In strict mode, warnings should cause validation failure."""
        plugin_file = tmp_path / "warning_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            import requests

            def register(manager):
                pass
        """)
        )
        result = strict_loader.validate_file(str(plugin_file))
        assert result.is_valid is False

    def test_results_tracked(self, loader, tmp_path):
        """Validation results should be tracked per plugin."""
        plugin_file = tmp_path / "tracked_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            import json

            def register(manager):
                pass
        """)
        )
        loader.validate_file(str(plugin_file))
        results = loader.results
        assert "tracked_plugin" in results

    def test_get_report(self, loader, tmp_path):
        """get_report() should return serialisable results."""
        plugin_file = tmp_path / "report_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            import json

            def register(manager):
                pass
        """)
        )
        loader.validate_file(str(plugin_file))
        report = loader.get_report()
        assert isinstance(report, list)
        assert len(report) == 1
        assert report[0]["plugin_name"] == "report_plugin"
        assert report[0]["is_valid"] is True
        assert report[0]["loaded"] is False

    @pytest.mark.asyncio
    async def test_load_plugins_advisory_mode(self, loader, tmp_path):
        """Advisory mode should load plugins with warnings."""
        plugin_file = tmp_path / "warn_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            from thumbelina.plugins.base import Plugin, PluginType

            import requests  # non-whitelisted but not blocked

            async def register(manager):
                plugin = Plugin(
                    id="warn-plugin",
                    name="warn_plugin",
                    description="A plugin with warnings",
                    plugin_type=PluginType.TOOL,
                    version="1.0.0",
                )
                await manager.register(plugin)
        """)
        )
        manager = PluginManager()
        loaded = await loader.load_plugins_from_directory(str(tmp_path), manager)
        assert loaded == 1
        # Verify the plugin was actually registered
        plugin = await manager.get("warn-plugin")
        assert plugin is not None

    @pytest.mark.asyncio
    async def test_load_plugins_strict_mode_blocks(self, tmp_path):
        """Strict mode should reject plugins with violations."""
        plugin_file = tmp_path / "bad_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            from thumbelina.plugins.base import Plugin, PluginType
            import subprocess

            async def register(manager):
                plugin = Plugin(
                    id="bad-plugin",
                    name="bad_plugin",
                    description="Blocked plugin",
                    plugin_type=PluginType.TOOL,
                    version="1.0.0",
                )
                await manager.register(plugin)
        """)
        )
        strict = SandboxedPluginLoader(strict_mode=True)
        manager = PluginManager()
        loaded = await strict.load_plugins_from_directory(str(tmp_path), manager)
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_load_nonexistent_directory(self, loader):
        """Should return 0 for nonexistent directory."""
        manager = PluginManager()
        loaded = await loader.load_plugins_from_directory("/nonexistent", manager)
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_load_empty_directory(self, loader, tmp_path):
        """Should return 0 for empty directory."""
        manager = PluginManager()
        loaded = await loader.load_plugins_from_directory(str(tmp_path), manager)
        assert loaded == 0


# ---------------------------------------------------------------------------
# PluginManager integration tests
# ---------------------------------------------------------------------------


class TestPluginManagerSandboxIntegration:
    """Tests for PluginManager sandbox integration."""

    @pytest.mark.asyncio
    async def test_manager_without_sandbox(self):
        """PluginManager without sandbox should work as before."""
        manager = PluginManager()
        report = manager.get_sandbox_report()
        assert report == []

    @pytest.mark.asyncio
    async def test_manager_with_sandbox_loader(self, loader, tmp_path):
        """PluginManager with sandboxed loader should validate before loading."""
        plugin_file = tmp_path / "good_plugin.py"
        plugin_file.write_text(
            textwrap.dedent("""\
            from thumbelina.plugins.base import Plugin, PluginType

            async def register(manager):
                plugin = Plugin(
                    id="good-plugin",
                    name="good_plugin",
                    description="A good plugin",
                    plugin_type=PluginType.TOOL,
                    version="1.0.0",
                )
                await manager.register(plugin)
        """)
        )
        manager = PluginManager(sandboxed_loader=loader)
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 1

        # Check sandbox report
        report = manager.get_sandbox_report()
        assert len(report) == 1
        assert report[0]["plugin_name"] == "good_plugin"
        assert report[0]["is_valid"] is True
        assert report[0]["loaded"] is True


# ---------------------------------------------------------------------------
# SandboxViolation tests
# ---------------------------------------------------------------------------


class TestSandboxViolation:
    """Tests for SandboxViolation dataclass."""

    def test_create_violation(self):
        """Should create a SandboxViolation."""
        v = SandboxViolation(
            violation_type="warning",
            message="Test warning",
            line=42,
        )
        assert v.violation_type == "warning"
        assert v.message == "Test warning"
        assert v.line == 42

    def test_violation_without_line(self):
        """Should create a SandboxViolation without line number."""
        v = SandboxViolation(violation_type="error", message="Test error")
        assert v.line is None
