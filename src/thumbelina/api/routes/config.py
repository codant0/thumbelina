"""Configuration API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


# ── Response models ──────────────────────────────────────────────────


class QQChannelInfo(BaseModel):
    """QQ channel configuration info."""

    enabled: bool
    app_id: str
    app_secret_set: bool = Field(description="True if app_secret is non-empty")
    allowed_guilds: list[str]
    allowed_groups: list[str]


class WeChatChannelInfo(BaseModel):
    """WeChat channel configuration info."""

    enabled: bool
    ilink_bot_id: str = Field(default="", description="iLink bot ID (empty if not logged in)")
    bot_token_set: bool = Field(description="True if bot_token is non-empty")


class ChannelConfigResponse(BaseModel):
    """Channel configuration snapshot."""

    qq: QQChannelInfo
    wechat: WeChatChannelInfo


class ConfigResponse(BaseModel):
    """Response body for GET /config."""

    provider: str
    model: str
    base_url: str | None = None
    api_key_set: bool = Field(description="True if api_key is non-empty")
    auth_enabled: bool
    rate_limit_enabled: bool
    streaming_enabled: bool
    channels: ChannelConfigResponse


# ── Request models ───────────────────────────────────────────────────


class ConfigUpdateRequest(BaseModel):
    """Request body for POST /config (hot-reloadable fields only)."""

    llm: dict[str, str | bool | None] = Field(default_factory=dict)
    rate_limit: dict[str, bool] = Field(default_factory=dict)


class LLMSwapRequest(BaseModel):
    """Request body for PUT /config/llm."""

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    api_key: str = Field(default="")
    base_url: str | None = None


class LLMSwapResponse(BaseModel):
    """Response body for PUT /config/llm."""

    status: str
    provider: str
    model: str
    base_url: str | None = None


class ChannelSwapRequest(BaseModel):
    """Request body for PUT /config/channels/{name}."""

    enabled: bool
    # QQ-specific (ignored for wechat)
    app_id: str | None = None
    app_secret: str | None = None
    allowed_guilds: list[str] | None = None
    allowed_groups: list[str] | None = None
    # WeChat-specific (ignored for qq)
    bot_token: str | None = None
    ilink_bot_id: str | None = None
    ilink_user_id: str | None = None
    ilink_base_url: str | None = None
    webhook_secret: str | None = None


class ChannelSwapResponse(BaseModel):
    """Response body for PUT /config/channels/{name}."""

    status: str
    channel: str
    enabled: bool
    connected: bool


# ── GET /config ──────────────────────────────────────────────────────


@router.get("/config", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    """Return current configuration snapshot.

    Sensitive fields are never returned — only ``*_set`` booleans.
    """
    config: Any = request.app.state.config
    return ConfigResponse(
        provider=config.llm.provider,
        model=config.llm.model,
        base_url=config.llm.base_url,
        api_key_set=bool(config.llm.api_key),
        auth_enabled=bool(config.auth.secret_key),
        rate_limit_enabled=config.rate_limit.enabled,
        streaming_enabled=config.llm.streaming_enabled,
        channels=ChannelConfigResponse(
            qq=QQChannelInfo(
                enabled=config.channels.qq.enabled,
                app_id=config.channels.qq.app_id,
                app_secret_set=bool(config.channels.qq.app_secret),
                allowed_guilds=config.channels.qq.allowed_guilds,
                allowed_groups=config.channels.qq.allowed_groups,
            ),
            wechat=WeChatChannelInfo(
                enabled=config.channels.wechat.enabled,
                ilink_bot_id=config.channels.wechat.ilink_bot_id,
                bot_token_set=bool(config.channels.wechat.bot_token),
            ),
        ),
    )


# ── POST /config (hot-reloadable toggles) ────────────────────────────


@router.post("/config")
async def update_config(
    body: ConfigUpdateRequest,
    request: Request,
) -> dict[str, str]:
    """Apply runtime configuration changes.

    Only ``streaming_enabled`` and ``rate_limit.enabled`` can be changed
    at runtime via this endpoint.  Use ``PUT /config/llm`` or
    ``PUT /config/channels/{name}`` for full hot-swap.
    """
    config = request.app.state.config

    if "streaming_enabled" in body.llm:
        config.llm.streaming_enabled = bool(body.llm["streaming_enabled"])

    if "enabled" in body.rate_limit:
        config.rate_limit.enabled = body.rate_limit["enabled"]

    return {"status": "ok"}


# ── PUT /config/llm ─────────────────────────────────────────────────


@router.put("/config/llm", response_model=LLMSwapResponse)
async def swap_llm(body: LLMSwapRequest, request: Request) -> LLMSwapResponse:
    """Hot-swap the LLM provider/model at runtime."""
    manager = request.app.state.runtime_config_manager
    agent = request.app.state.agent

    try:
        await manager.swap_llm_provider(
            new_provider=body.provider,
            new_model=body.model,
            new_api_key=body.api_key,
            new_base_url=body.base_url,
            agent=agent,
            skill_engine=getattr(request.app.state, "skill_engine", None),
            composition_engine=getattr(request.app.state, "composition_engine", None),
            subagent_manager=getattr(request.app.state, "subagent_manager", None),
            user_profiler=getattr(request.app.state, "user_profiler", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return LLMSwapResponse(
        status="ok",
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
    )


# ── PUT /config/channels/{channel_name} ──────────────────────────────


@router.put(
    "/config/channels/{channel_name}",
    response_model=ChannelSwapResponse,
)
async def swap_channel(
    channel_name: str,
    body: ChannelSwapRequest,
    request: Request,
) -> ChannelSwapResponse:
    """Hot-swap a channel configuration at runtime."""
    if channel_name not in ("qq", "wechat"):
        raise HTTPException(400, f"Unknown channel: {channel_name}")

    manager = request.app.state.runtime_config_manager
    agent = request.app.state.agent
    config = request.app.state.config

    # Build the typed config object from the request + existing defaults
    if channel_name == "qq":
        from thumbelina.channels.config import QQChannelConfig

        existing = config.channels.qq
        new_config: Any = QQChannelConfig(
            enabled=body.enabled,
            app_id=(
                body.app_id if body.app_id is not None else existing.app_id
            ),
            app_secret=(
                body.app_secret if body.app_secret is not None
                else existing.app_secret
            ),
            allowed_guilds=(
                body.allowed_guilds if body.allowed_guilds is not None
                else existing.allowed_guilds
            ),
            allowed_groups=(
                body.allowed_groups if body.allowed_groups is not None
                else existing.allowed_groups
            ),
        )
    else:
        from thumbelina.channels.config import WeChatChannelConfig

        existing = config.channels.wechat
        new_config = WeChatChannelConfig(
            enabled=body.enabled,
            bot_token=(
                body.bot_token if body.bot_token is not None
                else existing.bot_token
            ),
            ilink_bot_id=(
                body.ilink_bot_id if body.ilink_bot_id is not None
                else existing.ilink_bot_id
            ),
            ilink_user_id=(
                body.ilink_user_id if body.ilink_user_id is not None
                else existing.ilink_user_id
            ),
            ilink_base_url=(
                body.ilink_base_url if body.ilink_base_url is not None
                else existing.ilink_base_url
            ),
            webhook_secret=(
                body.webhook_secret if body.webhook_secret is not None
                else existing.webhook_secret
            ),
        )

    try:
        connected = await manager.swap_channel(
            channel_name=channel_name,
            new_config=new_config,
            app_state=request.app.state,
            agent=agent,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return ChannelSwapResponse(
        status="ok",
        channel=channel_name,
        enabled=new_config.enabled,
        connected=connected,
    )
