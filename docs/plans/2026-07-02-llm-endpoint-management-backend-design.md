# LLM Endpoint Management — Backend Design

> **Date:** 2026-07-02  
> **Scope:** Backend API 与服务，用于多 base_url 管理、模型列表获取以及速度测试。  
> **Strategy:** 从 OpenAI / OpenAI 兼容提供商开始；为后续支持 Ollama 与 Anthropic 定义清晰的扩展点。

---

## 1. Goal

允许用户：

1. 为每个 provider 保存多个 LLM base URL（endpoint）。
2. 在提供 API key 后，从指定 endpoint 获取可用模型列表。
3. 对 endpoint 执行轻量级延迟 / 可用性测试。
4. 选择默认 endpoint，使 `PUT /config/llm` 可以隐式复用。

首次实现仅针对 **OpenAI 兼容 endpoint**。Ollama 与 Anthropic 将在后续通过实现相同的 provider 接口加入。

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

新增两个抽象方法：

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

规则：
- 如果 provider 未实现该方法，则抛出 `NotImplementedError`。
- `base_url=None` 表示“使用 provider 配置的默认 base URL”。
- `api_key=None` 表示“使用 provider 配置的 API key”。

### 3.2 `OpenAIProvider` (`llm/openai.py`)

实现：
- `list_models`：`GET {base_url}/v1/models`，读取 `data[].id`。
- `speed_test`：`POST {base_url}/v1/chat/completions`，参数为 `max_tokens=1`、`messages=[{"role":"user","content":"hi"}]`。测量 TTFB 与总耗时。

这些调用直接使用 `httpx.AsyncClient`，从而在非聊天场景下不依赖 LangChain。

### 3.3 `EndpointManager` (`llm/endpoint_manager.py`)

职责：
- 定义 `LLMEndpoint` Pydantic model。
- 基于 `ConfigRepository` 的 CRUD 操作。
- 保证每个 provider 最多只有一个 `is_default=True` 的 endpoint。
- 通过 `create_provider(provider, ...)` 运行速度测试。

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

在 `ConfigRepository` 中的存储 key：`llm_endpoints.{id}`，category 为 `llm_endpoints`。  
另一个索引 key `llm_endpoints.index` 保存有序的 ID 列表，便于列出。

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
| `GET` | `/api/v1/config/llm/endpoints` | 列出已保存的 endpoints，可按照 `provider` 过滤。 |
| `POST` | `/api/v1/config/llm/endpoints` | 创建新 endpoint。 |
| `PUT` | `/api/v1/config/llm/endpoints/{id}` | 更新 endpoint 字段。 |
| `DELETE` | `/api/v1/config/llm/endpoints/{id}` | 删除 endpoint。 |
| `POST` | `/api/v1/config/llm/endpoints/{id}/speed-test` | 运行速度测试并持久化结果。 |
| `GET` | `/api/v1/config/llm/models?provider=&base_url=` | 从在线 endpoint 获取模型列表。若未保存，可通过 `api_key` header 提供。 |

**安全：** `api_key` 为仅写字段，响应中始终只暴露 `api_key_set: bool`，不会返回 key 本身。

### 3.5 Integration with existing `PUT /config/llm`

当 `PUT /config/llm` 收到 `base_url` 或 `endpoint_id` 时，按以下规则解析完整 endpoint：
- 若提供了 `endpoint_id`，则在 `EndpointManager` 中查找，并使用其 `base_url` + `api_key`。
- 若只提供了 `base_url`，则保持现有行为回退。
- 若 `endpoint_id` 为默认 endpoint，则 `base_url` 变为可选。

这样可在不改变现有聊天流程的情况下复用 endpoint。

---

## 4. Data Flow

### 4.1 Fetching model list

1. 前端调用 `GET /api/v1/config/llm/models?provider=openai&base_url=https://api.xxx.com/v1`。
2. Route 向 `EndpointManager` 请求匹配 `(provider, base_url)` 的 API key。
3. Route 调用 `create_provider("openai", api_key=..., base_url=...)`。
4. `OpenAIProvider.list_models(...)` 请求 `/v1/models`。
5. Route 返回 `{ provider, base_url, models: [...] }`。

### 4.2 Speed test

1. 前端调用 `POST /api/v1/config/llm/endpoints/{id}/speed-test`。
2. `EndpointManager` 加载 endpoint。
3. 调用 `provider.speed_test(model=..., base_url=..., api_key=...)`。
4. 将 `latency_ms`、`total_ms`、`is_reachable`、`last_tested_at` 持久化到 endpoint 记录。
5. 返回 `SpeedTestResponse`。

### 4.3 Creating an endpoint

