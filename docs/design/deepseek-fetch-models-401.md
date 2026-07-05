# DeepSeek API Fetch Models 401 错误修复设计

## 1. 背景

对应 TODO #4：deepseek 模型 fetch models 报错 401。

当用户在管理面板中配置 DeepSeek 作为 LLM Provider 时（选择 provider 为 `openai`，设置 `base_url=https://api.deepseek.com`），点击「Fetch models」按钮触发 `/api/v1/config/llm/models` 接口，最终调用 `OpenAIProvider.list_models()`，返回 HTTP 401 错误。

## 2. 问题根因分析

### 2.1 请求流程

```
Frontend (ModelSelector)
  → GET /api/v1/config/llm/models?provider=openai&base_url=https://api.deepseek.com&api_key=sk-xxx
    → config.py:list_models()
      → OpenAIProvider.list_models(base_url="https://api.deepseek.com", api_key="sk-xxx")
        → httpx GET {base_url}/models  → 401
```

### 2.2 根因拆解

**根因 1：DeepSeek API 不公开 `/v1/models` 端点**

DeepSeek 的 API 兼容 OpenAI 的 chat completion 接口（`/v1/chat/completions`），但**不提供 `/v1/models` 端点**用于列出可用模型。当请求发送到不存在的端点时，DeepSeek 返回 401 作为安全响应（而非 404）。

目前已知的 DeepSeek 模型列表（截至 2026-07）：
- `deepseek-chat`（通用对话）
- `deepseek-reasoner`（推理模型）

**根因 2：base_url 路径片段处理问题**

`OpenAIProvider.list_models()` 第 68 行的 URL 拼接逻辑：

```python
url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
# ...
response = await client.get(f"{url}/models", headers=headers, timeout=30.0)
```

当用户配置 `base_url = "https://api.deepseek.com"`（不含 `/v1` 路径）时，请求 URL 变为 `https://api.deepseek.com/models`，缺少 `/v1` 路径前缀，即使未来 DeepSeek 添加了 `/v1/models` 端点也无法命中。

当用户配置 `base_url = "https://api.deepseek.com/v1"` 时，请求 URL 变为 `https://api.deepseek.com/v1/models`，但 DeepSeek 仍然不支持此端点。

**根因 3：OpenAI 兼容性假设太强**

`OpenAIProvider` 假定所有 provider 都完整兼容 OpenAI API 的全部端点（包括 `/models`），但实际上第三方 OpenAI 兼容 API 通常只实现 chat completion 核心路径，不实现 `/models`。

### 2.3 涉及的相关设计文档

[LLM Provider 连通性测试设计](./llm-provider-connection-test.md) 中已经意识到了这个问题：

> Level 2 使用 `GET /v1/models` 检查 401 — 该端点对 DeepSeek 等 provider 不可用。

但尚未针对 `list_models()` 调用场景做具体修复。

## 3. DeepSeek API 调研结论

| 项目 | 结论 |
|------|------|
| **API Base URL** | `https://api.deepseek.com`（无需 `/v1` 前缀；LangChain 的 ChatOpenAI SDK 内部自动拼接 `/v1`） |
| **鉴权方式** | `Authorization: Bearer <api_key>` |
| **/v1/models 端点** | 不支持（返回 401 或 404） |
| **/v1/chat/completions** | 完全兼容 OpenAI 格式 |
| **可用模型** | `deepseek-chat`, `deepseek-reasoner`（静态列表，无 API 可查询） |
| **OpenAI SDK 兼容** | 使用 LangChain `ChatOpenAI` 配合 `base_url="https://api.deepseek.com"` 即可正常工作 |
| **特殊注意事项** | 部分模型需额外参数（如 `deepseek-reasoner` 不支持 `temperature` 参数）；流式兼容 |

## 4. 修复方案设计

### 4.1 方案总览

采用**多层修复策略**，由浅入深：

