# LLM Provider 连通性测试功能设计文档

## 1. 背景与目标

TODO 条目 #3：「LLM PROVIDER支持测试base_url是否连接」。

### 目标

允许用户在配置 LLM endpoint 时，一键测试目标地址是否可用，具体包含：

- **网络可达**：DNS 解析 + TCP 连接成功
- **鉴权有效**：API key 被服务端接受（非 401/403）
- **服务可用**：服务端正常响应（非 500/503）

### 非目标

- 完整的 benchmark / 延迟基准测试（已有 `SpeedTestResult`，保留但与此功能分离）
- 模型能力验证（如发送复杂 prompt 检查回答质量）

---

## 2. 当前状态分析

### 后端已有能力

| 能力 | 文件 | 状态 |
|------|------|------|
| `list_models()` (ABC) | `llm/base.py:99` | 已定义，OpenAI 实现，Anthropic/Ollama 抛 `NotImplementedError` |
| `speed_test()` (ABC) | `llm/base.py:109` | 已定义，OpenAI 实现（完整 chat completion），Anthropic/Ollama 抛 `NotImplementedError` |
| `SpeedTestResult` dataclass | `llm/base.py:15` | 包含 `reachable` / `latency_ms` / `total_ms` / `error` |
| `EndpointManager.run_speed_test()` | `llm/endpoint_manager.py:177` | 通过完整 provider 实例调用 `speed_test()`，需要指定 model |
| `GET /config/llm/models` | `api/routes/config.py:483` | 对指定 provider+base_url+api_key 调用 `list_models()` |
| `POST .../speed-test` | `api/routes/config.py:458` | 对已保存 endpoint 执行 speed test |

### 前端已有交互

| 组件 | 能力 |
|------|------|
| `EndpointList` | 每行有「Speed Test」按钮，调用 `runSpeedTest(id, model)` |
| `ModelSelector` | 「Fetch models」按钮，调用 `fetchModels({provider, base_url, api_key})` |
| `SpeedTestResult` | 展示加载态、成功（延迟）、失败（错误信息） |
| `SettingsPanel` | 顶部 LLM 配置区域有 manual 的 provider/model/base_url/api_key 输入，无连通性测试按钮 |

### 关键缺口

1. **Anthropic / Ollama 的 `list_models()` 和 `speed_test()` 均未实现**，导致这些 provider 的 endpoint 无法测试连通性
2. **现有 speed test 需要指定 model 名称**，而用户在首次配置时可能不知道有哪些 model
3. **当前测试太重**：`speed_test()` 实际发了一条 chat completion 请求（含 `max_tokens: 1` 的 `"hi"`），不适合仅验证连通性
4. **SettingsPanel 顶部的手动配置区域** 没有单独的连通性测试按钮（只有通过 EndpointManager 的已保存 endpoint 才有 Speed Test）

---

## 3. 设计

### 3.1 核心概念：三层连通性测试

```
Level 1: 网络可达性 (ping)
  目的: 确认 base_url 的 host 可解析、端口可连接
  方法: DNS 解析 + TCP 握手
  耗时: < 1s

Level 2: 鉴权有效性 (auth)
  目的: 确认 API key 被服务端接受
  方法: 对 OpenAI 兼容 endpoint 发 GET /v1/models（或 HEAD），检查 401/403
  耗时: < 3s

Level 3: 服务可用性 (health)
  目的: 确认服务端能正常响应请求
  方法: 发一个极简请求（如 GET /v1/models 或最小 chat completion）
  耗时: < 10s
```

### 3.2 后端 API 设计

#### 新增接口：对**任意参数**的连通性测试（不对应已保存 endpoint）

```http
POST /api/v1/config/llm/test-connection
```

请求体：

```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4o"           // 可选，部分 provider 需要 model 才能验证
}
```

响应体：

```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "reachable": true,
  "network_reachable": true,
  "auth_valid": true,
  "service_available": true,
  "latency_ms": 234,
  "error": null,
  "details": {
    "network": { "ok": true, "latency_ms": 45 },
    "auth": { "ok": true, "latency_ms": 89 },
    "service": { "ok": true, "latency_ms": 234 }
  }
}
```

错误响应：

