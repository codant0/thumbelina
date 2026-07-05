"""Pydantic models for LLM provider presets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LLMPreset(BaseModel):
    """Persisted LLM provider preset."""

    id: str
    name: str
    provider: str
    base_url: str
    api_key: str = ""
    api_key_set: bool = False
    model: str = ""
    extra_params: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = False
    created_at: datetime
    updated_at: datetime


class LLMPresetCreate(BaseModel):
    """Request body for creating a preset."""

    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1)
    api_key: str = Field(default="")
    model: str = Field(default="")
    extra_params: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = Field(default=False)


class LLMPresetUpdate(BaseModel):
    """Request body for updating a preset."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = Field(default=None, min_length=1)
    base_url: str | None = Field(default=None, min_length=1)
    api_key: str | None = Field(default=None)
    model: str | None = Field(default=None)
    extra_params: dict[str, Any] | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class LLMPresetResponse(BaseModel):
    """Preset representation returned to clients (no api_key)."""

    id: str
    name: str
    provider: str
    base_url: str
    api_key_set: bool
    model: str
    extra_params: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LLMPresetActivateResponse(BaseModel):
    """Response body for activating a preset."""

    status: str
    preset_id: str
    preset_name: str
    provider: str
    model: str