| 优先级 | 方案 | 目标 |
|--------|------|------|
| P0 | `list_models()` 优雅降级 | 401/404 不抛异常，返回空列表或 fallback 列表 |
| P1 | Provider 模型表支持 | 为已知 provider 维护静态模型推荐列表 |
| P2 | DeepSeekProvider 专用 provider | 完整的独立 provider 支持 |
| P3 | URL 路径规范化 | 自动补全 `/v1` 路径前缀 |

### 4.2 P0：list_models() 优雅降级（立即修复）

**目标**：`GET /models` 返回 401/404 时不抛异常，返回空列表 + warn 日志。

**改动点**：`src/thumbelina/llm/openai.py` — `list_models()` 方法

```python
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

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/models", headers=headers, timeout=30.0)
            response.raise_for_status()
            payload = response.json()
        return [m["id"] for m in payload.get("data", []) if "id" in m]
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403, 404):
            logger.warning(
                "Model listing not supported at %s (HTTP %d). "
                "Falling back to empty list.",
                url,
                e.response.status_code,
            )
            return []
        raise
    except Exception:
        logger.warning("Failed to fetch models from %s", url, exc_info=True)
        return []
```

**改动点**：`src/thumbelina/api/routes/config.py` — `list_models()` 路由

需要同时处理空模型列表的情况 — 不要把它视为错误：

```python
return ModelListResponse(provider=provider, base_url=base_url, models=models)
# 即使 models 为空也不抛异常
```

### 4.3 P1：Provider 模型表支持（规划阶段）

**目标**：为已知的第三方 provider 维护静态模型推荐列表，当 `list_models()` 返回空时，根据 base_url 自动匹配推荐列表。

**设计**：

在 `OpenAIProvider` 中新增类级模型表：

```python
# openai.py

PROVIDER_FALLBACK_MODELS: dict[str, list[str]] = {
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
}
```

在 `list_models()` 中 fallback 逻辑：

```python
models = []
if provider_name := self._detect_provider(url):
    models = PROVIDER_FALLBACK_MODELS.get(provider_name, [])
```

_provider 检测逻辑：基于 `base_url` 域名判断

```python
@staticmethod
def _detect_provider(base_url: str) -> str | None:
    """Detect known third-party provider from base_url."""
    import urllib.parse
    hostname = urllib.parse.urlparse(base_url).hostname or ""
    if "deepseek" in hostname:
        return "deepseek"
    if "groq" in hostname:
        return "groq"
    return None
```

> **注意**：该方案在 `OpenAIProvider` 中维护了一个外部 provider 的模型列表，存在以下问题：
> - 模型列表会过时（需要随 DeepSeek 更新而更新）
> - 额外的维护成本
> - 所以作为可选优化，P0 修复已足够解决 401 报错

### 4.4 P2：新增 DeepSeekProvider（未来规划）

**目标**：创建独立的 `DeepSeekProvider`，继承 `OpenAIProvider`，覆盖 `list_models()` 和 `speed_test()`。

**设计**：

```python
# src/thumbelina/llm/deepseek.py

from thumbelina.llm.openai import OpenAIProvider

DEEPSEEK_MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
]

class DeepSeekProvider(OpenAIProvider):
    """LLM provider for DeepSeek API.

    DeepSeek uses OpenAI-compatible API for chat completions
    but does not expose a /v1/models endpoint for model listing.

    Parameters
    ----------
    api_key:
        DeepSeek API key.
    model:
        Model identifier (default ``"deepseek-chat"``).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-chat",
        **kwargs: Any,
    ) -> None:
        # Force base_url to DeepSeek default if not specified
        kwargs.setdefault("base_url", "https://api.deepseek.com")
        super().__init__(api_key=api_key, model=model, **kwargs)

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        # DeepSeek does not expose /v1/models endpoint
        # Return known model list instead
        logger.info("DeepSeek: using static model list (no /v1/models endpoint)")
        return list(DEEPSEEK_MODELS)
```

**注册**：在 `factory.py` 中注册：

```python
_registry = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
    "deepseek": DeepSeekProvider,    # ← 新增
}
```

