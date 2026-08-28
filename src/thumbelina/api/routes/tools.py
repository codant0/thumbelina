"""Built-in tool configuration API routes.

Currently exposes the web_search tool strategy (Tavily / DuckDuckGo).
Sensitive fields (api_key) are never returned by the API — only
``api_key_set`` — but ``tools.web_search.api_key`` IS persisted to the
config database (scoped allowlist exception; the key is exempted from
the sensitive-key filter for this tool only).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


class WebSearchInfo(BaseModel):
    """Web search tool configuration snapshot (no secrets)."""

    enabled: bool
    provider: Literal["tavily", "duckduckgo"]
    api_key_set: bool


class ToolsConfigResponse(BaseModel):
    """Response body for GET /config/tools."""

    web_search: WebSearchInfo


class WebSearchUpdateRequest(BaseModel):
    """Request body for PUT /config/tools/web_search."""

    enabled: bool | None = None
    provider: Literal["tavily", "duckduckgo"] | None = None
    api_key: str | None = None


@router.get("/config/tools", response_model=ToolsConfigResponse)
async def get_tools_config(request: Request) -> ToolsConfigResponse:
    """Return current built-in tool configuration (no secrets)."""
    config: Any = request.app.state.config
    ws = config.tools.web_search
    return ToolsConfigResponse(
        web_search=WebSearchInfo(
            enabled=ws.enabled,
            provider=ws.provider,
            api_key_set=bool(ws.api_key),
        )
    )


@router.put("/config/tools/web_search", response_model=ToolsConfigResponse)
async def update_web_search_config(
    body: WebSearchUpdateRequest,
    request: Request,
) -> ToolsConfigResponse:
    """Update web_search tool configuration at runtime.

    ``enabled``/``provider`` and ``api_key`` are all persisted to the
    config database (``api_key`` is exempted from the sensitive-key
    filter specifically for this tool). An empty ``api_key`` clears the
    stored key.
    """
    config: Any = request.app.state.config
    ws = config.tools.web_search

    if body.enabled is not None:
        ws.enabled = body.enabled
    if body.provider is not None:
        ws.provider = body.provider
    if body.api_key is not None:
        ws.api_key = body.api_key

    manager = getattr(request.app.state, "runtime_config_manager", None)
    if manager is not None:
        if body.enabled is not None:
            await manager._persist_to_db("tools", "tools.web_search.enabled", ws.enabled)
        if body.provider is not None:
            await manager._persist_to_db("tools", "tools.web_search.provider", ws.provider)
        if body.api_key is not None:
            await manager._persist_to_db("tools", "tools.web_search.api_key", ws.api_key)

    return ToolsConfigResponse(
        web_search=WebSearchInfo(
            enabled=ws.enabled,
            provider=ws.provider,
            api_key_set=bool(ws.api_key),
        )
    )