```json
// 网络不可达
{
  "provider": "openai",
  "base_url": "https://invalid.example.com",
  "reachable": false,
  "network_reachable": false,
  "auth_valid": false,
  "service_available": false,
  "latency_ms": null,
  "error": "Connection refused",
  "details": {
    "network": { "ok": false, "latency_ms": null, "error": "Connection refused" },
    "auth": { "ok": false, "latency_ms": null, "error": "Skipped due to network failure" },
    "service": { "ok": false, "latency_ms": null, "error": "Skipped due to network failure" }
  }
}

// 鉴权失败
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "reachable": false,
  "network_reachable": true,
  "auth_valid": false,
  "service_available": false,
  "latency_ms": 120,
  "error": "401 Unauthorized - Invalid API key",
  "details": {
    "network": { "ok": true, "latency_ms": 45 },
    "auth": { "ok": false, "latency_ms": 120, "error": "HTTP 401" },
    "service": { "ok": false, "latency_ms": null, "error": "Skipped due to auth failure" }
  }
}
```

#### 新增接口：对**已保存 endpoint** 的连通性测试（轻量版，无需 model 参数）

```http
POST /api/v1/config/llm/endpoints/{endpoint_id}/test-connection
```

响应体同上，但 endpoint_id 从路径参数获取，provider/base_url/api_key 从数据库读取。

响应中额外包含 `endpoint_id` 字段。

#### 响应模型定义

```python
class ConnectionTestStep(BaseModel):
    ok: bool
    latency_ms: int | None = None
    error: str | None = None

class ConnectionTestDetails(BaseModel):
    network: ConnectionTestStep
    auth: ConnectionTestStep
    service: ConnectionTestStep

class ConnectionTestResponse(BaseModel):
    provider: str
    base_url: str
    endpoint_id: str | None = None
    reachable: bool
    network_reachable: bool
    auth_valid: bool
    service_available: bool
    latency_ms: int | None = None
    error: str | None = None
    details: ConnectionTestDetails | None = None
```

### 3.3 Provider 连通性实现策略

在每个 provider 中新增 `async def test_connection(base_url, api_key) -> ConnectionTestResult` 方法。

#### OpenAI 兼容（含 DeepSeek、Groq 等）

```python
async def test_connection(
    self,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ConnectionTestResult:
    url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
    key = api_key or self._api_key

    steps = ConnectionTestDetails()
    start = time.perf_counter()

    # Level 1: 网络可达
    try:
        host = urllib.parse.urlparse(url).hostname
        port = urllib.parse.urlparse(url).port or 443
        t0 = time.perf_counter()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        steps.network = ConnectionTestStep(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
    except Exception as e:
        steps.network = ConnectionTestStep(ok=False, error=str(e))
        return ConnectionTestResult(
            reachable=False, network_reachable=False,
            error=str(e), details=steps,
        )

    # Level 2: 鉴权
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/models", headers=headers, timeout=10.0)
        auth_latency = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 401 or resp.status_code == 403:
            steps.auth = ConnectionTestStep(ok=False, latency_ms=auth_latency, error=f"HTTP {resp.status_code}")
            return ConnectionTestResult(
                reachable=False, network_reachable=True, auth_valid=False,
                error=f"Authentication failed: HTTP {resp.status_code}",
                details=steps,
            )
        resp.raise_for_status()
        steps.auth = ConnectionTestStep(ok=True, latency_ms=auth_latency)
    except httpx.HTTPStatusError as e:
        steps.auth = ConnectionTestStep(ok=False, error=str(e))
        return ConnectionTestResult(
            reachable=False, network_reachable=True, auth_valid=False,
            error=str(e), details=steps,
        )
    except Exception as e:
        steps.auth = ConnectionTestStep(ok=False, error=str(e))
        return ConnectionTestResult(
            reachable=False, network_reachable=True, auth_valid=False,
            error=str(e), details=steps,
        )

    # Level 3: 服务可用（发最小 chat completion）
    try:
        t0 = time.perf_counter()
        payload = {
            "model": model or "gpt-4o",  # 需要 model 参数
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/chat/completions",
                headers=headers | {"Content-Type": "application/json"},
                json=payload,
                timeout=15.0,
            )
            resp.raise_for_status()
        total_latency = int((time.perf_counter() - t0) * 1000)
        steps.service = ConnectionTestStep(ok=True, latency_ms=total_latency)
    except Exception as e:
        steps.service = ConnectionTestStep(ok=False, error=str(e))
        return ConnectionTestResult(
            reachable=False, network_reachable=True, auth_valid=True,
            error=str(e), details=steps,
        )

    return ConnectionTestResult(
        reachable=True, network_reachable=True, auth_valid=True,
        service_available=True, latency_ms=total_latency,
        details=steps,
    )
```

