"""Tests for plugin filesystem loader."""

from __future__ import annotations

import os
import textwrap

import pytest

from thumbelina.plugins.base import PluginType
from thumbelina.plugins.manager import PluginManager


@pytest.fixture
def manager():
    """Create a PluginManager."""
    return PluginManager()


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a temporary directory with sample plugin files."""
    # Valid plugin
    plugin_file = tmp_path / "greet_plugin.py"
    plugin_file.write_text(
        textwrap.dedent("""\
            from thumbelina.plugins.base import Plugin, PluginType

            async def register(manager):
                plugin = Plugin(
                    id="greet-plugin",
                    name="Greet Plugin",
                    description="Says hello",
                    plugin_type=PluginType.TOOL,
                    version="1.0.0",
                )
                await manager.register(plugin)
        """)
    )

    # Valid async plugin
    async_plugin = tmp_path / "async_plugin.py"
    async_plugin.write_text(
        textwrap.dedent("""\
            from thumbelina.plugins.base import Plugin, PluginType

            async def register(manager):
                plugin = Plugin(
                    id="async-plugin",
                    name="Async Plugin",
                    description="An async plugin",
                    plugin_type=PluginType.SKILL,
                    version="1.0.0",
                )
                await manager.register(plugin)
        """)
    )

    return tmp_path


@pytest.fixture
def plugin_dir_with_package(tmp_path):
    """Create a directory with a package-style plugin."""
    pkg_dir = tmp_path / "my_plugin"
    pkg_dir.mkdir()
    init_file = pkg_dir / "__init__.py"
    init_file.write_text(
        textwrap.dedent("""\
            from thumbelina.plugins.base import Plugin, PluginType

            async def register(manager):
                plugin = Plugin(
                    id="pkg-plugin",
                    name="Package Plugin",
                    description="A package plugin",
                    plugin_type=PluginType.CHANNEL,
                    version="2.0.0",
                )
                await manager.register(plugin)
        """)
    )
    return tmp_path


class TestLoadPluginsFromDirectory:
    """Tests for PluginManager.load_plugins_from_directory."""

    @pytest.mark.asyncio
    async def test_load_valid_plugins(self, manager, plugin_dir):
        """Should load plugins from .py files in directory."""
        loaded = await manager.load_plugins_from_directory(str(plugin_dir))
        assert loaded == 2

        plugins = await manager.list_plugins()
        assert len(plugins) == 2
        ids = {p.id for p in plugins}
        assert ids == {"greet-plugin", "async-plugin"}

    @pytest.mark.asyncio
    async def test_load_package_plugin(self, manager, plugin_dir_with_package):
        """Should load plugins from */__init__.py packages."""
        loaded = await manager.load_plugins_from_directory(str(plugin_dir_with_package))
        assert loaded == 1

        plugins = await manager.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].id == "pkg-plugin"
        assert plugins[0].plugin_type == PluginType.CHANNEL

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, manager):
        """Should return 0 and log warning for missing directory."""
        loaded = await manager.load_plugins_from_directory("/nonexistent/path")
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_empty_directory(self, manager, tmp_path):
        """Should return 0 for empty directory."""
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_skip_underscore_files(self, manager, tmp_path):
        """Should skip files starting with underscore."""
        p = tmp_path / "_private.py"
        p.write_text("def register(manager): pass")
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_skip_file_without_register(self, manager, tmp_path):
        """Should skip files that don't have a register function."""
        p = tmp_path / "no_register.py"
        p.write_text("x = 42\n")
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_handle_import_error(self, manager, tmp_path):
        """Should skip files that raise import errors."""
        p = tmp_path / "broken.py"
        p.write_text("import nonexistent_module_xyz_12345\n")
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_handle_runtime_error_in_register(self, manager, tmp_path):
        """Should skip files where register() raises an error."""
        p = tmp_path / "bad_register.py"
        p.write_text(
            textwrap.dedent("""\
                async def register(manager):
                    raise RuntimeError("boom")
            """)
        )
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_non_callable_register(self, manager, tmp_path):
        """Should skip files where register is not callable."""
        p = tmp_path / "static_register.py"
        p.write_text("register = 42\n")
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid(self, manager, tmp_path):
        """Should load valid plugins and skip invalid ones."""
        valid = tmp_path / "good.py"
        valid.write_text(
            textwrap.dedent("""\
                from thumbelina.plugins.base import Plugin, PluginType

                async def register(manager):
                    plugin = Plugin(
                        id="good",
                        name="Good",
                        description="ok",
                        plugin_type=PluginType.TOOL,
                        version="1.0",
                    )
                    await manager.register(plugin)
            """)
        )
        broken = tmp_path / "bad.py"
        broken.write_text("import this_does_not_exist_at_all\n")

        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 1
        assert await manager.get("good") is not None

    @pytest.mark.asyncio
    async def test_skips_non_py_files(self, manager, tmp_path):
        """Should ignore non-Python files."""
        txt = tmp_path / "readme.txt"
        txt.write_text("not a plugin")
        loaded = await manager.load_plugins_from_directory(str(tmp_path))
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_example_plugin_loads(self):
        """The example plugin at plugins/examples should load correctly."""
        example_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "plugins", "examples"
        )
        if not os.path.isdir(example_dir):
            pytest.skip("Example plugin directory not found")

        manager = PluginManager()
        loaded = await manager.load_plugins_from_directory(example_dir)
        assert loaded == 1

        plugin = await manager.get("hello-plugin")
        assert plugin is not None
        assert plugin.name == "Hello Plugin"
        assert plugin.plugin_type == PluginType.TOOL
