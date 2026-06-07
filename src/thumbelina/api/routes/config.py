"""Configuration API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["config"])

# Fields that require an application restart to take effect.
_RESTART_REQUIRED_LLM_FIELDS = frozenset({"provider", "model", "base_url", "api_key"})


class ConfigResponse(BaseModel):
    """Response body for the config endpoint."""

    provider: str
    model: str
    base_url: str | None = None
    auth_enabled: bool
    rate_limit_enabled: bool
    streaming_enabled: bool
    channels: ChannelConfigResponse


class ConfigUpdateRequest(BaseModel):
    """Request body for updating configuration."""

    llm: dict[str, str | bool | None] = Field(default_factory=dict)
    rate_limit: dict[str, bool] = Field(default_factory=dict)


class QQChannelInfo(BaseModel):
    """QQ channel configuration info (read-only)."""

    enabled: bool
    app_id: str
    allowed_guilds: list[str]
    allowed_groups: list[str]


class WeChatChannelInfo(BaseModel):
    """WeChat channel configuration info (read-only)."""

    enabled: bool
    weclaw_api_url: str


class ChannelConfigResponse(BaseModel):
    """Channel configuration snapshot."""

    qq: QQChannelInfo
    wechat: WeChatChannelInfo


@router.get("/config", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    """Return current read-only configuration snapshot."""
    config = request.app.state.config
    return ConfigResponse(
        provider=config.llm.provider,
        model=config.llm.model,
        base_url=config.llm.base_url,
        auth_enabled=bool(config.auth.secret_key),
        rate_limit_enabled=config.rate_limit.enabled,
        streaming_enabled=config.llm.streaming_enabled,
        channels=ChannelConfigResponse(
            qq=QQChannelInfo(
                enabled=config.channels.qq.enabled,
                app_id=config.channels.qq.app_id,
                allowed_guilds=config.channels.qq.allowed_guilds,
                allowed_groups=config.channels.qq.allowed_groups,
            ),
            wechat=WeChatChannelInfo(
                enabled=config.channels.wechat.enabled,
                weclaw_api_url=config.channels.wechat.weclaw_api_url,
            ),
        ),
    )


@router.post("/config")
async def update_config(
    body: ConfigUpdateRequest,
    request: Request,
) -> dict[str, str]:
    """Apply runtime configuration changes.

    Only ``streaming_enabled`` and ``rate_limit.enabled`` can be changed
    at runtime.  All other fields require an application restart.
    """
    config = request.app.state.config

    # Reject fields that require a restart
    requested_restart_fields = _RESTART_REQUIRED_LLM_FIELDS & body.llm.keys()
    if requested_restart_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot change {', '.join(sorted(requested_restart_fields))} at runtime. "
                "These fields require an application restart."
            ),
        )

    # Hot-reloadable: streaming toggle
    if "streaming_enabled" in body.llm:
        config.llm.streaming_enabled = bool(body.llm["streaming_enabled"])

    # Hot-reloadable: rate limit toggle
    if "enabled" in body.rate_limit:
        config.rate_limit.enabled = body.rate_limit["enabled"]

    return {"status": "ok"}