> **注意**：在 API 路由层，会尝试先使用 `list_models()`（Level 2），如果 provider 不支持（抛 `NotImplementedError`），降级为仅进行网络可达性测试 + 基础 auth header 格式验证。

#### Anthropic

```python
async def test_connection(
    self,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ConnectionTestResult:
    # Anthropic 没有公开的 /v1/models 端点
    # Level 1: 网络可达 (api.anthropic.com:443)
    # Level 2: 用 x-api-key header 发 GET /v1/messages?limit=1 检查 401
    # Level 3: 发最小 messages 请求
    #
    # 参考: https://docs.anthropic.com/en/api/messages
```

#### Ollama

```python
async def test_connection(
    self,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ConnectionTestResult:
    # Ollama 不需要 api_key，也没有鉴权
    # Level 1: 网络可达 (localhost:11434)
    # Level 2: 跳过（无鉴权）
    # Level 3: GET /api/tags 列出模型 或 POST /api/generate 发最小请求
    #
    # 参考: https://github.com/ollama/ollama/blob/main/docs/api.md
```

### 3.4 基类新增方法

在 `LLMProvider` ABC 中新增：

```python
@dataclass
class ConnectionTestStep:
    ok: bool
    latency_ms: int | None = None
    error: str | None = None

@dataclass
class ConnectionTestDetails:
    network: ConnectionTestStep
    auth: ConnectionTestStep
    service: ConnectionTestStep

@dataclass
class ConnectionTestResult:
    reachable: bool
    network_reachable: bool = False
    auth_valid: bool = False
    service_available: bool = False
    latency_ms: int | None = None
    error: str | None = None
    details: ConnectionTestDetails | None = None
    tested_at: datetime | None = None

class LLMProvider(ABC):
    # ... 现有方法 ...

    @abstractmethod
    async def test_connection(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> ConnectionTestResult:
        """Test connectivity to the provider endpoint.

        Performs a three-level check:
        1. Network reachability (TCP handshake)
        2. Auth validity (API key acceptance)
        3. Service availability (minimal request round-trip)

        Returns a detailed result with per-step timing and errors.
        """
        ...
```

### 3.5 现有接口的变更

#### `EndpointManager` 新增方法

```python
class EndpointManager:
    # ... 现有方法 ...

    async def test_connection(
        self,
        endpoint_id: str,
        model: str | None = None,
    ) -> ConnectionTestResult | None:
        """Test connectivity for a saved endpoint without a full speed test."""
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

        # 更新 endpoint 的可达性状态（轻量，不覆盖 speed_test 的延迟数据）
        endpoint.is_reachable = result.reachable
        endpoint.updated_at = datetime.now(UTC)
        await self._persist(endpoint)
        return result
```

#### `speed_test()` 保持不变

已有的 `speed_test()` 方法保留，作为 full-benchmark 使用。
新增的 `test_connection()` 专注于连通性验证，两套逻辑独立。

### 3.6 路由设计

现有路由：

| 路径 | 方法 | 用途 |
|------|------|------|
| `/config/llm/endpoints/{id}/speed-test` | POST | 全量 speed test（需 model） |

新增路由：

| 路径 | 方法 | 用途 |
|------|------|------|
| `/config/llm/test-connection` | POST | 对任意参数做连通性测试 |
| `/config/llm/endpoints/{id}/test-connection` | POST | 对已保存 endpoint 做连通性测试 |

`test-connection` 优于已存在的 `speed-test` 之处：

1. 不需要预先知道 model 名称
2. 三层逐步诊断，出错时能精确指出哪一层失败
3. 更快（Level 1 在网络不通时秒级返回）

