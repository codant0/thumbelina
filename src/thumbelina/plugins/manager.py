"""Plugin manager for registering and managing plugins."""

from __future__ import annotations

from thumbelina.plugins.base import Plugin, PluginType


class PluginManager:
    """Manager for registering and managing plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    async def register(self, plugin: Plugin) -> None:
        """Register a plugin."""
        self._plugins[plugin.id] = plugin

    async def get(self, plugin_id: str) -> Plugin | None:
        """Get a plugin by ID."""
        return self._plugins.get(plugin_id)

    async def list_plugins(self) -> list[Plugin]:
        """List all registered plugins."""
        return list(self._plugins.values())

    async def unregister(self, plugin_id: str) -> bool:
        """Unregister a plugin."""
        if plugin_id not in self._plugins:
            return False
        del self._plugins[plugin_id]
        return True

    async def list_by_type(self, plugin_type: PluginType) -> list[Plugin]:
        """List plugins by type."""
        return [p for p in self._plugins.values() if p.plugin_type == plugin_type]
