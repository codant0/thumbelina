"""Plugin management API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["plugins"])


def _get_plugin_manager(request: Request):
    """Get the PluginManager from app.state, if available."""
    return getattr(request.app.state, "plugin_manager", None)


@router.get("/plugins")
async def list_plugins(request: Request) -> JSONResponse:
    """List all loaded plugins with their sandbox validation status.

    Returns a JSON array of plugin objects, each containing basic
    plugin info and sandbox validation results when available.
    """
    plugin_manager = _get_plugin_manager(request)
    if plugin_manager is None:
        return JSONResponse(content=[])

    plugins = await plugin_manager.list_plugins()
    sandbox_report = plugin_manager.get_sandbox_report()

    # Build a lookup from plugin name to sandbox result
    sandbox_lookup: dict[str, dict] = {}
    for entry in sandbox_report:
        sandbox_lookup[entry["plugin_name"]] = entry

    result = []
    for plugin in plugins:
        plugin_info = {
            "id": plugin.id,
            "name": plugin.name,
            "description": plugin.description,
            "plugin_type": plugin.plugin_type.value,
            "version": plugin.version,
            "enabled": plugin.enabled,
        }
        # Attach sandbox info if available
        if plugin.name in sandbox_lookup:
            plugin_info["sandbox"] = {
                "is_valid": sandbox_lookup[plugin.name].get("is_valid", True),
                "violation_count": len(
                    sandbox_lookup[plugin.name].get("violations", [])
                ),
            }
        result.append(plugin_info)

    return JSONResponse(content=result)


@router.get("/plugins/sandbox-report")
async def sandbox_report(request: Request) -> JSONResponse:
    """Return the detailed sandbox validation report.

    Includes per-plugin validation results, violations, and loading status.
    """
    plugin_manager = _get_plugin_manager(request)
    if plugin_manager is None:
        return JSONResponse(
            content={"message": "Plugin manager not available", "report": []}
        )

    report = plugin_manager.get_sandbox_report()
    return JSONResponse(content={"report": report})
