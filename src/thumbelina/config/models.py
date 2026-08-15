"""Pydantic configuration models for Thumbelina."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from thumbelina.channels.config import (  # noqa: F401
    ChannelsConfig,
    QQChannelConfig,
    WeChatChannelConfig,
)

_CONTEXT_WINDOW_PATTERN = re.compile(r"^(\d+)\s*([KM])?$", re.IGNORECASE)
_CONTEXT_WINDOW_MULTIPLIERS = {"K": 1_000, "M": 1_000_000}


def parse_context_window(value: str | int) -> int:
    """Parse a context-window specification into a token count.

    Accepts a plain token count (``200000`` or ``"200000"``) or a count with a
    case-insensitive ``K`` (thousand) / ``M`` (million) token suffix, e.g.
    ``"128K"`` or ``"1M"``.

    Raises:
        ValueError: If the specification is malformed or non-positive.
    """
    if isinstance(value, bool):
        raise ValueError(f"Invalid context window: {value!r}")
    if isinstance(value, int):
        tokens = value
    elif isinstance(value, str):
        match = _CONTEXT_WINDOW_PATTERN.match(value.strip())
        if match is None:
            raise ValueError(
                f"Invalid context window {value!r}; expected a positive token count "
                "with an optional K/M suffix (e.g. '128K', '1M')"
            )
        suffix = (match.group(2) or "").upper()
        tokens = int(match.group(1)) * _CONTEXT_WINDOW_MULTIPLIERS.get(suffix, 1)
    else:
        raise ValueError(f"Invalid context window: {value!r}")
    if tokens <= 0:
        raise ValueError(f"Context window must be positive, got {value!r}")
    return tokens


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
    streaming_enabled: bool = Field(
        default=True,
        description="Enable streaming responses. When false, full response is sent at once.",
    )
    role: str = Field(
        default="assistant",
        min_length=1,
        description=(
            "Role persona name; the matching prompt file under "
            "prompts/roles/<role>.md is injected as the system prompt."
        ),
    )
    context_window: str = Field(
        default="128K",
        description=(
            "Default context window of the provider model. Supports K (thousand) / "
            "M (million) token suffixes, case-insensitive. Endpoints may override "
            "this via their own context_window field."
        ),
    )

    @field_validator("context_window", mode="before")
    @classmethod
    def _validate_context_window(cls, value: Any) -> str:
        parse_context_window(value)  # raises ValueError on invalid formats
        return str(value).strip()

    @property
    def context_window_tokens(self) -> int:
        """Context window normalized to a token count."""
        return parse_context_window(self.context_window)


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


class TodoConfig(BaseModel):
    """TODO module configuration (local Markdown files)."""

    enabled: bool = Field(default=True, description="Enable the TODO module")
    directory: str = Field(
        default="TODO",
        description="Directory for the Markdown files (todolist.md / notes.md)",
    )


class ContextCompressConfig(BaseModel):
    """Context compression settings applied when usage nears the window."""

    strategy: Literal["sliding_window", "full_summary", "summary_recent"] = Field(
        default="summary_recent",
        description="Compression strategy used when the context nears the window",
    )
    threshold: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        description="Fraction of the window (0, 1] at which compression triggers",
    )
    recent_turns: int = Field(
        default=6,
        ge=1,
        description="Number of recent turns kept verbatim by the summary_recent strategy",
    )


class ContextConfig(BaseModel):
    """Conversation context (checkpointer) configuration."""

    compress: ContextCompressConfig = Field(default_factory=ContextCompressConfig)


class AppConfig(BaseModel):
    """Top-level application configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    todo: TodoConfig = Field(default_factory=TodoConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins. Use ['*'] for development only.",
    )
    plugin_dirs: list[str] = Field(
        default_factory=list,
        description="Directories to scan for plugins at startup",
    )
