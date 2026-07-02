# LLM Endpoint Management — Backend Design

> **Date:** 2026-07-02  
> **Scope:** Backend API and services for multi-base_url management, model list fetching, and speed testing.  
> **Strategy:** Start with OpenAI / OpenAI-compatible providers; define a clean extension point for Ollama and Anthropic later.

---

## 1. Goal

Allow users to:

1. Save multiple LLM base URLs (endpoints) per provider.
2. Fetch the list of available models from a given endpoint after providing an API key.
3. Run a lightweight latency / availability test against an endpoint.
4. Select a default endpoint so that `PUT /config/llm` can reuse it implicitly.

The first implementation targets **OpenAI-compatible endpoints only**. Ollama and Anthropic will be added later by implementing the same provider interface.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Routes  (api/routes/config.py)                     │
│  ├── GET    /api/v1/config/llm/endpoints                    │
│  ├── POST   /api/v1/config/llm/endpoints                    │
│  ├── PUT    /api/v1/config/llm/endpoints/{id}               │
│  ├── DELETE /api/v1/config/llm/endpoints/{id}               │
│  ├── POST   /api/v1/config/llm/endpoints/{id}/speed-test    │
│  ├── GET    /api/v1/config/llm/models                       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  EndpointManager  (llm/endpoint_manager.py)                 │
│  - CRUD on LLMEndpoint records                              │
│  - Persist to ConfigRepository (category: llm_endpoints)    │
│  - Resolve default endpoint                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  LLMProvider  (llm/base.py)                                 │
│  + list_models(base_url, api_key) -> list[str]              │
│  + speed_test(model, base_url, api_key) -> SpeedTestResult  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Provider implementations                                   │
│  OpenAIProvider  —  /v1/models  +  /v1/chat/completions     │
│  (OllamaProvider  —  /api/tags  +  /api/generate)  [future] │
│  (AnthropicProvider — hard-coded list + messages)  [future] │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Components and Responsibilities

### 3.1 `LLMProvider` abstract base (`llm/base.py`)

Two new abstract methods:

```python
from dataclasses import dataclass

@dataclass
class SpeedTestResult:
    reachable: bool
    latency_ms: int | None = None        # time-to-first-token (TTFB)
    total_ms: int | None = None          # full round-trip for a minimal request
    error: str | None = None
    tested_at: datetime | None = None

class LLMProvider(ABC):
    @abstractmethod
    async def list_models(self, *, base_url: str | None = None, api_key: str | None = None) -> list[str]:
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

Rules:
- If a provider does not implement the method, raise `NotImplementedError`.
- `base_url=None` means “use the provider’s configured default base URL”.
- `api_key=None` means “use the provider’s configured API key”.

### 3.2 `OpenAIProvider` (`llm/openai.py`)

Implements:
- `list_models`: `GET {base_url}/v1/models`, read `data[].id`.
- `speed_test`: `POST {base_url}/v1/chat/completions` with `max_tokens=1`, `messages=[{"role":"user","content":"hi"}]`. Measure TTFB and total time.

Use `httpx.AsyncClient` directly for these calls so we do not depend on LangChain for non-chat operations.

### 3.3 `EndpointManager` (`llm/endpoint_manager.py`)

Responsibilities:
- Define `LLMEndpoint` Pydantic model.
- CRUD operations backed by `ConfigRepository`.
- Maintain at most one `is_default=True` endpoint per provider.
- Run speed tests via `create_provider(provider, ...)`.

```python
class LLMEndpoint(BaseModel):
    id: str
    provider: str
    name: str
    base_url: str
    api_key: str = ""                     # never returned to frontend
    api_key_set: bool = False
    is_default: bool = False
    last_latency_ms: int | None = None
    last_total_ms: int | None = None
    is_reachable: bool | None = None
    last_tested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
```

Storage key in `ConfigRepository`: `llm_endpoints.{id}` under category `llm_endpoints`.  
A separate index key `llm_endpoints.index` stores the ordered list of IDs for easy listing.

### 3.4 API Routes (`api/routes/config.py`)

#### Request / Response Models

```python
class LLMEndpointCreate(BaseModel):
    provider: str
    name: str
    base_url: str
    api_key: str = ""
    is_default: bool = False

class LLMEndpointUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_default: bool | None = None

class LLMEndpointResponse(BaseModel):
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
    endpoint_id: str
    reachable: bool
    latency_ms: int | None = None
    total_ms: int | None = None
    error: str | None = None

class ModelListResponse(BaseModel):
    provider: str
    base_url: str
    models: list[str]
```

#### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/config/llm/endpoints` | List saved endpoints, optionally filtered by `provider`. |
| `POST` | `/api/v1/config/llm/endpoints` | Create a new endpoint. |
| `PUT` | `/api/v1/config/llm/endpoints/{id}` | Update endpoint fields. |
| `DELETE` | `/api/v1/config/llm/endpoints/{id}` | Delete endpoint. |
| `POST` | `/api/v1/config/llm/endpoints/{id}/speed-test` | Run speed test and persist result. |
| `GET` | `/api/v1/config/llm/models?provider=&base_url=` | Fetch model list from a live endpoint. Optional `api_key` header if not saved. |

**Security:** `api_key` is write-only. Responses always expose `api_key_set: bool` instead of the key.

### 3.5 Integration with existing `PUT /config/llm`

When `PUT /config/llm` receives `base_url` or `endpoint_id`, it resolves the full endpoint:
- If `endpoint_id` is provided, look it up in `EndpointManager` and use its `base_url` + `api_key`.
- If only `base_url` is provided, fall back to current behavior.
- If `endpoint_id` is the default endpoint, `base_url` becomes optional.

This keeps the existing chat flow unchanged while allowing endpoint reuse.

---

## 4. Data Flow

### 4.1 Fetching model list

1. Frontend calls `GET /api/v1/config/llm/models?provider=openai&base_url=https://api.xxx.com/v1`.
2. Route asks `EndpointManager` for the API key if an endpoint matches `(provider, base_url)`.
3. Route calls `create_provider("openai", api_key=..., base_url=...)`.
4. `OpenAIProvider.list_models(...)` fetches `/v1/models`.
5. Route returns `{ provider, base_url, models: [...] }`.

### 4.2 Speed test

1. Frontend calls `POST /api/v1/config/llm/endpoints/{id}/speed-test`.
2. `EndpointManager` loads the endpoint.
3. It calls `provider.speed_test(model=..., base_url=..., api_key=...)`.
4. Persists `latency_ms`, `total_ms`, `is_reachable`, `last_tested_at` to the endpoint record.
5. Returns `SpeedTestResponse`.

### 4.3 Creating an endpoint

1. Frontend `POST /api/v1/config/llm/endpoints` with name, provider, base_url, api_key.
2. `EndpointManager` validates URL format and provider name.
3. If `is_default=True`, clears default flag on other endpoints of the same provider.
4. Saves endpoint and updates index.
5. Returns `LLMEndpointResponse` with `api_key_set=True`.

---

## 5. Error Handling

| Scenario | HTTP Status | Response Body |
|---|---|---|
| Provider does not support `list_models` / `speed_test` | `501 Not Implemented` | `{ "detail": "Provider 'anthropic' does not support model listing yet." }` |
| Endpoint unreachable / network error | `502 Bad Gateway` | `{ "detail": "Failed to reach endpoint: <reason>" }` |
| Request timeout | `504 Gateway Timeout` | `{ "detail": "Endpoint did not respond in time." }` |
| Invalid provider | `422 Unprocessable Entity` | Standard FastAPI validation |
| Endpoint not found | `404 Not Found` | `{ "detail": "Endpoint not found" }` |
| Duplicate `(provider, base_url)` | `409 Conflict` | `{ "detail": "An endpoint with this base_url already exists." }` |

All provider-specific errors are logged server-side with `logger.warning` / `logger.exception`.

---

## 6. Testing Strategy

### 6.1 Unit tests

