# LLM 端点管理 —— 前端设计

> **日期：** 2026-07-02  
> **范围：** 用于管理多个 LLM 基础 URL、拉取模型列表并执行测速的 React UI。  
> **策略：** 先支持 OpenAI / OpenAI 兼容提供商；组件设计需便于后续 Ollama 和 Anthropic 复用同一套 UI。

---

## 1. 目标

扩展设置页面，使用户能够：

1. 为每个提供商保存多个 LLM 端点（base URL）。
2. 在输入 API 密钥后，从端点拉取可用模型名称。
3. 对任意已保存端点执行一键延迟 / 可用性测试。
4. 标记默认端点，以便主 LLM 表单自动填充 `base_url`。

首次实现面向 **OpenAI 兼容端点**。Ollama 和 Anthropic 将在后端提供商实现后复用相同组件。

---

## 2. 架构概览

```
┌────────────────────────────────────────────────────────────────┐
│  SettingsPanel.tsx                                             │
│  ├── LLMConfigCard (existing provider/model/base_url/api_key)  │
│  ├── EndpointManager.tsx  ← new                                │
│  │   ├── EndpointList.tsx                                      │
│  │   ├── EndpointForm.tsx                                      │
│  │   └── SpeedTestResult.tsx                                   │
│  └── ModelSelector.tsx  ← new (integrated into LLMConfigCard)  │
└────────────────────┬───────────────────────────────────────────┘
                     │ fetch()
┌────────────────────▼───────────────────────────────────────────┐
│  api/llmConfig.ts                                              │
│  - fetchEndpoints()                                            │
│  - createEndpoint()                                            │
│  - updateEndpoint()                                            │
│  - deleteEndpoint()                                            │
│  - runSpeedTest()                                              │
│  - fetchModels()                                               │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型

### 3.1 `LLMEndpoint`

与后端 `LLMEndpointResponse` 模式一一对应。

```typescript
interface LLMEndpoint {
  id: string
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key_set: boolean
  is_default: boolean
  last_latency_ms?: number
  last_total_ms?: number
  is_reachable?: boolean
  last_tested_at?: string // ISO 8601
}
```

### 3.2 `SpeedTestResult`

与后端 `SpeedTestResponse` 模式对应。

```typescript
interface SpeedTestResult {
  endpoint_id: string
  reachable: boolean
  latency_ms?: number
  total_ms?: number
  error?: string
}
```

### 3.3 `ModelList`

```typescript
interface ModelList {
  provider: string
  base_url: string
  models: string[]
}
```

### 3.4 表单状态

```typescript
interface EndpointFormData {
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key: string
  is_default: boolean
}
```

---

## 4. 组件与职责

### 4.1 `api/llmConfig.ts`

一个轻量的 fetch 封装层。所有与设置相关的 LLM 配置请求集中在此，便于测试和复用。

```typescript
export async function fetchEndpoints(provider?: string): Promise<LLMEndpoint[]>
export async function createEndpoint(data: EndpointFormData): Promise<LLMEndpoint>
export async function updateEndpoint(id: string, data: Partial<EndpointFormData>): Promise<LLMEndpoint>
export async function deleteEndpoint(id: string): Promise<void>
export async function runSpeedTest(id: string): Promise<SpeedTestResult>
export async function fetchModels(params: { provider: string; base_url: string; api_key?: string }): Promise<ModelList>
```

规则：
- 复用现有的 `fetch` 基础路径（`/api/v1`）。
- `api_key` 仅在写入时发送；保存后不再渲染。
- 将 HTTP 错误转换为 `Error`，并使用后端返回的 `detail` 消息。

### 4.2 `EndpointManager.tsx`

容器组件，负责维护端点列表状态。

职责：
- 挂载时加载端点列表。
- 控制创建 / 编辑表单的打开与关闭。
- 处理创建、更新、删除、测速和设为默认等操作。
- 通过 `SettingsPanel` 中现有的 `message` / `isError` 横幅展示全局反馈（以 props 传入）。

Props：

```typescript
interface EndpointManagerProps {
  onMessage: (message: string, isError: boolean) => void
}
```

### 4.3 `EndpointList.tsx`

纯展示组件。

职责：
- 以卡片或表格行形式渲染端点。
- 显示提供商标识、名称、base_url、可达性状态、最近延迟。
- 触发事件：编辑、删除、测速、设为默认。

显示列 / 字段：
- 名称（加粗）
- 提供商标识
- Base URL（截断显示，使用 `title` 提示完整内容）
- 默认星标 / 标识
- 最近测试：相对时间或“从未”
- 延迟：`123 ms` 或 `—`
- 可达性：绿点 / 红点 / 灰点
- 操作：测速、编辑、删除、设为默认

### 4.4 `EndpointForm.tsx`

用于创建 / 编辑端点的弹窗或内联表单。

字段：
- 提供商选择（首次迭代仅 `openai`；未来提供商选项可注释或禁用）
- 名称输入框
- Base URL 输入框（占位符：`https://api.openai.com/v1`）
- API 密钥输入框（密码类型；编辑时显示可选提示“留空以保留当前密钥”）
- “设为默认”复选框

