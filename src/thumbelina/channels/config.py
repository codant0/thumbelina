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
    """WeChat channel configuration.

    After QR code login, the iLink credential fields (``bot_token``,
    ``ilink_bot_id``, ``ilink_user_id``) are populated automatically.
    The channel uses these to long-poll iLink directly using the
    weixin-bot protocol — no sidecar required.
    """

    enabled: bool = Field(default=False, description="Enable WeChat channel")
    bot_token: str = Field(default="", description="iLink bot token from QR login")
    ilink_bot_id: str = Field(default="", description="iLink bot ID")
    ilink_user_id: str = Field(default="", description="iLink user ID")
    ilink_base_url: str = Field(
        default="https://ilinkai.weixin.qq.com",
        description="iLink API base URL",
    )
    accounts_dir: str = Field(
        default="",
        description=(
            "Directory for saved iLink credentials ({bot_id}.json). "
            "Empty = default CHANNEL/.weclaw/accounts (relative to the "
            "working directory). Point this at a persistent volume "
            "(e.g. /app/data/CHANNEL/.weclaw/accounts) in Docker so "
            "login survives container rebuilds."
        ),
    )
    webhook_secret: str = Field(default="", description="Webhook signature verification secret")


class ChannelsConfig(BaseModel):
    """Top-level channels configuration."""

    qq: QQChannelConfig = Field(default_factory=QQChannelConfig)
    wechat: WeChatChannelConfig = Field(default_factory=WeChatChannelConfig)
