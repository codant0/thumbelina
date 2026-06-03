"""Sandboxed plugin loader that validates plugins before loading."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field

from thumbelina.plugins.sandbox import PluginSandbox, SandboxViolation

logger = logging.getLogger(__name__)


@dataclass
class PluginValidationResult:
    """Validation result for a single plugin file.

    Attributes
    ----------
    file_path:
        Path to the plugin file.
    plugin_name:
        Name derived from the file/directory name.
    is_valid:
        Whether the plugin passed validation.
    violations:
        List of sandbox violations found.
    loaded:
        Whether the plugin was actually loaded.
    """

    file_path: str
    plugin_name: str
    is_valid: bool = True
    violations: list[SandboxViolation] = field(default_factory=list)
    loaded: bool = False


class SandboxedPluginLoader:
    """Plugin loader that validates plugins through a sandbox before loading.

    Wraps the standard plugin loading flow with sandbox validation.  In
    advisory mode (default), violations are logged as warnings but plugins
    are still loaded.  In strict mode, plugins with violations are rejected.

    Parameters
    ----------
    sandbox:
        The :class:`PluginSandbox` instance to use for validation.
    strict_mode:
        If *True*, plugins with any violations (including warnings) are
        rejected.  If *False* (default), only plugins with errors are
        rejected.
    """

    def __init__(
        self,
        sandbox: PluginSandbox | None = None,
        strict_mode: bool = False,
    ) -> None:
        self.sandbox = sandbox or PluginSandbox()
        self.strict_mode = strict_mode
        self._results: dict[str, PluginValidationResult] = {}

    @property
    def results(self) -> dict[str, PluginValidationResult]:
        """Validation results keyed by plugin name."""
        return dict(self._results)

    def get_report(self) -> list[dict[str, object]]:
        """Return a serialisable validation report for all processed plugins."""
        report: list[dict[str, object]] = []
        for result in self._results.values():
            report.append({
                "plugin_name": result.plugin_name,
                "file_path": result.file_path,
                "is_valid": result.is_valid,
                "loaded": result.loaded,
                "violations": [
                    {
                        "type": v.violation_type,
                        "message": v.message,
                        "line": v.line,
                    }
                    for v in result.violations
                ],
            })
        return report

    def validate_file(self, file_path: str) -> PluginValidationResult:
        """Validate a single plugin file without loading it.

        Parameters
        ----------
        file_path:
            Absolute path to the Python plugin file.

        Returns
        -------
        PluginValidationResult
            The validation result.
        """
        plugin_name = os.path.splitext(os.path.basename(file_path))[0]

        try:
            with open(file_path, encoding="utf-8") as f:
                source = f.read()
        except OSError as exc:
            result = PluginValidationResult(
                file_path=file_path,
                plugin_name=plugin_name,
                is_valid=False,
                violations=[
                    SandboxViolation(
                        violation_type="error",
                        message=f"Could not read file: {exc}",
                    )
                ],
            )
            self._results[plugin_name] = result
            return result

        is_valid, violations = self.sandbox.validate_plugin(source)

        result = PluginValidationResult(
            file_path=file_path,
            plugin_name=plugin_name,
            is_valid=is_valid,
            violations=violations,
        )

        # In strict mode, treat all violations as failures
        if self.strict_mode and violations:
            result.is_valid = False

        self._results[plugin_name] = result

        # Log violations
        for v in violations:
            if v.violation_type == "error":
                logger.error(
                    "Plugin %s sandbox error (line %s): %s",
                    plugin_name,
                    v.line,
                    v.message,
                )
            else:
                logger.warning(
                    "Plugin %s sandbox warning (line %s): %s",
                    plugin_name,
                    v.line,
                    v.message,
                )

        return result

    async def load_plugins_from_directory(
        self,
        directory: str,
        manager: object,
    ) -> int:
        """Load plugins from *directory* with sandbox validation.

        Parameters
        ----------
        directory:
            Path to the directory to scan.
        manager:
            The :class:`~thumbelina.plugins.manager.PluginManager` instance.

        Returns
        -------
        int
            Number of plugins successfully loaded.
        """
        if not os.path.isdir(directory):
            logger.warning("Plugin directory does not exist: %s", directory)
            return 0

        # Import here to avoid circular imports
        import asyncio

        loaded = 0
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

            # Validate before loading
            validation = self.validate_file(file_path)

            if not validation.is_valid:
                if self.strict_mode:
                    logger.warning(
                        "Plugin %s rejected by sandbox (strict mode): %d violations",
                        module_name,
                        len(validation.violations),
                    )
                    continue
                else:
                    # Advisory mode: log but continue
                    if validation.violations:
                        logger.warning(
                            "Plugin %s has %d sandbox violation(s) "
                            "-- loading anyway (advisory mode)",
                            module_name,
                            len(validation.violations),
                        )

            # Load the module
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
                    result = register_fn(manager)
                    if asyncio.iscoroutine(result):
                        await result
                    loaded += 1
                    validation.loaded = True
                    logger.info("Loaded plugin from %s", file_path)
                else:
                    logger.warning("Plugin %s has no register() function", file_path)
            except Exception:
                logger.warning(
                    "Failed to load plugin from %s", file_path, exc_info=True
                )

        return loaded
