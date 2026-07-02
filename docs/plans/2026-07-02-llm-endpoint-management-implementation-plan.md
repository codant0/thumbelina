# LLM Endpoint Management — 实现计划

> **日期：** 2026-07-02
> **功能：** 多 base_url 的 LLM 端点管理，支持模型列表获取与速度测试。
> **目标：** 允许用户保存多个 OpenAI 兼容端点，拉取可用模型，执行延迟 / 可用性测试，并设置一个主 LLM 表单可复用的默认端点。
> **技术栈：** FastAPI + Python 3.11（后端），React 19 + TypeScript + Vite + Vitest（前端）。
> **架构概述：** 扩展 `LLMProvider` 的 `list_models` 和 `speed_test` 能力，在 `OpenAIProvider` 中实现；基于 `ConfigRepository` 构建 `EndpointManager`；在 `/api/v1/config/llm` 下暴露 REST 路由；并在设置页面中构建 React 的 `EndpointManager` + `ModelSelector`。

---

## 后端任务

### 任务 1 — 扩展 `LLMProvider` 基类

**涉及文件**
- 修改：`src/thumbelina/llm/base.py`
- 修改：`src/thumbelina/llm/anthropic.py`
- 修改：`src/thumbelina/llm/ollama.py`
- 测试：`tests/test_llm/test_base.py`

**步骤 1 — 编写失败的测试**

```python
# tests/test_llm/test_base.py
from __future__ import annotations

import pytest

from thumbelina.llm.base import LLMProvider, SpeedTestResult


def test_speed_test_result_has_reachable_field():
    result = SpeedTestResult(reachable=True, latency_ms=123, total_ms=456)
    assert result.reachable is True
    assert result.latency_ms == 123
    assert result.total_ms == 456


def test_provider_has_list_models_and_speed_test_methods():
    assert hasattr(LLMProvider, "list_models")
    assert hasattr(LLMProvider, "speed_test")
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_llm/test_base.py -x -q
```

预期失败：`ImportError: cannot import name 'SpeedTestResult' from 'thumbelina.llm.base'`。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/llm/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


@dataclass
class SpeedTestResult:
    """Result of a lightweight endpoint latency / availability test."""

    reachable: bool
    latency_ms: int | None = None        # time-to-first-token (TTFB)
    total_ms: int | None = None          # full round-trip for a minimal request
    error: str | None = None
    tested_at: datetime | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    # ... existing code ...

    @abstractmethod
    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        """Return model IDs available at the given endpoint."""
        ...

    @abstractmethod
    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        """Run a minimal request and measure latency."""
        ...
```

```python
# src/thumbelina/llm/anthropic.py
from thumbelina.llm.base import LLMProvider, SpeedTestResult

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        raise NotImplementedError("Anthropic does not support model listing yet.")

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        raise NotImplementedError("Anthropic does not support speed tests yet.")
```

```python
# src/thumbelina/llm/ollama.py
from thumbelina.llm.base import LLMProvider, SpeedTestResult

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        raise NotImplementedError("Ollama does not support model listing yet.")

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        raise NotImplementedError("Ollama does not support speed tests yet.")
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
pytest tests/test_llm/test_base.py -x -q
```

预期结果：2 passed。

**步骤 5 — Commit message**

```
feat(llm): add list_models and speed_test abstract methods to LLMProvider

Adds SpeedTestResult dataclass and stubs for Anthropic/Ollama.
```

---

### 任务 2 — 实现 `OpenAIProvider.list_models`

**涉及文件**
- 修改：`src/thumbelina/llm/openai.py`
- 测试：`tests/test_llm/test_openai_provider.py`

**步骤 1 — 编写失败的测试**

```python
# tests/test_llm/test_openai_provider.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from thumbelina.llm.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_lists_models():
    provider = OpenAIProvider(api_key="test-key")
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}]
    }
    mock_response.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        models = await provider.list_models(base_url="https://api.openai.com/v1")

    assert models == ["gpt-4o", "gpt-3.5-turbo"]
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_llm/test_openai_provider.py::test_openai_provider_lists_models -x -q
```

预期失败：`AttributeError: 'OpenAIProvider' object has no attribute 'list_models'`。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/llm/openai.py
from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """LLM provider that delegates to OpenAI models via LangChain."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        from langchain_openai import ChatOpenAI

        self._model_name = model
        self._api_key = api_key
        self._base_url = base_url
        self._model = ChatOpenAI(
            api_key=api_key,
            model=model,
            base_url=base_url,
            **kwargs,
        )

    # ... existing model / chat_model properties ...

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        """Return model IDs from the OpenAI /v1/models endpoint."""
        url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
        key = api_key or self._api_key
        headers: dict[str, str] = {"Authorization": f"Bearer {key}"} if key else {}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/models", headers=headers, timeout=30.0)
            response.raise_for_status()
            payload = response.json()

        return [m["id"] for m in payload.get("data", []) if "id" in m]
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
pytest tests/test_llm/test_openai_provider.py::test_openai_provider_lists_models -x -q
```

预期结果：1 passed。

**步骤 5 — Commit message**

```
feat(llm): implement OpenAIProvider.list_models
```

---

### 任务 3 — 实现 `OpenAIProvider.speed_test`

**涉及文件**
- 修改：`src/thumbelina/llm/openai.py`
- 测试：`tests/test_llm/test_openai_provider.py`

**步骤 1 — 编写失败的测试**

```python
# tests/test_llm/test_openai_provider.py
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from thumbelina.llm.base import SpeedTestResult


@pytest.mark.asyncio
async def test_openai_provider_speed_test_reachable():
    provider = OpenAIProvider(api_key="test-key")

    async def _fake_aiter_text():
        yield "{"
        yield "}"

    mock_response = MagicMock()
    mock_response.aiter_text = _fake_aiter_text
    mock_response.raise_for_status = AsyncMock()

    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient.stream", return_value=mock_context):
        result = await provider.speed_test(
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )

    assert isinstance(result, SpeedTestResult)
    assert result.reachable is True
    assert isinstance(result.latency_ms, int)
    assert isinstance(result.total_ms, int)
    assert result.total_ms >= result.latency_ms


@pytest.mark.asyncio
async def test_openai_provider_speed_test_unreachable():
    provider = OpenAIProvider(api_key="test-key")

    with patch(
        "httpx.AsyncClient.stream",
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = await provider.speed_test(
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )

    assert isinstance(result, SpeedTestResult)
    assert result.reachable is False
    assert result.error is not None
    assert "Connection refused" in result.error
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_llm/test_openai_provider.py -x -q
```

