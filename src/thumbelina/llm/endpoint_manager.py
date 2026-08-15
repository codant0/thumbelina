from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, field_validator

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.config.models import parse_context_window
from thumbelina.llm.base import ConnectionTestResult, SpeedTestResult
from thumbelina.llm.factory import create_provider

logger = logging.getLogger(__name__)

_INDEX_KEY = "llm_endpoints.index"


def _normalize_context_window(value: Any) -> str | None:
    """校验用户提供的上下文窗口；``None``/空值表示清除。

    对 ``"12X"`` 之类的畸形规格抛出 ``ValueError``（由 Pydantic
    包装为校验错误）。
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    parse_context_window(value)  # 格式无效时抛出 ValueError
    return str(value).strip()


class LLMEndpoint(BaseModel):
    """Persisted LLM endpoint record."""

    id: str
    provider: str
    name: str
    base_url: str
    models: list[str] = []
    active_model: str | None = None
    api_key: str = ""
    api_key_set: bool = False
    is_default: bool = False
    context_window: str | None = None
    last_latency_ms: int | None = None
    last_total_ms: int | None = None
    is_reachable: bool | None = None
    last_tested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("context_window", mode="before")
    @classmethod
    def _validate_context_window(cls, value: Any) -> str | None:
        return _normalize_context_window(value)

    @property
    def context_window_tokens(self) -> int | None:
        """已配置时，上下文窗口归一化为 token 数量。"""
        if self.context_window is None:
            return None
        return parse_context_window(self.context_window)


class LLMEndpointCreate(BaseModel):
    """Input for creating an endpoint."""

    provider: str
    name: str
    base_url: str
    models: list[str] = []
    api_key: str = ""
    is_default: bool = False
    context_window: str | None = None

    @field_validator("context_window", mode="before")
    @classmethod
    def _validate_context_window(cls, value: Any) -> str | None:
        return _normalize_context_window(value)


class LLMEndpointUpdate(BaseModel):
    """Input for updating an endpoint."""

    name: str | None = None
    base_url: str | None = None
    models: list[str] | None = None
    api_key: str | None = None
    is_default: bool | None = None
    context_window: str | None = None

    @field_validator("context_window", mode="before")
    @classmethod
    def _validate_context_window(cls, value: Any) -> str | None:
        return _normalize_context_window(value)


class LLMEndpointActivate(BaseModel):
    """Input for activating a specific model on an endpoint."""

    model: str


class EndpointManager:
    """CRUD + speed-test manager for LLM endpoints."""

    def __init__(self, config_repo: ConfigRepository) -> None:
        self._repo = config_repo

    def _record_key(self, endpoint_id: str) -> str:
        return f"llm_endpoints.{endpoint_id}"

    async def _load_index(self) -> list[str]:
        raw = await self._repo.get(_INDEX_KEY)
        if raw is None:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    async def _save_index(self, index: list[str]) -> None:
        await self._repo.set(_INDEX_KEY, json.dumps(index), "llm_endpoints")

    async def _get_raw(self, endpoint_id: str) -> LLMEndpoint | None:
        raw = await self._repo.get(self._record_key(endpoint_id))
        if raw is None:
            return None
        # Backward compatibility: migrate the legacy single `model` string to
        # `models: [model]` so older persisted records stay usable.
        raw_dict = json.loads(raw)
        if not raw_dict.get("models") and raw_dict.get("model"):
            raw_dict["models"] = [raw_dict.pop("model")]
        return LLMEndpoint.model_validate(raw_dict)

    async def _persist(self, endpoint: LLMEndpoint) -> None:
        await self._repo.set(
            self._record_key(endpoint.id),
            endpoint.model_dump_json(),
            "llm_endpoints",
        )

    async def _clear_all_active(self) -> None:
        """Clear the is_default/active_model flags on every endpoint.

        Activation is global and unique — exactly one (endpoint, model) pair
        may be active at a time, regardless of provider.
        """
        for endpoint in await self.list_endpoints():
            if endpoint.is_default or endpoint.active_model:
                endpoint.is_default = False
                endpoint.active_model = None
                endpoint.updated_at = datetime.now(UTC)
                await self._persist(endpoint)

    async def list_endpoints(self, provider: str | None = None) -> list[LLMEndpoint]:
        index = await self._load_index()
        endpoints: list[LLMEndpoint] = []
        for eid in index:
            endpoint = await self._get_raw(eid)
            if endpoint is None:
                continue
            if provider is None or endpoint.provider == provider:
                endpoints.append(endpoint)
        return endpoints

    async def get_endpoint(self, endpoint_id: str) -> LLMEndpoint | None:
        return await self._get_raw(endpoint_id)

    async def get_active_endpoint_model(self) -> tuple[LLMEndpoint, str] | None:
        """Return the globally active (endpoint, model) pair, if any."""
        for endpoint in await self.list_endpoints():
            if endpoint.is_default and endpoint.active_model:
                return endpoint, endpoint.active_model
        return None

    async def create_endpoint(
        self,
        data: LLMEndpointCreate | None = None,
        **kwargs: Any,
    ) -> LLMEndpoint:
        if data is None:
            data = LLMEndpointCreate(**kwargs)
        now = datetime.now(UTC)
        endpoint = LLMEndpoint(
            id=str(uuid.uuid4()),
            provider=data.provider,
            name=data.name,
            base_url=data.base_url.rstrip("/"),
            models=list(data.models),
            api_key=data.api_key,
            api_key_set=bool(data.api_key),
            is_default=data.is_default,
            context_window=data.context_window,
            active_model=data.models[0] if data.is_default and data.models else None,
            created_at=now,
            updated_at=now,
        )
        if data.is_default:
            await self._clear_all_active()

        await self._persist(endpoint)
        index = await self._load_index()
        index.append(endpoint.id)
        await self._save_index(index)
        return endpoint

    async def update_endpoint(
        self,
        endpoint_id: str,
        data: LLMEndpointUpdate,
    ) -> LLMEndpoint | None:
        endpoint = await self._get_raw(endpoint_id)
        if endpoint is None:
            return None

        if data.name is not None:
            endpoint.name = data.name
        if data.base_url is not None:
            endpoint.base_url = data.base_url.rstrip("/")
        if data.models is not None:
            endpoint.models = list(data.models)
            # Drop an active_model that no longer exists in the list.
            if endpoint.active_model and endpoint.active_model not in endpoint.models:
                endpoint.active_model = None
        if data.api_key is not None:
            endpoint.api_key = data.api_key
            endpoint.api_key_set = bool(data.api_key)
        if "context_window" in data.model_fields_set:
            # 显式的 null/空值清除覆盖；未提供字段则保持原值。
            endpoint.context_window = data.context_window
        if data.is_default is True:
            await self._clear_all_active()
            endpoint.is_default = True
            # Keep the current active_model if still in models, else pick the first.
            if endpoint.models:
                if not endpoint.active_model or endpoint.active_model not in endpoint.models:
                    endpoint.active_model = endpoint.models[0]
            else:
                endpoint.active_model = None
        elif data.is_default is False:
            endpoint.is_default = False
            endpoint.active_model = None

        endpoint.updated_at = datetime.now(UTC)
        await self._persist(endpoint)
        return endpoint

    async def delete_endpoint(self, endpoint_id: str) -> bool:
        endpoint = await self._get_raw(endpoint_id)
        if endpoint is None:
            return False
        await self._repo.delete(self._record_key(endpoint_id))
        index = await self._load_index()
        if endpoint_id in index:
            index.remove(endpoint_id)
            await self._save_index(index)
        return True

    async def activate_model(self, endpoint_id: str, model: str) -> LLMEndpoint | None:
        """Globally activate a specific model on an endpoint.

        Clears any other active (endpoint, model) pair so activation remains
        globally unique.
        """
        endpoint = await self._get_raw(endpoint_id)
        if endpoint is None:
            return None
        if model not in endpoint.models:
            raise ValueError(f"Model '{model}' is not configured on endpoint '{endpoint.name}'")
        await self._clear_all_active()
        endpoint.is_default = True
        endpoint.active_model = model
        endpoint.updated_at = datetime.now(UTC)
        await self._persist(endpoint)
        return endpoint

    async def run_speed_test(self, endpoint_id: str, model: str) -> SpeedTestResult | None:
        endpoint = await self._get_raw(endpoint_id)
        if endpoint is None:
            return None

        provider = create_provider(
            endpoint.provider,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            model=model,
        )
        result = await provider.speed_test(
            model,
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
        )

        endpoint.is_reachable = result.reachable
        endpoint.last_latency_ms = result.latency_ms
        endpoint.last_total_ms = result.total_ms
        endpoint.last_tested_at = result.tested_at or datetime.now(UTC)
        endpoint.updated_at = datetime.now(UTC)
        await self._persist(endpoint)
        return result

    async def test_connection(
        self,
        endpoint_id: str,
        model: str | None = None,
    ) -> ConnectionTestResult | None:
        """Run a lightweight connectivity test against a saved endpoint."""
        endpoint = await self._get_raw(endpoint_id)
        if endpoint is None:
            return None

        effective_model = (
            model or endpoint.active_model or (endpoint.models[0] if endpoint.models else None)
        )
        provider = create_provider(
            endpoint.provider,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            model=effective_model or "gpt-4o",
        )
        result = await provider.test_connection(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            model=effective_model,
        )

        endpoint.is_reachable = result.reachable
        endpoint.last_tested_at = result.tested_at or datetime.now(UTC)
        endpoint.updated_at = datetime.now(UTC)
        await self._persist(endpoint)
        return result
