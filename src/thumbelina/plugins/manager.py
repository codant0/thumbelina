"""Plugin manager for registering and managing plugins."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys

from thumbelina.plugins.base import Plugin, PluginType
from thumbelina.plugins.dependency import PluginMetadata, parse_plugin_metadata
from thumbelina.plugins.resolver import DependencyResolver
from thumbelina.plugins.sandboxed_loader import SandboxedPluginLoader

logger = logging.getLogger(__name__)


class PluginManager:
    """Manager for registering and managing plugins.

    Parameters
    ----------
    sandboxed_loader:
        Optional :class:`SandboxedPluginLoader` for sandboxed plugin loading.
        When provided, ``load_plugins_from_directory`` uses it for validation.
    """

    def __init__(self, sandboxed_loader: SandboxedPluginLoader | None = None) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._metadata_cache: dict[str, PluginMetadata] = {}
        self._resolver = DependencyResolver()
        self._sandboxed_loader = sandboxed_loader

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
        self._metadata_cache.pop(plugin_id, None)
        return True

    async def list_by_type(self, plugin_type: PluginType) -> list[Plugin]:
        """List plugins by type."""
        return [p for p in self._plugins.values() if p.plugin_type == plugin_type]

    def resolve_dependencies(self) -> tuple[list[str], list[str]]:
        """Resolve dependencies among cached plugin metadata.

        Returns
        -------
        tuple[list[str], list[str]]
            ``(load_order, errors)`` from the dependency resolver.
        """
        return self._resolver.resolve(self._metadata_cache)

    def get_dependency_graph(self) -> dict:
        """Return the dependency graph as a serialisable dict.

        Returns
        -------
        dict
            Contains ``plugins`` (mapping name to info dict),
            ``load_order`` (list of names), and ``errors`` (list of strings).
        """
        load_order, errors = self.resolve_dependencies()

        plugins_info: dict[str, dict] = {}
        for name, meta in self._metadata_cache.items():
            plugins_info[name] = {
                "name": meta.name,
                "version": meta.version,
                "description": meta.description,
                "author": meta.author,
                "dependencies": [
                    {
                        "name": d.name,
                        "version_constraint": d.version_constraint,
                        "optional": d.optional,
                    }
                    for d in meta.dependencies
                ],
                "conflicts": meta.conflicts,
            }

        return {
            "plugins": plugins_info,
            "load_order": load_order,
            "errors": errors,
        }

    def get_sandbox_report(self) -> list[dict[str, object]]:
        """Return sandbox validation results for all processed plugins.

        Returns
        -------
        list[dict[str, object]]
            Each entry contains ``plugin_name``, ``file_path``,
            ``is_valid``, ``loaded``, and ``violations``.
        """
        if self._sandboxed_loader is None:
            return []
        return self._sandboxed_loader.get_report()

    async def load_plugins_from_directory(self, directory: str) -> int:
        """Load plugins from a directory by scanning for Python modules.

        Scans *directory* for files matching ``*.py`` or ``*/__init__.py``.
        Each discovered module is imported and, if it exports a ``register``
        callable, that callable is invoked with *self* so the module can
        register its plugins.

        When plugin metadata is available (via ``__plugin_meta__`` dict or
        docstring ``plugin:`` marker), plugins are loaded in dependency
        order.  Warnings are logged for unmet dependencies or conflicts.

        Parameters
        ----------
        directory:
            Path to the directory to scan.

        Returns
        -------
        int
            Number of plugins successfully loaded.
        """
        if not os.path.isdir(directory):
            logger.warning("Plugin directory does not exist: %s", directory)
            return 0

        # --- Delegation to sandboxed loader when available ---
        if self._sandboxed_loader is not None:
            return await self._sandboxed_loader.load_plugins_from_directory(
                directory, self
            )

        # --- Phase 1: discover all plugin files and parse metadata ---
        discovered: list[tuple[str, str, str, PluginMetadata]] = []
        # (module_name, file_path, source_code, metadata)

        for entry in sorted(os.listdir(directory)):
            module_name: str | None = None
            file_path: str | None = None

            if entry.endswith(".py") and not entry.startswith("_"):
                module_name = entry[:-3]
                file_path = os.path.join(directory, entry)
            elif os.path.isdir(os.path.join(directory, entry)):
                init_path = os.path.join(directory, entry, "__init__.py")
                if os.path.isfile(init_path):
                    module_name = entry
                    file_path = init_path

            if module_name is None or file_path is None:
                continue

            try:
                with open(file_path, encoding="utf-8") as fh:
                    source = fh.read()
            except Exception:
                source = ""

            meta = parse_plugin_metadata(source)
            # If no metadata found, create a default entry using module_name
            if not meta.name:
                meta = PluginMetadata(name=module_name)
            discovered.append((module_name, file_path, source, meta))

        if not discovered:
            return 0

        # --- Phase 2: resolve dependencies to get load order ---
        meta_map: dict[str, PluginMetadata] = {}
        # Map module_name -> (module_name, file_path)
        file_map: dict[str, tuple[str, str]] = {}

        for module_name, file_path, _source, meta in discovered:
            key = meta.name  # Use metadata name as canonical key
            meta_map[key] = meta
            file_map[key] = (module_name, file_path)
            # Cache metadata
            self._metadata_cache[key] = meta

        load_order, errors = self._resolver.resolve(meta_map)

        for error in errors:
            logger.warning("Plugin dependency issue: %s", error)

        # --- Phase 3: load plugins in dependency order ---
        loaded = 0
        loaded_names: set[str] = set()

        for plugin_name in load_order:
            if plugin_name not in file_map:
                continue

            module_name, file_path = file_map[plugin_name]

            # Check if all required (non-optional) dependencies are satisfied
            meta = meta_map[plugin_name]
            skip = False
            for dep in meta.dependencies:
                if not dep.optional and dep.name not in loaded_names:
                    # Check if the dep was supposed to be loaded but failed
                    if dep.name in meta_map:
                        logger.warning(
                            "Skipping plugin '%s': dependency '%s' failed to load",
                            plugin_name,
                            dep.name,
                        )
                    else:
                        logger.warning(
                            "Skipping plugin '%s': dependency '%s' not available",
                            plugin_name,
                            dep.name,
                        )
                    skip = True
                    break
            if skip:
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"thumbelina_plugin_{module_name}",
                    file_path,
                )
                if spec is None or spec.loader is None:
                    logger.warning("Could not create module spec for %s", file_path)
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)

                register_fn = getattr(module, "register", None)
                if callable(register_fn):
                    result = register_fn(self)
                    # Support both sync and async register functions
                    if asyncio.iscoroutine(result):
                        await result
                    loaded += 1
                    loaded_names.add(plugin_name)
                    logger.info("Loaded plugin '%s' from %s", plugin_name, file_path)
                else:
                    logger.warning("Plugin %s has no register() function", file_path)
            except Exception:
                logger.warning(
                    "Failed to load plugin '%s' from %s",
                    plugin_name,
                    file_path,
                    exc_info=True,
                )

        return loaded