**前端变更**：在 `frontend/src/api/llmConfig.ts` 中补充 provider 类型：

```typescript
export interface LLMEndpoint {
  provider: 'openai' | 'ollama' | 'anthropic' | 'deepseek'  // ← 新增 deepseek
  // ...
}
```

在 `ModelSelector.tsx` 中支持 deepseek provider：

```tsx
const supported = provider === 'openai' || provider === 'deepseek'
```

### 4.5 P3：URL 路径规范化（辅助修复）

**目标**：当 `base_url` 不包含 `/v1` 路径片段时，自动补全。

**改动点**：`OpenAIProvider.list_models()` 中增加路径规范化：

```python
url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")

# 规范化：确保 URL 包含 /v1 路径（OpenAI 兼容 API 的惯例）
parsed = urllib.parse.urlparse(url)
if not parsed.path or parsed.path == "/":
    # 如 https://api.deepseek.com → https://api.deepseek.com/v1
    url = f"{url}/v1"
```

> **注意**：此方案有风险 — 不是所有 OpenAI 兼容 API 都使用 `/v1` 路径（如 Ollama 使用 `/api`）。所以此方案**不做**为默认行为，仅在明确确认目标 provider 支持 `/v1` 路径时使用。

### 4.6 推荐的实现顺序

```
优先 → P0：list_models() 优雅降级（最小改动，解决核心问题）
   → P1：Provider 模型表（用户体验优化）
   → 前端适配：错误提示友好化
可选 → P2：DeepSeekProvider（完整 provider 隔离）
可选 → P3：URL 路径规范化（辅助修复）
```

## 5. 配置示例

当用户使用 DeepSeek 时的正确配置方式（当前系统）：

```yaml
# thumbelina.yaml
llm:
  provider: openai
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: ${DEEPSEEK_API_KEY}
```

如未来实现了 `DeepSeekProvider`：

```yaml
llm:
  provider: deepseek
  model: deepseek-chat
  api_key: ${DEEPSEEK_API_KEY}
  # base_url 可选，默认为 https://api.deepseek.com
```

通过 Web UI 配置时选择 `provider=openai`，`base_url=https://api.deepseek.com`。

## 6. 前端交互建议

当 list_models 返回空列表时，前端应提供有好的降级体验：

1. **在 ModelSelector 中使用兜底输入**：当前已支持 input[type=text] + datalist 组合，用户可以直接输入模型名称
2. **错误提示改进**：当 Fetch models 返回 502（后端代理的 401）时，显示以下提示而非原始错误：
   - 非 DeepSeek 通用提示：`"该服务暂不支持自动获取模型列表，请手动输入模型名称"`
   - DeepSeek 特定提示：`"DeepSeek 不提供模型列表 API，推荐使用：deepseek-chat, deepseek-reasoner。请手动输入模型名称。"`
3. **推荐展示**：对已知 provider，在下拉列表(datalist)中直接预设推荐的模型列表，无需网络请求

## 7. 需要修改的文件清单

### P0 必需修改

| # | 文件 | 修改内容 | 影响范围 |
|---|------|----------|----------|
| 1 | `src/thumbelina/llm/openai.py` | `list_models()` 捕获 HTTP 401/403/404，返回空列表而非抛异常 | 所有通过 OpenAIProvider 获取模型列表的场景 |
| 2 | `src/thumbelina/api/routes/config.py` | `list_models()` 路由：允许 models 为空列表，不抛 502 | 前端调用 `/config/llm/models` 接口 |

### P1 可选优化

| # | 文件 | 修改内容 | 影响范围 |
|---|------|----------|----------|
| 3 | `src/thumbelina/llm/openai.py` | 新增 `PROVIDER_FALLBACK_MODELS` 字典；新增 `_detect_provider()` 静态方法；在 `list_models()` 中添加 fallback 逻辑 | DeepSeek/Groq 等已知 provider |
| 4 | `frontend/src/components/Settings/ModelSelector.tsx` | 根据 provider 类型显示友好的降级提示 | 前端 fetch 失败时的用户体验 |

