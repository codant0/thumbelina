"""Tests for plugin manager."""

from __future__ import annotations

import pytest

from thumbelina.plugins.base import Plugin, PluginType
from thumbelina.plugins.manager import PluginManager


@pytest.fixture
def manager():
    """Create a PluginManager."""
    return PluginManager()


@pytest.fixture
def sample_plugin():
    """Create a sample plugin."""
    return Plugin(
        id="plugin-1",
        name="test_plugin",
        description="A test plugin",
        plugin_type=PluginType.TOOL,
        version="1.0.0",
    )


class TestPluginManager:
    """Tests for the PluginManager class."""

    def test_manager_class_exists(self):
        """PluginManager should be importable."""
        assert PluginManager is not None

    def test_manager_creates_instance(self):
        """Should create a PluginManager."""
        m = PluginManager()
        assert m is not None

    @pytest.mark.asyncio
    async def test_register_plugin(self, manager, sample_plugin):
        """Should be able to register a plugin."""
        await manager.register(sample_plugin)

    @pytest.mark.asyncio
    async def test_get_plugin(self, manager, sample_plugin):
        """Should be able to get a plugin by ID."""
        await manager.register(sample_plugin)
        result = await manager.get("plugin-1")

        assert result is not None
        assert result.name == "test_plugin"

    @pytest.mark.asyncio
    async def test_get_nonexistent_plugin(self, manager):
        """Should return None for non-existent plugin."""
        result = await manager.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_plugins(self, manager):
        """Should list all plugins."""
        p1 = Plugin(
            id="p1", name="Plugin 1", description="desc",
            plugin_type=PluginType.TOOL, version="1.0",
        )
        p2 = Plugin(
            id="p2", name="Plugin 2", description="desc",
            plugin_type=PluginType.SKILL, version="1.0",
        )
        await manager.register(p1)
        await manager.register(p2)

        plugins = await manager.list_plugins()
        assert len(plugins) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, manager):
        """Should return empty list when no plugins."""
        plugins = await manager.list_plugins()
        assert plugins == []

    @pytest.mark.asyncio
    async def test_unregister_plugin(self, manager, sample_plugin):
        """Should be able to unregister a plugin."""
        await manager.register(sample_plugin)
        result = await manager.unregister("plugin-1")

        assert result is True
        assert await manager.get("plugin-1") is None

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, manager):
        """Should return False when unregistering non-existent plugin."""
        result = await manager.unregister("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_by_type(self, manager):
        """Should be able to list plugins by type."""
        p1 = Plugin(
            id="p1", name="Tool 1", description="desc",
            plugin_type=PluginType.TOOL, version="1.0",
        )
        p2 = Plugin(
            id="p2", name="Skill 1", description="desc",
            plugin_type=PluginType.SKILL, version="1.0",
        )
        await manager.register(p1)
        await manager.register(p2)

        tools = await manager.list_by_type(PluginType.TOOL)
        assert len(tools) == 1
        assert tools[0].name == "Tool 1"


class TestPlugin:
    """Tests for the Plugin class."""

    def test_plugin_class_exists(self):
        """Plugin should be importable."""
        assert Plugin is not None

    def test_plugin_create(self):
        """Should create a Plugin."""
        p = Plugin(
            id="p1",
            name="Test",
            description="Test plugin",
            plugin_type=PluginType.TOOL,
            version="1.0",
        )
        assert p.id == "p1"
        assert p.name == "Test"

    def test_plugin_type_enum(self):
        """PluginType should have expected values."""
        assert PluginType.TOOL == "tool"
        assert PluginType.SKILL == "skill"
        assert PluginType.CHANNEL == "channel"
        assert PluginType.PROVIDER == "provider"
