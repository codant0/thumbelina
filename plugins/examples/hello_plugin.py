"""Example plugin that registers a greeting tool."""

from thumbelina.plugins.base import Plugin, PluginType


async def register(manager):
    plugin = Plugin(
        id="hello-plugin",
        name="Hello Plugin",
        description="A simple example plugin",
        plugin_type=PluginType.TOOL,
        version="1.0.0",
    )
    await manager.register(plugin)