### P2 未来规划

| # | 文件 | 修改内容 | 影响范围 |
|---|------|----------|----------|
| 5 | `src/thumbelina/llm/deepseek.py` | 新建文件：`DeepSeekProvider` 类 | DeepSeek 用户 |
| 6 | `src/thumbelina/llm/factory.py` | 注册 `DeepSeekProvider` | provider 创建工厂 |
| 7 | `src/thumbelina/llm/__init__.py` | 导出 `DeepSeekProvider`（如需） | 模块接口 |
| 8 | `frontend/src/api/llmConfig.ts` | 新增 `'deepseek'` provider 类型 | 前端类型定义 |
| 9 | `frontend/src/components/Settings/ModelSelector.tsx` | `supported` 检查支持 `deepseek` | 前端功能开关 |

### 测试文件

| # | 文件 | 修改内容 |
|---|------|----------|
| 10 | `tests/test_llm/test_openai_provider.py` | 新增 `test_list_models_401_fallback`、`test_list_models_404_fallback`、`test_list_models_deepseek_fallback` 测试用例 |
| 11 | `tests/test_api/test_config_endpoints.py` | 新增 `test_list_models_deepseek_returns_empty` 测试用例（mock 返回 401） |

## 8. 测试建议

### 8.1 单元测试

**场景 1：真实 OpenAI 端点**
- mock `httpx.AsyncClient.get` 返回 200 + 模型列表
- 验证模型列表被正确提取

**场景 2：DeepSeek 返回 401**
- mock `httpx.AsyncClient.get` 抛出 `httpx.HTTPStatusError`（401）
- 验证 `list_models()` 返回空列表 `[]`，而非抛异常
- 验证 logger.warning 被调用

**场景 3：DeepSeek 返回 404**
- mock `httpx.AsyncClient.get` 抛出 404
- 验证同上

**场景 4：其他 HTTP 错误（500）**
- mock `httpx.AsyncClient.get` 抛出 500
- 验证异常被重新抛出（不捕获非 401/403/404 错误）

**场景 5：空 api_key**
- 验证当 api_key 为空时，不设置 Authorization header
- 验证请求仍然发送

### 8.2 集成测试

**场景 6：API 路由 — DeepSeek 配置**
- 使用 `TestClient` 调用 `GET /api/v1/config/llm/models?provider=openai&base_url=https://api.deepseek.com&api_key=sk-test`
- mock `OpenAIProvider.list_models()` 返回 `[]`
- 验证响应为 200，`models` 为空列表

### 8.3 手动验证步骤

1. 启动后端服务
2. 通过 API 调用：`GET /api/v1/config/llm/models?provider=openai&base_url=https://api.deepseek.com&api_key=<实际key>`
3. 验证返回 `{"provider":"openai","base_url":"https://api.deepseek.com","models":[]}`
4. 验证后端日志中出现 `WARNING — Model listing not supported at ... (HTTP 401)` 警告
5. 通过 Web UI 配置 DeepSeek endpoint，点击「Fetch models」，验证不报错
6. 验证手动输入 `deepseek-chat` 仍可正常保存
7. 验证聊天的 chat completion 功能不受影响

## 9. 风险与注意事项

1. **向后兼容**：P0 方案完全向后兼容 — 对 OpenAI 等正常支持 `/models` 的 provider 无影响；对 DeepSeek 等不支持 `/models` 的 provider，从「报错」变为「返回空列表」
2. **安全考虑**：返回空列表不暴露任何凭据信息
3. **鉴权绕过风险**：在空 api_key 情况下，list_models 不设 Authorization header 可能被拒绝，但这是预期行为
4. **前端为空列表的兜底**：确保 ModelSelector 的 datalist 为空时不阻塞用户 — 目前 input[type=text] 已允许用户自由输入，这是正确的设计
5. **已知模型的更新**：P1 方案中的 `PROVIDER_FALLBACK_MODELS` 需要随 provider 发布新模型而更新，建议添加备注标明最后更新日期