### 3.7 安全考虑

1. **API key 不在响应中返回**：任何时候响应中都不包含 `api_key` 字段
2. **错误信息 sanitize**：网络错误信息应 sanitize header 中的敏感内容（如 URL 中的 token）
3. **超时控制**：每层都有独立超时，Level 1=5s, Level 2=10s, Level 3=15s
4. **避免 SSRF**：Level 1 只验证 TCP 连接，不发送 HTTP 请求到任意 host；URL 应通过 `urllib.parse` 验证为合法 http/https

### 3.8 前端交互设计

#### SettingsPanel 顶部手动配置区

在 LLM Configuration 区域的「Model」输入框下方新增两行：

```
[Fetch models] [Test Connection]     ← 新增 Test Connection 按钮
```

点击「Test Connection」：

1. 按钮变 loading 态，文本变为「Testing…」
2. 调用 `POST /api/v1/config/llm/test-connection`，传当前 form 中的 provider/base_url/api_key
3. 根据结果展示反馈：

**成功：**
```
✓ Connected — 234 ms
   ├─ Network: ✓ 45 ms
   ├─ Auth:    ✓ 89 ms
   └─ Service: ✓ 234 ms
```

**网络不可达：**
```
✗ Connection failed — Connection refused
   ├─ Network: ✗ Connection refused
   └─ Skipped further checks
```

**鉴权失败：**
```
✗ Authentication failed — HTTP 401 Unauthorized
   ├─ Network: ✓ 45 ms
   ├─ Auth:    ✗ HTTP 401
   └─ Skipped further checks
```

#### EndpointList 中每行的 Test Connection

在现有「Speed Test」按钮旁边新增「Test Connection」按钮：

```
[Test Connection] [Speed Test] [Edit] [Delete] [Set Default]
```

- 「Test Connection」使用 `POST .../endpoints/{id}/test-connection`（轻量，不重）
- 「Speed Test」使用现有 `POST .../endpoints/{id}/speed-test?model=...`（重量，测量延迟）

#### 前端 API 层新增函数

```typescript
// frontend/src/api/llmConfig.ts

export interface ConnectionTestStep {
  ok: boolean
  latency_ms?: number
  error?: string
}

export interface ConnectionTestDetails {
  network: ConnectionTestStep
  auth: ConnectionTestStep
  service: ConnectionTestStep
}

export interface ConnectionTestResult {
  provider: string
  base_url: string
  endpoint_id?: string
  reachable: boolean
  network_reachable: boolean
  auth_valid: boolean
  service_available: boolean
  latency_ms?: number
  error?: string
  details?: ConnectionTestDetails
}

// 测试任意参数
export async function testConnection(params: {
  provider: string
  base_url: string
  api_key?: string
  model?: string
}): Promise<ConnectionTestResult> {
  return request<ConnectionTestResult>('/config/llm/test-connection', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

// 测试已保存 endpoint
export async function testEndpointConnection(
  endpointId: string,
  model?: string,
): Promise<ConnectionTestResult> {
  const query = model ? `?model=${encodeURIComponent(model)}` : ''
  return request<ConnectionTestResult>(`/config/llm/endpoints/${endpointId}/test-connection${query}`)
}
```

#### 新增前端组件：`ConnectionTestButton`

```tsx
interface ConnectionTestButtonProps {
  provider: string
  base_url: string
  api_key: string
  onResult: (result: ConnectionTestResult) => void
}
```

- 小型按钮组件，可复用
- 调用 `testConnection()` API
- 管理自身 loading 状态
- 通过 props 暴露结果给父组件展示

#### 新增前端组件：`ConnectionTestResultDisplay`

```tsx
interface ConnectionTestResultDisplayProps {
  result: ConnectionTestResult | null
  loading: boolean
}
```

- 展示测试结果的详细信息（分层详情）
- 成功：绿色 ✓ 加延迟
- 失败：红色 ✗ 加错误详情

---

## 4. 修改文件清单

### 后端