校验规则：
- `base_url` 必须是有效 URL。
- `name` 不能为空。
- `provider` 不能为空。

提交时调用 `createEndpoint` 或 `updateEndpoint`，然后关闭表单并刷新列表。

### 4.5 `SpeedTestResult.tsx`

小型内联组件，用于渲染单次测速结果。

状态：
- 加载中：转圈图标 + “测试中…”
- 成功：绿色对勾 + `123 ms`（延迟）+ `245 ms`（总耗时）
- 失败：红色叉号 + 截断后的错误信息

### 4.6 `ModelSelector.tsx`

集成到现有 `LLMConfigCard` 区域，位于模型输入框旁边。

职责：
- 接收当前 `provider`、`base_url` 和 `api_key`。
- 提供“拉取模型”按钮。
- 点击后调用 `fetchModels` 并以下拉列表 / 数据列表形式展示返回的模型 ID。
- 用户选择模型后，更新父级 `model` 状态。

UI 方案对比：
- **A.** 拉取模型后将模型输入框替换为选择框。
- **B.** 保持模型输入框可自由输入，同时展示从已拉取模型填充的数据列表。
- **决定：B。** 既保留灵活性（用户仍可输入列表中不存在的模型名），又提供便利。

### 4.7 `LLMConfigCard` 修改

现有 `SettingsPanel.tsx` 中的 LLM 区域将抽离为 `LLMConfigCard`（若规模较小也可保持内联）。

变更：
- 在模型输入框下方添加 `<ModelSelector />`。
- 当 `base_url` 为空时，可选展示当前默认端点的 `base_url` 作为提示。
- 不破坏 `PUT /config/llm` 的请求载荷。

---

## 5. 数据流

### 5.1 加载端点

1. `EndpointManager` 挂载。
2. 调用 `fetchEndpoints()`。
3. 将结果存入 `endpoints` 状态。
4. `EndpointList` 渲染。

### 5.2 创建端点

1. 用户点击“添加端点”。
2. `EndpointForm` 以空状态打开。
3. 用户填写表单并提交。
4. `EndpointManager` 调用 `createEndpoint(data)`。
5. 成功后刷新列表并显示成功消息。
6. 失败时显示错误消息。

### 5.3 测速

1. 用户点击端点行上的测速图标。
2. `EndpointManager` 设置 `testingId` 状态。
3. 调用 `runSpeedTest(id)`。
4. 使用返回的 `latency_ms`、`total_ms`、`is_reachable`、`last_tested_at` 更新本地端点记录。
5. `EndpointList` 以新状态重新渲染。

### 5.4 拉取模型列表

1. 用户在主 LLM 表单中输入 base_url 和 api_key。
2. 点击模型输入框旁的“拉取模型”。
3. `ModelSelector` 调用 `fetchModels({ provider, base_url, api_key })`。
4. 成功后填充 `<datalist id="model-options">`。
5. 用户可从列表中选择，或继续自由输入。

---

## 6. 错误处理

| 场景 | 用户体验 |
|---|---|
| 网络错误 | 红色横幅：“网络错误，请检查连接。” |
| 端点不可达 | 红色横幅：“无法连接到端点：<detail>” |
| 提供商暂不支持 | 禁用“拉取模型”按钮，提示“该提供商暂不支持模型列表。” |
| 校验错误（无效 URL） | 内联字段错误，阻止提交 |
| 测速失败 | 红色内联结果：“不可达 — <reason>” |

所有错误均通过 `onMessage` 展示为页面级反馈，或为表单 / 测速相关错误提供内联反馈。

---

## 7. 测试策略

### 7.1 API 客户端测试

`frontend/src/api/llmConfig.test.ts`：
- Mock `fetch`。
- 测试每个函数返回符合类型的数据。
- 测试错误处理能正确提取 `detail`。
- 测试提供 `api_key` 时请求体中包含该字段。