1. 前端 `POST /api/v1/config/llm/endpoints`，携带 name、provider、base_url、api_key。
2. `EndpointManager` 校验 URL 格式与 provider 名称。
3. 若 `is_default=True`，清除同 provider 下其他 endpoint 的默认标记。
4. 保存 endpoint 并更新索引。
5. 返回 `LLMEndpointResponse`，其中 `api_key_set=True`。

---

## 5. Error Handling

| 场景 | HTTP Status | Response Body |
|---|---|---|
| Provider 尚未支持 `list_models` / `speed_test` | `501 Not Implemented` | `{ "detail": "Provider 'anthropic' does not support model listing yet." }` |
| Endpoint 不可达 / 网络错误 | `502 Bad Gateway` | `{ "detail": "Failed to reach endpoint: <reason>" }` |
| 请求超时 | `504 Gateway Timeout` | `{ "detail": "Endpoint did not respond in time." }` |
| 无效的 provider | `422 Unprocessable Entity` | 标准 FastAPI 校验错误 |
| Endpoint 不存在 | `404 Not Found` | `{ "detail": "Endpoint not found" }` |
| 重复的 `(provider, base_url)` | `409 Conflict` | `{ "detail": "An endpoint with this base_url already exists." }` |

所有 provider 相关的错误都会通过 `logger.warning` / `logger.exception` 在服务端记录。

---

## 6. Testing Strategy

### 6.1 Unit tests

- `tests/test_llm/test_openai_provider.py`
  - `test_openai_provider_lists_models` — mock httpx，断言返回 model IDs。
  - `test_openai_provider_speed_test_reachable` — mock 成功的 completion。
  - `test_openai_provider_speed_test_unreachable` — mock 连接错误。

- `tests/test_llm/test_endpoint_manager.py`
  - 使用内存中的 `ConfigRepository` 进行 CRUD 操作。
  - 默认 endpoint 唯一性。
  - 重复 base_url 拒绝。

### 6.2 API tests

- `tests/test_api/test_config_endpoints.py`（新文件）
  - 创建 / 列出 / 更新 / 删除 endpoints。
  - 速度测试接口返回正确结构。
  - 模型列表接口返回模型。
  - 响应中绝不泄露 `api_key`。

外部 HTTP 调用使用 `respx` 或 `httpx` transport mocking。

### 6.3 Contract tests

- 确保 `LLMEndpointResponse` 的字段名与配套前端设计文档中定义的 `LLMEndpoint` TypeScript 接口一致。

---

## 7. Extension Points for Ollama / Anthropic

| Provider | `list_models` 策略 | `speed_test` 策略 |
|---|---|---|
| Ollama | `GET {base_url}/api/tags` → `models[].name` | `POST {base_url}/api/generate`，使用极小 prompt |
| Anthropic | `AnthropicProvider` 中硬编码列表 | `POST /v1/messages`，参数为 `max_tokens=1` |

添加 provider 的步骤：
1. 在该 provider 类中实现这两个方法。
2. 将 provider 名称加入前端 provider 下拉框。
3. 添加 API 测试。

无需修改 `EndpointManager` 或 routes。

---

## 8. Files to Create / Modify

### Create
- `src/thumbelina/llm/endpoint_manager.py`
- `src/thumbelina/llm/models.py`（可选 — 共享 `SpeedTestResult`、`LLMEndpoint` schema）
- `tests/test_llm/test_openai_provider.py`
- `tests/test_llm/test_endpoint_manager.py`
- `tests/test_api/test_config_endpoints.py`

### Modify
- `src/thumbelina/llm/base.py` — 添加抽象方法。
- `src/thumbelina/llm/openai.py` — 实现方法。
- `src/thumbelina/llm/factory.py` — 为 OpenAI 接受 `base_url`（已支持，需验证）。
- `src/thumbelina/api/routes/config.py` — 添加新 routes。
- `src/thumbelina/api/app.py` — 如需，在 app state 中注册 `EndpointManager`。

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
| `ModelListResponse.models` | `string[]` | model ID 列表 |
| `SpeedTestResponse.latency_ms` | `number` | TTFB，单位为毫秒 |
| `SpeedTestResponse.total_ms` | `number` | 请求总耗时 |

前端设计文档是 UI state 与组件命名的唯一事实来源；本文档是 API schema 的事实来源。

---

## 10. Open Questions

1. Endpoint 应该按用户作用域还是全局作用域？（当前配置系统是全局的；为保持一致，保持全局。）
2. `api_key` 是否应该在静态存储中加密？（首次迭代不在范围内；与现有 `config.llm.api_key` 一样以明文存储。）
3. 创建 endpoint 时是否应自动运行速度测试？（否；仅手动触发，以避免意外的 API 调用。）
