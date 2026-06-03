"""Channel configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QQChannelConfig(BaseModel):
    """QQ Bot channel configuration."""

    enabled: bool = Field(default=False, description="Enable QQ Bot channel")
    app_id: str = Field(default="", description="QQ Bot App ID")
    app_secret: str = Field(default="", description="QQ Bot App Secret")
    allowed_guilds: list[str] = Field(
        default_factory=list,
        description="Guild IDs to respond in (empty = all)",
    )
    allowed_groups: list[str] = Field(
        default_factory=list,
        description="Group IDs to respond in (empty = all)",
    )


class WeChatChannelConfig(BaseModel):
    """WeChat ClawBot channel configuration."""

    enabled: bool = Field(default=False, description="Enable WeChat channel")
    weclaw_api_url: str = Field(
        default="http://127.0.0.1:18011",
        description="WeClaw API base URL",
    )
    weclaw_token: str = Field(default="", description="WeClaw authentication token")
    webhook_secret: str = Field(default="", description="Webhook signature verification secret")


class ChannelsConfig(BaseModel):
    """Top-level channels configuration."""

    qq: QQChannelConfig = Field(default_factory=QQChannelConfig)
    wechat: WeChatChannelConfig = Field(default_factory=WeChatChannelConfig)
