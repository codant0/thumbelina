"""Base classes for plugin system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PluginType(StrEnum):
    """Type of plugin."""

    TOOL = "tool"
    SKILL = "skill"
    CHANNEL = "channel"
    PROVIDER = "provider"


@dataclass
class Plugin:
    """A plugin definition.

    Attributes
    ----------
    id:
        Unique identifier.
    name:
        Display name.
    description:
        Description of what the plugin does.
    plugin_type:
        Type of the plugin.
    version:
        Plugin version string.
    enabled:
        Whether the plugin is enabled.
    config:
        Plugin configuration.
    """

    id: str
    name: str
    description: str
    plugin_type: PluginType
    version: str
    enabled: bool = True
    config: dict[str, Any] | None = None
