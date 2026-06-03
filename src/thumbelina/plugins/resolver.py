"""Plugin dependency resolver using topological sort (Kahn's algorithm)."""

from __future__ import annotations

import logging
from collections import deque

from thumbelina.plugins.dependency import (
    PluginMetadata,
    satisfies_version,
)

logger = logging.getLogger(__name__)


class DependencyResolver:
    """Resolves plugin dependencies and determines load order.

    Uses Kahn's algorithm for topological sort to produce a valid load
    order.  Detects circular dependencies and missing dependencies.
    """

    def resolve(
        self,
        plugins: dict[str, PluginMetadata],
    ) -> tuple[list[str], list[str]]:
        """Determine the correct load order for *plugins*.

        Parameters
        ----------
        plugins:
            Mapping of plugin name to its metadata.

        Returns
        -------
        tuple[list[str], list[str]]
            ``(load_order, errors)`` where *load_order* is the
            topologically sorted list of plugin names and *errors*
            contains human-readable descriptions of problems found.
        """
        errors: list[str] = []

        # Check conflicts first
        errors.extend(self.check_conflicts(plugins))

        # Check missing dependencies
        errors.extend(self.check_missing_dependencies(plugins))

        # Build adjacency list (only for existing plugins)
        # in_degree[name] = number of required deps that must load before name
        in_degree: dict[str, int] = {name: 0 for name in plugins}
        # graph[dep] = list of plugins that depend on dep
        graph: dict[str, list[str]] = {name: [] for name in plugins}

        for name, meta in plugins.items():
            for dep in meta.dependencies:
                if dep.name in plugins:
                    # Only count non-optional or existing deps
                    if not dep.optional or dep.name in plugins:
                        # Check version satisfaction
                        dep_version = plugins[dep.name].version
                        if dep.version_constraint and not satisfies_version(
                            dep_version, dep.version_constraint
                        ):
                            errors.append(
                                f"Plugin '{name}' requires '{dep.name}' "
                                f"{dep.version_constraint} but found {dep_version}"
                            )
                        graph[dep.name].append(name)
                        in_degree[name] += 1
                # Missing deps already reported by check_missing_dependencies

        # Kahn's algorithm
        queue: deque[str] = deque()
        for name in plugins:
            if in_degree[name] == 0:
                queue.append(name)

        load_order: list[str] = []
        while queue:
            current = queue.popleft()
            load_order.append(current)
            for dependent in graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # If not all plugins are in load_order, there's a cycle
        if len(load_order) < len(plugins):
            remaining = set(plugins) - set(load_order)
            errors.append(
                f"Circular dependency detected among: {', '.join(sorted(remaining))}"
            )

        return load_order, errors

    def check_conflicts(
        self,
        plugins: dict[str, PluginMetadata],
    ) -> list[str]:
        """Detect conflict pairs among loaded plugins.

        Parameters
        ----------
        plugins:
            Mapping of plugin name to its metadata.

        Returns
        -------
        list[str]
            Human-readable conflict descriptions.
        """
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()

        for name, meta in plugins.items():
            for conflict_name in meta.conflicts:
                if conflict_name in plugins:
                    pair = tuple(sorted([name, conflict_name]))
                    if pair not in seen:
                        seen.add(pair)
                        errors.append(
                            f"Plugin '{name}' conflicts with '{conflict_name}'"
                        )
        return errors

    def check_missing_dependencies(
        self,
        plugins: dict[str, PluginMetadata],
    ) -> list[str]:
        """Find dependencies that cannot be resolved from available plugins.

        Parameters
        ----------
        plugins:
            Mapping of plugin name to its metadata.

        Returns
        -------
        list[str]
            Human-readable descriptions of missing dependencies.
        """
        errors: list[str] = []
        available = set(plugins)

        for name, meta in plugins.items():
            for dep in meta.dependencies:
                if dep.name not in available:
                    if dep.optional:
                        errors.append(
                            f"Optional dependency '{dep.name}' of plugin "
                            f"'{name}' is not available"
                        )
                    else:
                        errors.append(
                            f"Plugin '{name}' requires '{dep.name}' "
                            f"which is not available"
                        )
        return errors
