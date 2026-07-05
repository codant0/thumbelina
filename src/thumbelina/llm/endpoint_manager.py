from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.base import ConnectionTestResult, SpeedTestResult
from thumbelina.llm.factory import create_provider

logger = logging.getLogger(__name__)

_INDEX_KEY = "llm_endpoints.index"


class LLMEndpoint(BaseModel):
    """Persisted LLM endpoint record."""

    id: str
    provider: str
    name: str
    base_url: str
    api_key: str = ""
    api_key_set: bool = False
    is_default: bool = False
    last_latency_ms: int | None = None
    last_total_ms: int | None = None
    is_reachable: bool | None = None
    last_tested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LLMEndpointCreate(BaseModel):
    """Input for creating an endpoint."""

    provider: str
    name: str
    base_url: str
    api_key: str = ""
    is_default: bool = False


class LLMEndpointUpdate(BaseModel):
    """Input for updating an endpoint."""

    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_default: bool | None = None


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
        return LLMEndpoint.model_validate_json(raw)

    async def _persist(self, endpoint: LLMEndpoint) -> None:
        await self._repo.set(
            self._record_key(endpoint.id),
            endpoint.model_dump_json(),
            "llm_endpoints",
        )

    async def _clear_default_for_provider(self, provider: str) -> None:
        for endpoint in await self.list_endpoints(provider=provider):
            if endpoint.is_default:
                endpoint.is_default = False
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
            api_key=data.api_key,
            api_key_set=bool(data.api_key),
            is_default=data.is_default,
            created_at=now,
            updated_at=now,
        )
        if data.is_default:
            await self._clear_default_for_provider(data.provider)

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
        if data.api_key is not None:
            endpoint.api_key = data.api_key
            endpoint.api_key_set = bool(data.api_key)
        if data.is_default is True:
            await self._clear_default_for_provider(endpoint.provider)
            endpoint.is_default = True
        elif data.is_default is False:
            endpoint.is_default = False

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

        provider = create_provider(
            endpoint.provider,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            model=model or "gpt-4o",
        )
        result = await provider.test_connection(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            model=model,
        )

        endpoint.is_reachable = result.reachable
        endpoint.last_tested_at = result.tested_at or datetime.now(UTC)
        endpoint.updated_at = datetime.now(UTC)
        await self._persist(endpoint)
        return result