### 7.2 组件测试

`frontend/src/components/Settings/EndpointManager.test.tsx`：
- 渲染加载状态。
- fetch 后渲染端点列表。
- 点击“添加端点”时打开表单。
- 创建后调用 API 并刷新列表。
- 测速后调用 API 并更新行状态。

`frontend/src/components/Settings/EndpointForm.test.tsx`：
- 校验必填字段。
- 提交正确的请求载荷。
- 编辑时显示“保留当前密钥”提示。

`frontend/src/components/Settings/ModelSelector.test.tsx`：
- 点击按钮时拉取模型。
- 填充 datalist。
- 选择时调用父级回调。

### 7.3 契约测试

- 验证 `LLMEndpoint` 接口字段名与后端设计文档中 `LLMEndpointResponse` 模式一致。

---

## 8. 样式

复用项目现有的 CSS 变量和类：

- `--success`, `--error`, `--warning`, `--text-secondary`
- `.card`, `.card-title`, `.form-group`, `.form-label`, `.form-input`, `.form-select`, `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-danger`

新增类（如需要）：
- `.endpoint-list` —— 行的网格 / 弹性布局
- `.endpoint-badge` —— 提供商标识
- `.endpoint-status-dot` —— 可达性指示器

保持视觉风格与现有设置面板一致。

---

## 9. 需要创建 / 修改的文件

### 创建
- `frontend/src/api/llmConfig.ts`
- `frontend/src/api/llmConfig.test.ts`
- `frontend/src/components/Settings/EndpointManager.tsx`
- `frontend/src/components/Settings/EndpointManager.test.tsx`
- `frontend/src/components/Settings/EndpointList.tsx`
- `frontend/src/components/Settings/EndpointForm.tsx`
- `frontend/src/components/Settings/EndpointForm.test.tsx`
- `frontend/src/components/Settings/SpeedTestResult.tsx`
- `frontend/src/components/Settings/ModelSelector.tsx`
- `frontend/src/components/Settings/ModelSelector.test.tsx`

### 修改
- `frontend/src/components/Settings/SettingsPanel.tsx` —— 集成 `EndpointManager` 和 `ModelSelector`，提升 message 状态。
- `frontend/src/components/Settings/SettingsPanel.test.tsx` —— 针对新增区域更新测试。

---

## 10. 与后端设计保持一致

| 前端 | 后端 | 契约 |
|---|---|---|
| `LLMEndpoint.id` | `LLMEndpointResponse.id` | UUID 字符串 |
| `LLMEndpoint.provider` | `LLMEndpointResponse.provider` | 字符串，后续改为枚举 |
| `LLMEndpoint.base_url` | `LLMEndpointResponse.base_url` | URL 字符串 |
| `LLMEndpoint.api_key_set` | `LLMEndpointResponse.api_key_set` | 布尔值 |
| `LLMEndpoint.is_default` | `LLMEndpointResponse.is_default` | 布尔值 |
| `LLMEndpoint.last_latency_ms` | `LLMEndpointResponse.last_latency_ms` | 整数或 null |
| `LLMEndpoint.last_total_ms` | `LLMEndpointResponse.last_total_ms` | 整数或 null |
| `LLMEndpoint.is_reachable` | `LLMEndpointResponse.is_reachable` | 布尔值或 null |
| `LLMEndpoint.last_tested_at` | `LLMEndpointResponse.last_tested_at` | ISO 8601 字符串或 null |
| `ModelList.models` | `ModelListResponse.models` | 字符串列表 |
| `SpeedTestResult.latency_ms` | `SpeedTestResponse.latency_ms` | 整数或 null |
| `SpeedTestResult.total_ms` | `SpeedTestResponse.total_ms` | 整数或 null |

两份文档共享相同的端点路径和载荷结构。后端文档是 API 模式的唯一真相源；本文档是 UI 状态和组件行为的唯一真相源。

---

## 11. 待确认问题

1. UI 是否允许重命名 / 删除当前正在使用的端点（即 `PUT /config/llm` 正在使用的端点）？（允许，无需特殊保护；当前配置与端点目录相互独立。）
2. 拉取模型时，若端点不存在，是否应自动保存？（不应；拉取模型属于探索性操作，保存需显式执行。）
3. 测速结果仅在后端缓存，还是同时镜像到前端本地状态？（后端是唯一真相源；前端可乐观更新本地行以提升响应感。）