预期失败：`AttributeError: 'OpenAIProvider' object has no attribute 'speed_test'`。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/llm/openai.py
import time
from datetime import datetime, timezone

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        """Run a minimal streamed chat completion and measure latency."""
        url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
        key = api_key or self._api_key
        headers: dict[str, str] = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": True,
        }

        start = time.perf_counter()
        latency_ms: int | None = None
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                ) as response:
                    response.raise_for_status()
                    async for _ in response.aiter_text():
                        if latency_ms is None:
                            latency_ms = int((time.perf_counter() - start) * 1000)
                        break
            total_ms = int((time.perf_counter() - start) * 1000)
            return SpeedTestResult(
                reachable=True,
                latency_ms=latency_ms or total_ms,
                total_ms=total_ms,
                tested_at=datetime.now(timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI speed test failed: %s", exc)
            return SpeedTestResult(
                reachable=False,
                error=str(exc),
                tested_at=datetime.now(timezone.utc),
            )
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
pytest tests/test_llm/test_openai_provider.py -x -q
```

预期结果：3 passed。

**步骤 5 — Commit message**

```
feat(llm): implement OpenAIProvider.speed_test
```

---

### 任务 4 — 创建 `EndpointManager`

**涉及文件**
- 创建：`src/thumbelina/llm/endpoint_manager.py`
- 测试：`tests/test_llm/test_endpoint_manager.py`

**步骤 1 — 编写失败的测试**

```python
# tests/test_llm/test_endpoint_manager.py
from __future__ import annotations

import pytest

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.endpoint_manager import EndpointManager


@pytest.fixture
def config_repo():
    repo = ConfigRepository("sqlite:///:memory:")
    yield repo
    repo.close()


@pytest.fixture
def manager(config_repo):
    return EndpointManager(config_repo=config_repo)


@pytest.mark.asyncio
async def test_create_endpoint(manager):
    endpoint = await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    assert endpoint.provider == "openai"
    assert endpoint.name == "OpenAI Default"
    assert endpoint.base_url == "https://api.openai.com/v1"
    assert endpoint.api_key_set is True
    assert endpoint.is_default is False


@pytest.mark.asyncio
async def test_list_endpoints(manager):
    await manager.create_endpoint(
        provider="openai",
        name="OpenAI Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    endpoints = await manager.list_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0].name == "OpenAI Default"


@pytest.mark.asyncio
async def test_default_endpoint_uniqueness(manager):
    first = await manager.create_endpoint(
        provider="openai",
        name="First",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        is_default=True,
    )
    second = await manager.create_endpoint(
        provider="openai",
        name="Second",
        base_url="https://api.other.com/v1",
        api_key="sk-test",
        is_default=True,
    )
    assert first.is_default is True
    updated_first = await manager.get_endpoint(first.id)
    assert updated_first.is_default is False
    assert second.is_default is True
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_llm/test_endpoint_manager.py -x -q
```

预期失败：`ModuleNotFoundError: No module named 'thumbelina.llm.endpoint_manager'`。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/llm/endpoint_manager.py
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from thumbelina.config.config_repo import ConfigRepository
from thumbelina.llm.base import SpeedTestResult
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
                endpoint.updated_at = datetime.now(timezone.utc)
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

    async def create_endpoint(self, data: LLMEndpointCreate) -> LLMEndpoint:
        now = datetime.now(timezone.utc)
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

        endpoint.updated_at = datetime.now(timezone.utc)
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
        endpoint.last_tested_at = result.tested_at or datetime.now(timezone.utc)
        endpoint.updated_at = datetime.now(timezone.utc)
        await self._persist(endpoint)
        return result
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
pytest tests/test_llm/test_endpoint_manager.py -x -q
```

预期结果：3 passed。

**步骤 5 — Commit message**

```
feat(llm): add EndpointManager for LLM endpoint CRUD and speed tests
```

---
### 任务 5 — 添加端点 API 路由

**文件**
- 修改：`src/thumbelina/api/routes/config.py`
- 测试：`tests/test_api/test_config_endpoints.py`

**步骤 1 — 编写失败测试**

```python
# tests/test_api/test_config_endpoints.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.api.app import create_app
from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig
from thumbelina.llm.base import SpeedTestResult
from thumbelina.llm.endpoint_manager import EndpointManager, LLMEndpoint


@pytest.fixture
def client():
    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        memory=MemoryConfig(database_url="sqlite:///:memory:"),
    )
    app = create_app(config)
    app.state.endpoint_manager = MagicMock(spec=EndpointManager)
    with TestClient(app) as client:
        yield client


def test_list_endpoints(client):
    client.app.state.endpoint_manager.list_endpoints = AsyncMock(return_value=[])
    response = client.get("/api/v1/config/llm/endpoints")
    assert response.status_code == 200
    assert response.json() == []


def test_create_endpoint(client):
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        api_key_set=True,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager.create_endpoint = AsyncMock(return_value=endpoint)
    response = client.post(
        "/api/v1/config/llm/endpoints",
        json={
            "provider": "openai",
            "name": "Default",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "openai"
    assert "api_key" not in data
    assert data["api_key_set"] is True
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_api/test_config_endpoints.py -x -q
```

预期失败：`/api/v1/config/llm/endpoints` 返回 `404 Not Found`。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/api/routes/config.py
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from thumbelina.llm.endpoint_manager import (
    EndpointManager,
    LLMEndpoint,
    LLMEndpointCreate,
    LLMEndpointUpdate,
)
from thumbelina.llm.factory import create_provider

# ... existing models ...


class LLMEndpointResponse(BaseModel):
    """LLM endpoint without secrets."""

    id: str
    provider: str
    name: str
    base_url: str
    api_key_set: bool
    is_default: bool
    last_latency_ms: int | None = None
    last_total_ms: int | None = None
    is_reachable: bool | None = None
    last_tested_at: datetime | None = None


class SpeedTestResponse(BaseModel):
    """Speed test result."""

    endpoint_id: str
    reachable: bool
    latency_ms: int | None = None
    total_ms: int | None = None
    error: str | None = None


class ModelListResponse(BaseModel):
    """Model list from a live endpoint."""

    provider: str
    base_url: str
    models: list[str]


def _to_response(endpoint: LLMEndpoint) -> LLMEndpointResponse:
    return LLMEndpointResponse(
        id=endpoint.id,
        provider=endpoint.provider,
        name=endpoint.name,
        base_url=endpoint.base_url,
        api_key_set=endpoint.api_key_set,
        is_default=endpoint.is_default,
        last_latency_ms=endpoint.last_latency_ms,
        last_total_ms=endpoint.last_total_ms,
        is_reachable=endpoint.is_reachable,
        last_tested_at=endpoint.last_tested_at,
    )


def _get_endpoint_manager(request: Request) -> EndpointManager:
    manager = getattr(request.app.state, "endpoint_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Endpoint manager not available")
    return manager


@router.get("/config/llm/endpoints", response_model=list[LLMEndpointResponse])
async def list_endpoints(
    request: Request,
    provider: str | None = Query(None),
) -> list[LLMEndpointResponse]:
    """List saved LLM endpoints."""
    manager = _get_endpoint_manager(request)
    endpoints = await manager.list_endpoints(provider=provider)
    return [_to_response(e) for e in endpoints]


@router.post(
    "/config/llm/endpoints",
    response_model=LLMEndpointResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    body: LLMEndpointCreate,
    request: Request,
) -> LLMEndpointResponse:
    """Create a new LLM endpoint."""
    manager = _get_endpoint_manager(request)
    endpoint = await manager.create_endpoint(body)
    return _to_response(endpoint)


@router.put("/config/llm/endpoints/{endpoint_id}", response_model=LLMEndpointResponse)
async def update_endpoint(
    endpoint_id: str,
    body: LLMEndpointUpdate,
    request: Request,
) -> LLMEndpointResponse:
    """Update an existing LLM endpoint."""
    manager = _get_endpoint_manager(request)
    endpoint = await manager.update_endpoint(endpoint_id, body)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return _to_response(endpoint)


@router.delete("/config/llm/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(endpoint_id: str, request: Request) -> None:
    """Delete an LLM endpoint."""
    manager = _get_endpoint_manager(request)
    deleted = await manager.delete_endpoint(endpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Endpoint not found")


@router.post(
    "/config/llm/endpoints/{endpoint_id}/speed-test",
    response_model=SpeedTestResponse,
)
async def speed_test_endpoint(
    endpoint_id: str,
    request: Request,
    model: str = Query(...),
) -> SpeedTestResponse:
    """Run a speed test against a saved endpoint."""
    manager = _get_endpoint_manager(request)
    result = await manager.run_speed_test(endpoint_id, model=model)
    if result is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    if result.reachable is False:
        logger.warning("Speed test failed for endpoint %s: %s", endpoint_id, result.error)
    return SpeedTestResponse(
        endpoint_id=endpoint_id,
        reachable=result.reachable,
        latency_ms=result.latency_ms,
        total_ms=result.total_ms,
        error=result.error,
    )


@router.get("/config/llm/models", response_model=ModelListResponse)
async def list_models(
    request: Request,
    provider: str = Query(...),
    base_url: str = Query(...),
    api_key: str | None = Query(None),
) -> ModelListResponse:
    """Fetch model list from a live endpoint."""
    manager = _get_endpoint_manager(request)
    resolved_key = api_key

    # Try to find a matching saved endpoint to reuse its key.
    for endpoint in await manager.list_endpoints(provider=provider):
        if endpoint.base_url.rstrip("/") == base_url.rstrip("/"):
            resolved_key = endpoint.api_key or api_key
            break

    try:
        llm_provider = create_provider(
            provider,
            api_key=resolved_key or "",
            base_url=base_url,
            model="gpt-4o",
        )
        models = await llm_provider.list_models(base_url=base_url, api_key=resolved_key)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        logger.warning("Failed to list models: %s", exc)
        raise HTTPException(status_code=502, detail=f"Failed to reach endpoint: {exc}")

    return ModelListResponse(provider=provider, base_url=base_url, models=models)
```

**步骤 4 — 运行测试命令并查看通过**

```bash
pytest tests/test_api/test_config_endpoints.py -x -q
```

预期：3 个通过。

**步骤 5 — 提交信息**

```
feat(api): add LLM endpoint management routes
```

---

### 任务 6 — 将 `EndpointManager` 接入应用状态

**文件**
- 修改：`src/thumbelina/api/app.py`
- 测试：`tests/test_api/test_config_endpoints.py`（现有）

**步骤 1 — 编写失败测试**

添加到 `tests/test_api/test_config_endpoints.py`：

```python
def test_app_state_has_endpoint_manager(client):
    assert hasattr(client.app.state, "endpoint_manager")
    assert client.app.state.endpoint_manager is not None
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_api/test_config_endpoints.py::test_app_state_has_endpoint_manager -x -q
```

预期失败：`AssertionError: assert hasattr(...)` 为假。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/api/app.py
from thumbelina.llm.endpoint_manager import EndpointManager

# In lifespan(), after config_repo is created:
    config_repo = ConfigRepository(db_url=config.memory.database_url)
    app.state.config_repo = config_repo

    endpoint_manager = EndpointManager(config_repo=config_repo)
    app.state.endpoint_manager = endpoint_manager
```

**步骤 4 — 运行测试命令并查看通过**

```bash
pytest tests/test_api/test_config_endpoints.py -x -q
```

预期：全部通过。

**步骤 5 — 提交信息**

```
feat(api): register EndpointManager in app state
```

---

### 任务 7 — 扩展 `PUT /config/llm` 以接受 `endpoint_id`

**文件**
- 修改：`src/thumbelina/api/routes/config.py`
- 测试：`tests/test_api/test_config_swap_api.py`（现有）

**步骤 1 — 编写失败测试**

添加到 `tests/test_api/test_config_swap_api.py`：

```python
def test_swap_llm_with_endpoint_id(client):
    endpoint = LLMEndpoint(
        id="e1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        api_key_set=True,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager.get_endpoint = AsyncMock(return_value=endpoint)
    response = client.put(
        "/api/v1/config/llm",
        json={
            "provider": "openai",
            "model": "gpt-4o",
            "endpoint_id": "e1",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["base_url"] == "https://api.openai.com/v1"
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
pytest tests/test_api/test_config_swap_api.py::test_swap_llm_with_endpoint_id -x -q
```

预期失败：针对 `endpoint_id` 的 Pydantic 校验错误。

**步骤 3 — 编写最小实现**

```python
# src/thumbelina/api/routes/config.py
class LLMSwapRequest(BaseModel):
    """Request body for PUT /config/llm."""

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    api_key: str = Field(default="")
    base_url: str | None = Field(default=None)
    endpoint_id: str | None = Field(default=None)


@router.put("/config/llm", response_model=LLMSwapResponse)
async def swap_llm(body: LLMSwapRequest, request: Request) -> LLMSwapResponse:
    """Hot-swap the LLM provider/model at runtime."""
    manager = request.app.state.runtime_config_manager
    agent = request.app.state.agent
    endpoint_manager = getattr(request.app.state, "endpoint_manager", None)

    effective_api_key = body.api_key
    effective_base_url = body.base_url

    if endpoint_manager and body.endpoint_id:
        endpoint = await endpoint_manager.get_endpoint(body.endpoint_id)
        if endpoint is None:
            raise HTTPException(status_code=404, detail="Endpoint not found")
        effective_base_url = endpoint.base_url
        effective_api_key = endpoint.api_key or body.api_key

    try:
        await manager.swap_llm_provider(
            new_provider=body.provider,
            new_model=body.model,
            new_api_key=effective_api_key,
            new_base_url=effective_base_url,
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
        base_url=effective_base_url,
    )
```

**步骤 4 — 运行测试命令并查看通过**

```bash
pytest tests/test_api/test_config_swap_api.py -x -q
```

预期：全部通过。

**步骤 5 — 提交信息**

```
feat(api): resolve endpoint_id in PUT /config/llm
```

---

## 前端任务

### 任务 8 — 创建 `api/llmConfig.ts`

**文件**
- 创建: `frontend/src/api/llmConfig.ts`
- 测试: `frontend/src/api/llmConfig.test.ts`

**步骤 1 — 编写失败的测试**

```typescript
// frontend/src/api/llmConfig.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchEndpoints, createEndpoint, fetchModels, runSpeedTest } from './llmConfig'

describe('llmConfig API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('fetchEndpoints returns parsed endpoints', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([{ id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', api_key_set: true, is_default: true }]), { status: 200 }),
    )
    const endpoints = await fetchEndpoints()
    expect(endpoints).toHaveLength(1)
    expect(endpoints[0].name).toBe('Default')
  })

  it('createEndpoint sends api_key in body', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', api_key_set: true, is_default: false }), { status: 201 }),
    )
    await createEndpoint({
      provider: 'openai',
      name: 'Default',
      base_url: 'https://api.openai.com/v1',
      api_key: 'sk-test',
      is_default: false,
    })
    const [, init] = fetchSpy.mock.calls[0]
    const body = JSON.parse(init?.body as string)
    expect(body.api_key).toBe('sk-test')
  })

  it('throws error with backend detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid URL' }), { status: 422 }),
    )
    await expect(createEndpoint({ provider: 'openai', name: 'x', base_url: 'bad', api_key: '', is_default: false })).rejects.toThrow('Invalid URL')
  })
})
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/api/llmConfig.test.ts
```

预期失败: `Error: Cannot find module './llmConfig' or its corresponding type declarations.`

**步骤 3 — 编写最小实现**

```typescript
// frontend/src/api/llmConfig.ts
export interface LLMEndpoint {
  id: string
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key_set: boolean
  is_default: boolean
  last_latency_ms?: number
  last_total_ms?: number
  is_reachable?: boolean
  last_tested_at?: string
}

export interface EndpointFormData {
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key: string
  is_default: boolean
}

export interface SpeedTestResult {
  endpoint_id: string
  reachable: boolean
  latency_ms?: number
  total_ms?: number
  error?: string
}

export interface ModelList {
  provider: string
  base_url: string
  models: string[]
}

const API_BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function fetchEndpoints(provider?: string): Promise<LLMEndpoint[]> {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : ''
  return request<LLMEndpoint[]>(`/config/llm/endpoints${query}`)
}

export async function createEndpoint(data: EndpointFormData): Promise<LLMEndpoint> {
  return request<LLMEndpoint>('/config/llm/endpoints', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updateEndpoint(id: string, data: Partial<EndpointFormData>): Promise<LLMEndpoint> {
  return request<LLMEndpoint>(`/config/llm/endpoints/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteEndpoint(id: string): Promise<void> {
  await request<void>(`/config/llm/endpoints/${id}`, { method: 'DELETE' })
}

export async function runSpeedTest(id: string, model: string): Promise<SpeedTestResult> {
  return request<SpeedTestResult>(`/config/llm/endpoints/${id}/speed-test?model=${encodeURIComponent(model)}`)
}

export async function fetchModels(params: { provider: string; base_url: string; api_key?: string }): Promise<ModelList> {
  const query = new URLSearchParams()
  query.set('provider', params.provider)
  query.set('base_url', params.base_url)
  if (params.api_key) query.set('api_key', params.api_key)
  return request<ModelList>(`/config/llm/models?${query.toString()}`)
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/api/llmConfig.test.ts
```

预期结果: 3 passed.

**步骤 5 — Commit message**

```
feat(frontend): add LLM endpoint API client
```

---

### 任务 9 — 创建 `EndpointList` 组件

**文件**
- 创建: `frontend/src/components/Settings/EndpointList.tsx`
- 测试: `frontend/src/components/Settings/EndpointList.test.tsx`

**步骤 1 — 编写失败的测试**

```typescript
// frontend/src/components/Settings/EndpointList.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EndpointList } from './EndpointList'

const sampleEndpoint = {
  id: '1',
  provider: 'openai' as const,
  name: 'OpenAI Default',
  base_url: 'https://api.openai.com/v1',
  api_key_set: true,
  is_default: true,
  is_reachable: true,
  last_latency_ms: 123,
  last_total_ms: 245,
  last_tested_at: new Date().toISOString(),
}

describe('EndpointList', () => {
  it('renders endpoint name and provider', () => {
    render(<EndpointList endpoints={[sampleEndpoint]} onEdit={vi.fn()} onDelete={vi.fn()} onSpeedTest={vi.fn()} onSetDefault={vi.fn()} testingId={null} />)
    expect(screen.getByText('OpenAI Default')).toBeInTheDocument()
    expect(screen.getByText('openai')).toBeInTheDocument()
  })

  it('emits speed-test event', () => {
    const onSpeedTest = vi.fn()
    render(<EndpointList endpoints={[sampleEndpoint]} onEdit={vi.fn()} onDelete={vi.fn()} onSpeedTest={onSpeedTest} onSetDefault={vi.fn()} testingId={null} />)
    fireEvent.click(screen.getByTestId('speed-test-1'))
    expect(onSpeedTest).toHaveBeenCalledWith('1')
  })
})
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/components/Settings/EndpointList.test.tsx
```

预期失败: `Cannot find module './EndpointList'`.

**步骤 3 — 编写最小实现**

```typescript
// frontend/src/components/Settings/EndpointList.tsx
import type { LLMEndpoint } from '../../api/llmConfig'
import { SpeedTestResult } from './SpeedTestResult'

interface EndpointListProps {
  endpoints: LLMEndpoint[]
  testingId: string | null
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onSpeedTest: (id: string) => void
  onSetDefault: (id: string) => void
}

export function EndpointList({
  endpoints,
  testingId,
  onEdit,
  onDelete,
  onSpeedTest,
  onSetDefault,
}: EndpointListProps) {
  const formatLatency = (ms?: number) => (ms !== undefined ? `${ms} ms` : '—')
  const formatTime = (iso?: string) => (iso ? new Date(iso).toLocaleString() : 'Never')

  return (
    <div className="endpoint-list">
      {endpoints.map((ep) => (
        <div key={ep.id} className="card" data-testid={`endpoint-row-${ep.id}`}>
          <div className="endpoint-row-header">
            <strong>{ep.name}</strong>
            <span className="endpoint-badge">{ep.provider}</span>
            {ep.is_default && <span className="endpoint-default-badge">★ Default</span>}
          </div>
          <div className="endpoint-row-body">
            <span title={ep.base_url}>{ep.base_url}</span>
            <span>
              <span
                className={`endpoint-status-dot ${
                  ep.is_reachable === true
                    ? 'reachable'
                    : ep.is_reachable === false
                      ? 'unreachable'
                      : 'unknown'
                }`}
              />
              {formatLatency(ep.last_latency_ms)} / {formatLatency(ep.last_total_ms)}
            </span>
            <span>{formatTime(ep.last_tested_at)}</span>
          </div>
          <div className="endpoint-row-actions">
            <button
              className="btn btn-ghost btn-sm"
              data-testid={`speed-test-${ep.id}`}
              onClick={() => onSpeedTest(ep.id)}
              disabled={testingId === ep.id}
            >
              {testingId === ep.id ? <SpeedTestResult loading /> : 'Speed Test'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => onEdit(ep.id)}>Edit</button>
            <button className="btn btn-danger btn-sm" onClick={() => onDelete(ep.id)}>Delete</button>
            {!ep.is_default && (
              <button className="btn btn-ghost btn-sm" onClick={() => onSetDefault(ep.id)}>
                Set Default
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/components/Settings/EndpointList.test.tsx
```

预期结果: 2 passed.

**步骤 5 — Commit message**

```
feat(frontend): add EndpointList component
```

---

### 任务 10 — 创建 `EndpointForm` 组件

**文件**
- 创建: `frontend/src/components/Settings/EndpointForm.tsx`
- 测试: `frontend/src/components/Settings/EndpointForm.test.tsx`

**步骤 1 — 编写失败的测试**

```typescript
// frontend/src/components/Settings/EndpointForm.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EndpointForm } from './EndpointForm'

describe('EndpointForm', () => {
  it('validates empty name', async () => {
    const onSubmit = vi.fn()
    render(<EndpointForm onSubmit={onSubmit} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByTestId('endpoint-form-submit'))
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-form-error')).toHaveTextContent('Name is required')
    })
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits correct payload', async () => {
    const onSubmit = vi.fn()
    render(<EndpointForm onSubmit={onSubmit} onCancel={vi.fn()} />)
    fireEvent.change(screen.getByTestId('endpoint-name-input'), { target: { value: 'Default' } })
    fireEvent.change(screen.getByTestId('endpoint-base-url-input'), { target: { value: 'https://api.openai.com/v1' } })
    fireEvent.change(screen.getByTestId('endpoint-api-key-input'), { target: { value: 'sk-test' } })
    fireEvent.click(screen.getByTestId('endpoint-form-submit'))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        provider: 'openai',
        name: 'Default',
        base_url: 'https://api.openai.com/v1',
        api_key: 'sk-test',
        is_default: false,
      })
    })
  })

  it('shows keep-current-key hint when editing', () => {
    render(<EndpointForm onSubmit={vi.fn()} onCancel={vi.fn()} initialValues={{ id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', api_key_set: true, is_default: false }} />)
    expect(screen.getByText(/leave empty to keep current key/i)).toBeInTheDocument()
  })
})
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/components/Settings/EndpointForm.test.tsx
```

预期失败: `Cannot find module './EndpointForm'`.

**步骤 3 — 编写最小实现**

```typescript
// frontend/src/components/Settings/EndpointForm.tsx
import { useState, type FormEvent } from 'react'
import type { EndpointFormData, LLMEndpoint } from '../../api/llmConfig'

interface EndpointFormProps {
  initialValues?: LLMEndpoint
  onSubmit: (data: EndpointFormData) => void
  onCancel: () => void
}

export function EndpointForm({ initialValues, onSubmit, onCancel }: EndpointFormProps) {
  const [provider, setProvider] = useState<'openai' | 'ollama' | 'anthropic'>(initialValues?.provider ?? 'openai')
  const [name, setName] = useState(initialValues?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initialValues?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [isDefault, setIsDefault] = useState(initialValues?.is_default ?? false)
  const [error, setError] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!name.trim()) {
      setError('Name is required')
      return
    }
    if (!provider) {
      setError('Provider is required')
      return
    }
    try {
      // eslint-disable-next-line no-new
      new URL(baseUrl)
    } catch {
      setError('Base URL must be a valid URL')
      return
    }
    onSubmit({
      provider,
      name: name.trim(),
      base_url: baseUrl.trim(),
      api_key: apiKey,
      is_default: isDefault,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="card" data-testid="endpoint-form">
      <div className="card-title">{initialValues ? 'Edit Endpoint' : 'Add Endpoint'}</div>
      <div className="form-group">
        <label className="form-label">Provider</label>
        <select className="form-select" data-testid="endpoint-provider-select" value={provider} onChange={e => setProvider(e.target.value as 'openai' | 'ollama' | 'anthropic')}>
          <option value="openai">OpenAI</option>
          <option value="anthropic" disabled>Anthropic (soon)</option>
          <option value="ollama" disabled>Ollama (soon)</option>
        </select>
      </div>
      <div className="form-group">
        <label className="form-label">Name</label>
        <input className="form-input" data-testid="endpoint-name-input" value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div className="form-group">
        <label className="form-label">Base URL</label>
        <input className="form-input" data-testid="endpoint-base-url-input" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
      </div>
      <div className="form-group">
        <label className="form-label">API Key</label>
        <input className="form-input" data-testid="endpoint-api-key-input" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={initialValues ? 'Leave empty to keep current key' : ''} />
      </div>
      <div className="form-group">
        <label className="form-checkbox">
          <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} />
          Set as default
        </label>
      </div>
      {error && <p className="form-error" data-testid="endpoint-form-error">{error}</p>}
      <div className="settings-actions">
        <button type="submit" className="btn btn-primary" data-testid="endpoint-form-submit">Save</button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/components/Settings/EndpointForm.test.tsx
```

预期结果: 3 passed.

**步骤 5 — Commit message**

```
feat(frontend): add EndpointForm component
```

---

### 任务 11 — 创建 `SpeedTestResult` 组件

**文件**
- 创建: `frontend/src/components/Settings/SpeedTestResult.tsx`
- 测试: 内联在 `EndpointList.test.tsx` 或 `SpeedTestResult.test.tsx`

**步骤 1 — 编写失败的测试**

```typescript
// frontend/src/components/Settings/SpeedTestResult.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SpeedTestResult } from './SpeedTestResult'

describe('SpeedTestResult', () => {
  it('shows loading state', () => {
    render(<SpeedTestResult loading />)
    expect(screen.getByText('Testing…')).toBeInTheDocument()
  })

  it('shows success state', () => {
    render(<SpeedTestResult result={{ endpoint_id: '1', reachable: true, latency_ms: 123, total_ms: 245 }} />)
    expect(screen.getByText('123 ms')).toBeInTheDocument()
    expect(screen.getByText('245 ms')).toBeInTheDocument()
  })

  it('shows error state', () => {
    render(<SpeedTestResult result={{ endpoint_id: '1', reachable: false, error: 'Connection refused' }} />)
    expect(screen.getByText(/Unreachable/)).toBeInTheDocument()
    expect(screen.getByText(/Connection refused/)).toBeInTheDocument()
  })
})
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/components/Settings/SpeedTestResult.test.tsx
```

预期失败: `Cannot find module './SpeedTestResult'`.

**步骤 3 — 编写最小实现**

```typescript
// frontend/src/components/Settings/SpeedTestResult.tsx
import type { SpeedTestResult as SpeedTestResultType } from '../../api/llmConfig'

interface SpeedTestResultProps {
  loading?: boolean
  result?: SpeedTestResultType
}

export function SpeedTestResult({ loading, result }: SpeedTestResultProps) {
  if (loading) {
    return <span className="speed-test-loading">Testing…</span>
  }
  if (!result) {
    return null
  }
  if (result.reachable) {
    return (
      <span className="speed-test-success">
        ✓ {result.latency_ms !== undefined ? `${result.latency_ms} ms` : '—'}
        {' / '}
        {result.total_ms !== undefined ? `${result.total_ms} ms` : '—'}
      </span>
    )
  }
  return (
    <span className="speed-test-error" title={result.error}>
      ✗ Unreachable{result.error ? ` — ${result.error}` : ''}
    </span>
  )
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/components/Settings/SpeedTestResult.test.tsx
```

预期结果: 3 passed.

**步骤 5 — Commit message**

```
feat(frontend): add SpeedTestResult component
```

---

### 任务 12 — 创建 `EndpointManager` 组件

**文件**
- 创建：`frontend/src/components/Settings/EndpointManager.tsx`
- 测试：`frontend/src/components/Settings/EndpointManager.test.tsx`

**步骤 1 — 编写失败的测试**

```typescript
// frontend/src/components/Settings/EndpointManager.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EndpointManager } from './EndpointManager'

const mockEndpoints = [
  { id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', api_key_set: true, is_default: true },
]

describe('EndpointManager', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      const urlStr = typeof url === 'string' ? url : url.toString()
      if (urlStr.includes('/config/llm/endpoints')) {
        return Promise.resolve(new Response(JSON.stringify(mockEndpoints), { status: 200 }))
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    })
  })

  it('renders endpoint list after loading', async () => {
    render(<EndpointManager onMessage={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('Default')).toBeInTheDocument()
    })
  })

  it('opens form on add endpoint click', async () => {
    render(<EndpointManager onMessage={vi.fn()} />)
    fireEvent.click(screen.getByTestId('add-endpoint-button'))
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-form')).toBeInTheDocument()
    })
  })
})
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/components/Settings/EndpointManager.test.tsx
```

预期失败：`Cannot find module './EndpointManager'`。

**步骤 3 — 编写最小实现**

```typescript
// frontend/src/components/Settings/EndpointManager.tsx
import { useEffect, useState, useCallback } from 'react'
import type { LLMEndpoint, EndpointFormData } from '../../api/llmConfig'
import {
  fetchEndpoints,
  createEndpoint,
  updateEndpoint,
  deleteEndpoint,
  runSpeedTest,
} from '../../api/llmConfig'
import { EndpointList } from './EndpointList'
import { EndpointForm } from './EndpointForm'

interface EndpointManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

export function EndpointManager({ onMessage }: EndpointManagerProps) {
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<LLMEndpoint | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchEndpoints()
      setEndpoints(data)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to load endpoints', true)
    } finally {
      setLoading(false)
    }
  }, [onMessage])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async (data: EndpointFormData) => {
    try {
      await createEndpoint(data)
      setShowForm(false)
      onMessage('Endpoint created', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to create endpoint', true)
    }
  }

  const handleUpdate = async (data: EndpointFormData) => {
    if (!editing) return
    try {
      await updateEndpoint(editing.id, data)
      setEditing(null)
      onMessage('Endpoint updated', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to update endpoint', true)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteEndpoint(id)
      onMessage('Endpoint deleted', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to delete endpoint', true)
    }
  }

  const handleSpeedTest = async (id: string) => {
    setTestingId(id)
    try {
      const result = await runSpeedTest(id, 'gpt-4o')
      setEndpoints(prev => prev.map(ep => (ep.id === id ? {
        ...ep,
        is_reachable: result.reachable,
        last_latency_ms: result.latency_ms,
        last_total_ms: result.total_ms,
        last_tested_at: new Date().toISOString(),
      } : ep)))
      onMessage(result.reachable ? 'Speed test complete' : `Speed test failed: ${result.error || ''}`, !result.reachable)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Speed test failed', true)
    } finally {
      setTestingId(null)
    }
  }

  const handleSetDefault = async (id: string) => {
    const ep = endpoints.find(e => e.id === id)
    if (!ep) return
    try {
      await updateEndpoint(id, { is_default: true })
      onMessage('Default endpoint updated', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to set default', true)
    }
  }

  if (loading) return <p>Loading endpoints…</p>

  return (
    <div className="card" data-testid="endpoint-manager">
      <div className="card-title">LLM Endpoints</div>
      <button className="btn btn-primary" data-testid="add-endpoint-button" onClick={() => setShowForm(true)}>Add Endpoint</button>
      {showForm && (
        <EndpointForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <EndpointForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
      )}
      <EndpointList
        endpoints={endpoints}
        testingId={testingId}
        onEdit={id => setEditing(endpoints.find(e => e.id === id) ?? null)}
        onDelete={handleDelete}
        onSpeedTest={handleSpeedTest}
        onSetDefault={handleSetDefault}
      />
    </div>
  )
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/components/Settings/EndpointManager.test.tsx
```

预期结果：2 个测试通过。

**步骤 5 — 提交信息**

```
feat(frontend): add EndpointManager container component
```

---

### 任务 13 — 创建 `ModelSelector` 组件

**文件**
- 创建：`frontend/src/components/Settings/ModelSelector.tsx`
- 测试：`frontend/src/components/Settings/ModelSelector.test.tsx`

**步骤 1 — 编写失败的测试**

```typescript
// frontend/src/components/Settings/ModelSelector.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ModelSelector } from './ModelSelector'

describe('ModelSelector', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches models on button click', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ provider: 'openai', base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-3.5-turbo'] }), { status: 200 }),
    )
    const onSelect = vi.fn()
    render(<ModelSelector provider="openai" base_url="https://api.openai.com/v1" api_key="sk-test" model="" onSelect={onSelect} />)
    fireEvent.click(screen.getByTestId('fetch-models-button'))
    await waitFor(() => {
      const options = screen.getAllByTestId('model-option')
      expect(options).toHaveLength(2)
    })
  })

  it('disables button for unsupported provider', () => {
    render(<ModelSelector provider="anthropic" base_url="" api_key="" model="" onSelect={vi.fn()} />)
    expect(screen.getByTestId('fetch-models-button')).toBeDisabled()
  })
})
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/components/Settings/ModelSelector.test.tsx
```

预期失败：`Cannot find module './ModelSelector'`。

**步骤 3 — 编写最小实现**

```typescript
// frontend/src/components/Settings/ModelSelector.tsx
import { useState, useCallback } from 'react'
import { fetchModels } from '../../api/llmConfig'

interface ModelSelectorProps {
  provider: string
  base_url: string
  api_key: string
  model: string
  onSelect: (model: string) => void
}

export function ModelSelector({ provider, base_url, api_key, model, onSelect }: ModelSelectorProps) {
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const supported = provider === 'openai'

  const handleFetch = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchModels({ provider, base_url, api_key })
      setModels(data.models)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch models')
    } finally {
      setLoading(false)
    }
  }, [provider, base_url, api_key])

  return (
    <div className="model-selector">
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        data-testid="fetch-models-button"
        onClick={handleFetch}
        disabled={!supported || loading || !base_url}
        title={supported ? 'Fetch available models' : 'Model listing not supported for this provider yet.'}
      >
        {loading ? 'Fetching…' : 'Fetch models'}
      </button>
      {error && <span className="form-error">{error}</span>}
      <datalist id="model-options">
        {models.map(m => (
          <option key={m} value={m} data-testid="model-option" />
        ))}
      </datalist>
      <input
        list="model-options"
        type="text"
        className="form-input"
        value={model}
        onChange={e => onSelect(e.target.value)}
        placeholder="Select or type a model"
      />
    </div>
  )
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/components/Settings/ModelSelector.test.tsx
```

预期结果：2 个测试通过。

**步骤 5 — 提交信息**

```
feat(frontend): add ModelSelector component
```

---

### 任务 14 — 集成到 `SettingsPanel`

**文件**
- 修改：`frontend/src/components/Settings/SettingsPanel.tsx`
- 修改：`frontend/src/components/Settings/SettingsPanel.test.tsx`

**步骤 1 — 编写失败的测试**

在 `frontend/src/components/Settings/SettingsPanel.test.tsx` 中添加：

```typescript
  it('should render endpoint manager', async () => {
    render(<SettingsPanel />)
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-manager')).toBeInTheDocument()
    })
  })

  it('should render fetch models button', async () => {
    render(<SettingsPanel />)
    await waitFor(() => {
      expect(screen.getByTestId('fetch-models-button')).toBeInTheDocument()
    })
  })
