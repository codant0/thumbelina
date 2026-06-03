"""Pydantic configuration models for Thumbelina."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from thumbelina.channels.config import (  # noqa: F401
    ChannelsConfig,
    QQChannelConfig,
    WeChatChannelConfig,
)


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openai", min_length=1, description="LLM provider name")
    model: str = Field(default="gpt-4o", description="Model identifier")
    api_key: str = Field(default="", description="API key for the provider")
    base_url: str | None = Field(
        default=None,
        description="Custom API base URL for OpenAI-compatible providers",
    )
    request_timeout: float | None = Field(
        default=None,
        description="Timeout in seconds for each LLM request. None = no timeout.",
    )


class MemoryConfig(BaseModel):
    """Memory/database configuration."""

    database_url: str = Field(
        default="sqlite:///thumbelina.db", description="Database connection URL"
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )


class AuthConfig(BaseModel):
    """Authentication configuration.

    When ``secret_key`` is set, all API routes (except ``/health``)
    require a valid Bearer JWT token.

    When ``required_roles`` is non-empty, authenticated users must have
    at least one of the listed roles to access any protected route.
    """

    secret_key: str = Field(
        default="",
        description="Secret key for JWT token signing. Leave empty to disable auth.",
    )
    required_roles: list[str] = Field(
        default_factory=list,
        description=(
            "Global list of roles required to access protected routes. "
            "Leave empty to allow all authenticated users."
        ),
    )


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    enabled: bool = Field(default=False, description="Enable rate limiting")
    max_requests: int = Field(default=60, description="Max requests per window")
    window_seconds: int = Field(default=60, description="Time window in seconds")


class AppConfig(BaseModel):
    """Top-level application configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    plugin_dirs: list[str] = Field(
        default_factory=list,
        description="Directories to scan for plugins at startup",
    )
