"""Pydantic configuration models for Thumbelina."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openai", min_length=1, description="LLM provider name")
    model: str = Field(default="gpt-4o", description="Model identifier")
    api_key: str = Field(default="", description="API key for the provider")
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
    """

    secret_key: str = Field(
        default="",
        description="Secret key for JWT token signing. Leave empty to disable auth.",
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