```

**步骤 2 — 运行测试命令并查看预期失败**

```bash
cd frontend && npm test -- src/components/Settings/SettingsPanel.test.tsx
```

预期失败：`Unable to find element with data-testid "endpoint-manager"`。

**步骤 3 — 编写最小实现**

修改 `frontend/src/components/Settings/SettingsPanel.tsx`：

```typescript
import { useState, useEffect, useCallback, type FormEvent } from 'react'
import { EndpointManager } from './EndpointManager'
import { ModelSelector } from './ModelSelector'

// ... existing interfaces ...

export function SettingsPanel() {
  // ... existing state ...

  return (
    <div className="page-container" data-testid="settings-panel">
      <div className="page-title">Settings</div>

      {/* LLM Configuration */}
      <div className="card">
        <div className="card-title">LLM Configuration</div>
        <form onSubmit={handleSubmit} className="settings-form">
          {/* ... existing provider / base_url / api_key fields ... */}
          <div className="form-group">
            <label className="form-label" htmlFor="model">Model</label>
            <input
              id="model"
              type="text"
              className="form-input"
              data-testid="model-input"
              value={config.model}
              onChange={e => setConfig({ ...config, model: e.target.value })}
            />
            <ModelSelector
              provider={config.provider}
              base_url={config.base_url}
              api_key={config.api_key}
              model={config.model}
              onSelect={model => setConfig(prev => ({ ...prev, model }))}
            />
          </div>
          {/* ... rest of form ... */}
        </form>
        {message && (
          <p data-testid="settings-message" style={{ marginTop: 12, fontSize: 12.5, color: isError ? 'var(--error)' : 'var(--success)' }}>
            {message}
          </p>
        )}
      </div>

      {/* LLM Endpoints */}
      <EndpointManager onMessage={(msg, err) => { setMessage(msg); setIsError(err) }} />

      {/* ... existing user profile / data management cards ... */}
    </div>
  )
}
```

**步骤 4 — 运行测试命令并查看预期通过**

```bash
cd frontend && npm test -- src/components/Settings/SettingsPanel.test.tsx
```

预期结果：所有已有测试 + 新增测试均通过。

**步骤 5 — 提交信息**

```
feat(frontend): integrate EndpointManager and ModelSelector into SettingsPanel
```

---

## 验证任务

### 任务 15 — 后端完整测试套件与代码检查

**文件**
- 上述所有创建/修改的后端文件。

**步骤 1 — 运行测试**

```bash
pytest tests/test_llm/ tests/test_api/test_config_endpoints.py tests/test_api/test_config_swap_api.py -q
```

**步骤 2 — 运行代码检查与类型检查**

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

**步骤 3 — 提交信息**

```
chore(llm): lint and type-check endpoint management backend
```

---

### 任务 16 — 前端完整测试套件与代码检查

**文件**
- 上述所有创建/修改的前端文件。

**步骤 1 — 运行测试**

```bash
cd frontend && npm test
```

**步骤 2 — 运行代码检查与构建**

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

**步骤 3 — 提交信息**

```
chore(frontend): lint and build endpoint management UI
```

---

## 任务清单总结

| # | 任务 | 文件 |
|---|------|-------|
| 1 | 扩展 `LLMProvider` 基类 | `src/thumbelina/llm/base.py`, `src/thumbelina/llm/anthropic.py`, `src/thumbelina/llm/ollama.py`, `tests/test_llm/test_base.py` |
| 2 | 实现 `OpenAIProvider.list_models` | `src/thumbelina/llm/openai.py`, `tests/test_llm/test_openai_provider.py` |
| 3 | 实现 `OpenAIProvider.speed_test` | `src/thumbelina/llm/openai.py`, `tests/test_llm/test_openai_provider.py` |
| 4 | 创建 `EndpointManager` | `src/thumbelina/llm/endpoint_manager.py`, `tests/test_llm/test_endpoint_manager.py` |
| 5 | 添加 API 路由 | `src/thumbelina/api/routes/config.py`, `tests/test_api/test_config_endpoints.py` |
| 6 | 将 `EndpointManager` 接入应用状态 | `src/thumbelina/api/app.py` |
| 7 | 扩展 `PUT /config/llm` 支持 `endpoint_id` | `src/thumbelina/api/routes/config.py`, `tests/test_api/test_config_swap_api.py` |
| 8 | 创建 `api/llmConfig.ts` | `frontend/src/api/llmConfig.ts`, `frontend/src/api/llmConfig.test.ts` |
| 9 | 创建 `EndpointList` 组件 | `frontend/src/components/Settings/EndpointList.tsx`, `frontend/src/components/Settings/EndpointList.test.tsx` |
| 10 | 创建 `EndpointForm` 组件 | `frontend/src/components/Settings/EndpointForm.tsx`, `frontend/src/components/Settings/EndpointForm.test.tsx` |
| 11 | 创建 `SpeedTestResult` 组件 | `frontend/src/components/Settings/SpeedTestResult.tsx`, `frontend/src/components/Settings/SpeedTestResult.test.tsx` |
| 12 | 创建 `EndpointManager` 组件 | `frontend/src/components/Settings/EndpointManager.tsx`, `frontend/src/components/Settings/EndpointManager.test.tsx` |
| 13 | 创建 `ModelSelector` 组件 | `frontend/src/components/Settings/ModelSelector.tsx`, `frontend/src/components/Settings/ModelSelector.test.tsx` |
| 14 | 集成到 `SettingsPanel` | `frontend/src/components/Settings/SettingsPanel.tsx`, `frontend/src/components/Settings/SettingsPanel.test.tsx` |
| 15 | 后端验证 | 后端完整测试套件 |
| 16 | 前端验证 | 前端完整测试套件 |