- `tests/test_llm/test_openai_provider.py`
  - `test_openai_provider_lists_models` — mock httpx, assert model IDs returned.
  - `test_openai_provider_speed_test_reachable` — mock successful completion.
  - `test_openai_provider_speed_test_unreachable` — mock connection error.

- `tests/test_llm/test_endpoint_manager.py`
  - CRUD operations with in-memory `ConfigRepository`.
  - Default-endpoint uniqueness.
  - Duplicate base_url rejection.

### 6.2 API tests

- `tests/test_api/test_config_endpoints.py` (new file)
  - Create / list / update / delete endpoints.
  - Speed test endpoint returns correct shape.
  - Model list endpoint returns models.
  - `api_key` is never leaked in responses.

Use `respx` or `httpx` transport mocking for external HTTP calls.

### 6.3 Contract tests

- Ensure `LLMEndpointResponse` field names match the frontend `LLMEndpoint` TypeScript interface defined in the companion frontend design doc.

---

## 7. Extension Points for Ollama / Anthropic

| Provider | `list_models` strategy | `speed_test` strategy |
|---|---|---|
| Ollama | `GET {base_url}/api/tags` → `models[].name` | `POST {base_url}/api/generate` with tiny prompt |
| Anthropic | Hard-coded list in `AnthropicProvider` | `POST /v1/messages` with `max_tokens=1` |

To add a provider:
1. Implement the two methods in its provider class.
2. Add the provider name to the frontend provider dropdown.
3. Add API tests.

No changes to `EndpointManager` or routes are required.

---

## 8. Files to Create / Modify

### Create
- `src/thumbelina/llm/endpoint_manager.py`
- `src/thumbelina/llm/models.py` (optional — shared `SpeedTestResult`, `LLMEndpoint` schemas)
- `tests/test_llm/test_openai_provider.py`
- `tests/test_llm/test_endpoint_manager.py`
- `tests/test_api/test_config_endpoints.py`

### Modify
- `src/thumbelina/llm/base.py` — add abstract methods.
- `src/thumbelina/llm/openai.py` — implement methods.
- `src/thumbelina/llm/factory.py` — accept `base_url` for OpenAI (already supports, verify).
- `src/thumbelina/api/routes/config.py` — add new routes.
- `src/thumbelina/api/app.py` — register `EndpointManager` in app state if needed.

---

## 9. Consistency with Frontend Design

| Backend | Frontend | Contract |
|---|---|---|
| `LLMEndpointResponse.id` | `LLMEndpoint.id` | UUID string |
| `LLMEndpointResponse.provider` | `LLMEndpoint.provider` | `"openai" \| "ollama" \| "anthropic"` |
| `LLMEndpointResponse.base_url` | `LLMEndpoint.base_url` | URL string |
| `LLMEndpointResponse.api_key_set` | `LLMEndpoint.api_key_set` | boolean |
| `LLMEndpointResponse.is_default` | `LLMEndpoint.is_default` | boolean |
| `LLMEndpointResponse.last_latency_ms` | `LLMEndpoint.last_latency_ms` | integer or null |
| `LLMEndpointResponse.last_total_ms` | `LLMEndpoint.last_total_ms` | integer or null |
| `LLMEndpointResponse.is_reachable` | `LLMEndpoint.is_reachable` | boolean or null |
| `LLMEndpointResponse.last_tested_at` | `LLMEndpoint.last_tested_at` | ISO 8601 string or null |
| `ModelListResponse.models` | `string[]` | list of model IDs |
| `SpeedTestResponse.latency_ms` | `number` | TTFB in milliseconds |
| `SpeedTestResponse.total_ms` | `number` | total request time |

The frontend design doc is the source of truth for UI state and component names; this doc is the source of truth for the API schema.

---

## 10. Open Questions

1. Should endpoints be scoped per user or global? (Current config system is global; keep global for consistency.)
2. Should `api_key` be encrypted at rest? (Out of scope for first iteration; store as plaintext like existing `config.llm.api_key`.)
3. Should speed tests run automatically when an endpoint is created? (No; manual trigger only to avoid surprising API usage.)