| 文件 | 修改内容 |
|------|----------|
| `src/thumbelina/llm/base.py` | 新增 `ConnectionTestStep`, `ConnectionTestDetails`, `ConnectionTestResult` dataclass；新增 `test_connection()` 抽象方法 |
| `src/thumbelina/llm/openai.py` | 实现 `test_connection()` 方法（三层逐步检测） |
| `src/thumbelina/llm/anthropic.py` | 实现 `test_connection()` 方法（Anthropic API 兼容） |
| `src/thumbelina/llm/ollama.py` | 实现 `test_connection()` 方法（Ollama API 兼容） |
| `src/thumbelina/llm/endpoint_manager.py` | 新增 `test_connection()` 方法 |
| `src/thumbelina/api/routes/config.py` | 新增两个路由端点；新增 `ConnectionTestRequest` / `ConnectionTestResponse` models |

### 前端

| 文件 | 修改内容 |
|------|----------|
| `frontend/src/api/llmConfig.ts` | 新增 `ConnectionTest*` 类型接口、`testConnection()` 和 `testEndpointConnection()` 函数 |
| `frontend/src/components/Settings/ConnectionTestButton.tsx` | 新建：可复用的测试按钮组件 |
| `frontend/src/components/Settings/ConnectionTestResultDisplay.tsx` | 新建：测试结果展示组件 |
| `frontend/src/components/Settings/SettingsPanel.tsx` | 在手动配置区添加 Test Connection 按钮 |
| `frontend/src/components/Settings/EndpointList.tsx` | 在每行添加「Test Connection」按钮 |
| `frontend/src/components/Settings/EndpointManager.tsx` | 添加 `testConnectingId` 状态 |
| `frontend/src/components/Settings/SpeedTestResult.tsx` | 不变（保留已有组件） |

### 测试

| 文件 | 修改内容 |
|------|----------|
| `tests/test_llm/test_openai_provider.py` | 新增 `test_connection()` 的单元测试 |
| `tests/test_llm/test_anthropic_provider.py` | 新增 `test_connection()` 的单元测试 |
| `tests/test_llm/test_ollama_provider.py` | 新增 `test_connection()` 的单元测试 |
| `tests/test_api/test_config_endpoints.py` | 新增连通性测试 endpoint 的集成测试 |

---

## 5. 实现顺序

1. **定义数据模型**：在 `base.py` 中添加 `ConnectionTestStep`, `ConnectionTestDetails`, `ConnectionTestResult` 和 `test_connection()` 抽象方法
2. **实现 OpenAI provider**：在 `openai.py` 中实现三层检测逻辑（可直接复用现有的 httpx 客户端）
3. **实现 Anthropic provider**：适配 Anthropic API 的鉴权方式（`x-api-key` header）
4. **实现 Ollama provider**：适配 Ollama API（无鉴权，GET /api/tags）
5. **后端路由**：在 `config.py` 中添加两个新路由端点
6. **EndpointManager**：添加 `test_connection()` 方法
7. **前端 API 层**：新增 types 和 functions
8. **前端组件**：新建 `ConnectionTestButton` 和 `ConnectionTestResultDisplay`
9. **前端集成**：接入 SettingsPanel 和 EndpointList
10. **测试**：为各 provider 和后端路由编写测试

---

## 6. 关键接口定义（API 契约）

### `POST /api/v1/config/llm/test-connection`

**Request:**
```json
{
  "provider": "openai | anthropic | ollama",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4o"
}
```

**Response (200):**
```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "reachable": true,
  "network_reachable": true,
  "auth_valid": true,
  "service_available": true,
  "latency_ms": 234,
  "error": null,
  "details": {
    "network": { "ok": true, "latency_ms": 45 },
    "auth": { "ok": true, "latency_ms": 89 },
    "service": { "ok": true, "latency_ms": 234, "error": null }
  }
}
```

**Response (422) — provider 不存在:**
```json
{
  "detail": "Unknown provider: 'unknown'. Available providers: anthropic, ollama, openai"
}
```

### `POST /api/v1/config/llm/endpoints/{endpoint_id}/test-connection`

**Query params:** `?model=gpt-4o`（可选）

**Response (200):** 同上，额外包含 `"endpoint_id": "xxx"`

**Response (404):**
```json
{
  "detail": "Endpoint not found"
}
```
