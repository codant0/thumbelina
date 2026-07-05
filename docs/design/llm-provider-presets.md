# 多 LLM Provider 配置预设设计文档

## 1. 背景与目标

### 现状

当前 Thumbelina 已有两套可并行的 LLM 配置方式：

1. **SettingsPanel 直接表单** — 用户在页面中填写 provider、model、base_url、api_key，点击 "Switch Model" 调用 `PUT /config/llm` 直接切换。配置仅存在于内存 AppConfig 和 YAML/DB 的 `llm.*` 键中。
2. **EndpointManager 端点管理** — 用户通过 `EndpointManager` 创建多个 `LLMEndpoint` 记录，每个记录包含 provider、name、base_url、api_key、is_default 等字段，持久化到 `system_config` 表。激活时需要通过 `PUT /config/llm` 传入 `endpoint_id` 引用。

### 问题

- 缺少 "预设" 概念：用户无法给一组完整的 LLM 配置（provider + model + base_url + api_key + 额外参数）起一个名字整体保存。
- 快速切换不顺畅：用户要切换必须重新填所有字段，或者先去 EndpointManager 找到端点再切。
- 模型参数未保存：temperature、max_tokens 等额外参数没有和配置一起存储。
- API key 存储存在风险：EndpointManager 通过 JSON 序列化绕过了 `ConfigRepository._is_sensitive` 的检查，将 api_key 明文写入 `system_config` 表。

### 目标

- 用户可创建多个命名预设，每个预设包含完整的 LLM 连接信息。
- 在设置页面可一键激活预设，无需重复填写字段。
- API key 加密存储（不在 DB 中保留明文）。
- 预设可附带额外参数（temperature、max_tokens 等）。
- 向后兼容现有两套配置方式。

---

## 2. 数据模型

### 2.1 SQLAlchemy 持久化模型

新增 `LLMPreset` 表，与现有的 `SystemConfig`、`Conversation` 等表同级。

```python
# 新增文件: src/thumbelina/llm/preset_models.py

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class LLMPresetCreate(BaseModel):
    """创建预设的请求体。"""
    name: str = Field(..., min_length=1, max_length=100, description="用户自定义预设名称")
    provider: str = Field(..., min_length=1, description="LLM provider 名称, 如 openai/anthropic/ollama")
    base_url: str | None = Field(default=None, description="API base URL")
    api_key: str = Field(default="", description="API key")
    model: str = Field(default="", description="默认模型标识")
    extra_params: dict[str, Any] = Field(default_factory=dict, description="额外参数, 如 temperature, max_tokens")
    is_active: bool = Field(default=False, description="是否立即设为活动预设")


class LLMPresetUpdate(BaseModel):
    """更新预设的请求体。留空字段表示不修改。"""
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    extra_params: dict[str, Any] | None = None


class LLMPresetResponse(BaseModel):
    """返回给前端的预设（不含 api_key 明文）。"""
    id: str
    name: str
    provider: str
    base_url: str | None
    api_key_set: bool  # 是否已设置 key，不返回明文
    model: str
    extra_params: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LLMPresetActivateResponse(BaseModel):
    """激活预设的返回。"""
    status: str
    preset_id: str
    preset_name: str
    provider: str
    model: str
```

```python
# 追加到: src/thumbelina/memory/models.py

class LLMPresetRecord(Base):
    """SQLAlchemy model for LLM provider preset storage."""

    __tablename__ = "llm_presets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model: Mapped[str] = mapped_column(String(100), default="")
    extra_params: Mapped[str] = mapped_column(  # JSON dict
        Text, default="{}",
    )
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )
```

### 2.2 加密策略

使用 `cryptography.fernet` 进行对称加密：

- 加密密钥派生自 `AuthService` 的 `secret_key`（配置在 `auth.secret_key`）。
- 如果未配置 `secret_key`，则在应用启动时自动生成一个 32 字节的密钥并存于 `system_config`（键 `_preset_encryption_key`），只在该实例有效。
- 加密过程：`fernet.encrypt(api_key.encode())` → 存 base64 字符串。
- 解密过程：`fernet.decrypt(encrypted_api_key).decode()`。
- 前端永远不获取明文 api_key，仅获取 `api_key_set: bool`。

如果 `cryptography` 不可用，则回退到 base64 + XOR with secret key 的简单方案，仅做混淆而非安全加密。

---

## 3. 后端实现

### 3.1 PresetManager 类

新增文件 `src/thumbelina/llm/preset_manager.py`：

```python
class PresetManager:
    """LLM provider presets CRUD + activation manager.

    职责：
    - 预设的创建、读取、更新、删除
    - 激活预设（调用 RuntimeConfigManager.swap_llm_provider）
    - 加密/解密 api_key
    - 标记 is_active（确保同时只有一个 active）
    """

    def __init__(
        self,
        db_url: str,
        runtime_manager: RuntimeConfigManager,
        agent: ThumbelinaAgent,
        secret_key: str,
    ) -> None: ...

    async def list_presets(self) -> list[LLMPresetResponse]: ...
    async def get_preset(self, preset_id: str) -> LLMPresetResponse | None: ...
    async def create_preset(self, data: LLMPresetCreate) -> LLMPresetResponse: ...
    async def update_preset(self, preset_id: str, data: LLMPresetUpdate) -> LLMPresetResponse | None: ...
    async def delete_preset(self, preset_id: str) -> bool: ...
    async def activate_preset(self, preset_id: str) -> LLMPresetActivateResponse: ...
    async def get_active_preset(self) -> LLMPresetResponse | None: ...

    # 内部方法
    def _encrypt_api_key(self, api_key: str) -> str: ...
    def _decrypt_api_key(self, encrypted: str) -> str: ...
    async def _clear_active_flag(self) -> None: ...
    async def _get_raw(self, preset_id: str) -> LLMPresetRecord | None: ...
```

### 3.2 API 路由

追加到 `src/thumbelina/api/routes/config.py`：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/config/llm/presets` | 列出所有预设 |
| POST | `/config/llm/presets` | 创建新预设（可附带 `is_active: true` 直接激活） |
| GET | `/config/llm/presets/{id}` | 获取单个预设详情 |
| PUT | `/config/llm/presets/{id}` | 更新预设（api_key 为空表示不修改） |
| DELETE | `/config/llm/presets/{id}` | 删除预设 |
| POST | `/config/llm/presets/{id}/activate` | 激活指定预设（自动清除其他预设的 active 标记） |

#### 路由逻辑细节

**POST /config/llm/presets** 创建流程：
1. 验证 `name`、`provider` 必填
2. 加密 `api_key` 后存储
3. 如果 `is_active=True`，清空所有其他预设的 `is_active`，并调用 `swap_llm_provider`
4. 返回 `LLMPresetResponse`（不含 api_key）

**POST /config/llm/presets/{id}/activate** 激活流程：
1. 按 ID 查找预设，如不存在返回 404
2. 解密 api_key
3. 调用 `RuntimeConfigManager.swap_llm_provider()` 进行热切换
4. 更新 `is_active` 标记（清除其他预设的标记）
5. 返回 `LLMPresetActivateResponse`

**PUT /config/llm/presets/{id}** 更新流程：
1. 如果 `api_key` 为 `""` 或 `None`，保持原有 key 不变
2. 如果提供了新的 `api_key`（非空字符串），重新加密存储
3. 如果当前预设是 active 的，更新后自动重新激活（确保配置变更立即生效）

### 3.3 RuntimeConfigManager 改动

在 `src/thumbelina/config/runtime_manager.py` 中增加：

```python
async def swap_llm_by_preset(
    self,
    preset_id: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None,
    agent: ThumbelinaAgent,
    ...  # 其他已有参数
) -> None:
    """根据预设参数切换 LLM provider。

    与 swap_llm_provider 逻辑相同，但额外更新 preset_id 到 AppConfig，
    以便重启后恢复活跃预设。
    """
    # 与 swap_llm_provider 相同逻辑
    # 区别：额外将 preset_id 持久化到数据库
    await self._persist_to_db("llm", "llm.active_preset_id", preset_id)
```

新增 `AppConfig.llm.active_preset_id` 字段（可选，默认 None），用于记录当前激活的预设 ID，以便重启后自动恢复。

### 3.4 app.py 初始化改动

在 `lifespan` 函数中：

```python
# 初始化 PresetManager
from thumbelina.llm.preset_manager import PresetManager
preset_manager = PresetManager(
    db_url=config.memory.database_url,
    runtime_manager=runtime_manager,
    agent=agent,
    secret_key=config.auth.secret_key or "thumbelina-default-fallback-key",
)
app.state.preset_manager = preset_manager

# 启动后检查数据库中是否有 active_preset_id
# 如果有，自动激活该预设
active_preset_id = config.llm.active_preset_id
if active_preset_id:
    try:
        await preset_manager.activate_preset(active_preset_id)
    except Exception:
        logger.warning("Failed to restore active preset %s", active_preset_id)
```

---

## 4. 前端实现

### 4.1 API 层

追加到 `frontend/src/api/llmConfig.ts`：

```typescript
export interface LLMPreset {
  id: string
  name: string
  provider: string
  base_url: string | null
  api_key_set: boolean
  model: string
  extra_params: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface PresetFormData {
  name: string
  provider: string
  base_url?: string
  api_key?: string
  model?: string
  extra_params?: Record<string, unknown>
  is_active?: boolean
}

// API functions
export async function fetchPresets(): Promise<LLMPreset[]>
export async function createPreset(data: PresetFormData): Promise<LLMPreset>
export async function updatePreset(id: string, data: Partial<PresetFormData>): Promise<LLMPreset>
export async function deletePreset(id: string): Promise<void>
export async function activatePreset(id: string): Promise<{ status: string; preset_id: string; preset_name: string; provider: string; model: string }>
```

### 4.2 组件结构

新增两个组件，整合到 SettingsPanel：

```
SettingsPanel
├── PresetManager (新增)
│   ├── PresetList: 显示所有预设 + 激活按钮 + 编辑/删除
│   └── PresetForm (模态/内联): 创建/编辑预设
│       └── ModelSelector (复用已有): 根据 provider+base_url 拉取模型列表
├── LLM Configuration (保留，可折叠)
│   └── 表单 + Switch Model 按钮 (保留旧入口)
├── EndpointManager (保留)
└── ...
```

#### PresetList 组件

预设列表组件，放在 SettingsPanel 的 LLM Configuration 区域上方，作为首要入口。

- 每行显示：预设名称、provider 标签、模型名称、激活状态、操作按钮
- 操作按钮：激活（is_active=false 时显示）、编辑、删除
- 当前 activate 的预设高亮显示（"当前使用" 标签）
- 空状态：显示引导文字，提示创建第一个预设

```tsx
// 伪代码
function PresetList({ presets, activeId, onActivate, onEdit, onDelete }) {
  if (presets.length === 0) {
    return <EmptyState message="No presets yet. Create your first preset to quickly switch between LLM providers." />
  }
  return (
    <div className="preset-list">
      {presets.map(preset => (
        <PresetCard
          key={preset.id}
          preset={preset}
          isActive={preset.id === activeId}
          onActivate={() => onActivate(preset.id)}
          onEdit={() => onEdit(preset)}
          onDelete={() => onDelete(preset.id)}
        />
      ))}
    </div>
  )
}
```

#### PresetForm 组件

创建/编辑预设的表单：

- 预设名称（必填）
- Provider 下拉选择（openai / anthropic / ollama）
- Base URL（可选，默认隐藏 placeholder）
- API Key（密码输入框，编辑时留空表示不修改）
- Model（文本输入 + ModelSelector 集成）
- Extra Params（JSON 编辑区域，可选，折叠）
- 设为激活（勾选框）
- 保存/取消 按钮

#### SettingsPanel 集成方案

在 SettingsPanel 中：

1. **顶部新增区域 "Presets"**：包含 PresetManager 组件
2. **下方保留 "LLM Configuration"** 作为快速切换后备方案，但在激活预设后自动回填表单字段
3. **行为联动**：
   - 点击预设的 "激活" 按钮 → 调用 activate API → 成功后在 LLM Configuration 表单中回显 provider/model/base_url
   - 创建/编辑预设时，填入 provider 和 base_url 后可通过 ModelSelector 拉取模型列表

### 4.3 SettingsPanel 交互流程

```
用户场景 1: 首次使用
1. 进入 Settings 页面
2. Presets 区域显示空白状态："还没有预设，创建第一个预设以快速切换 LLM Provider"
3. 用户点击 "创建预设"
4. 弹出 PresetForm，填写名称、provider、base_url、api_key、model
5. ⚡ 点击 ModelSelector "Fetch models" 测试连接并获取模型列表
6. 保存预设
7. 预设出现在列表中，标记为 "当前使用"（如果勾选了设为激活）

用户场景 2: 日常切换
1. 进入 Settings 页面
2. Presets 列表显示所有已保存的预设
3. 点击目标预设的 "激活" 按钮
4. 系统执行热切换，成功提示
5. 该预设标记为 "当前使用"，其他预设的激活状态被清除

用户场景 3: 编辑预设（如更换 API key）
1. 点击预设的 "编辑" 按钮
2. 修改相关字段
3. ⚡ 如果该预设是当前激活的，保存后自动重新激活
4. 如果该预设不是激活的，仅保存不切换
```

---

## 5. 向后兼容方案

| 场景 | 兼容方案 |
|------|----------|
| 旧用户无预设数据 | 激活预设 API 返回 404 时有明确提示；LLM Configuration 表单正常使用 |
| 同时使用旧 EndpointManager | EndpointManager 保留不变，两个系统独立运行 |
| 从 YAML/env 加载的 LLM 配置 | PresetManager 不覆盖，仅当用户手动激活预设后才切换 |
| 通过 `PUT /config/llm` 手动切换 | 不影响预设数据，Swich Model 后 PresetManager 显示无预设激活 |
| 重启恢复 | 如果上次有 active_preset_id，启动时自动恢复；否则使用 YAML/env 配置 |

---

## 6. 修改文件清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/thumbelina/llm/preset_manager.py` | PresetManager 类（CRUD + 激活 + 加密） |
| `src/thumbelina/llm/preset_models.py` | Pydantic 模型（Create/Update/Response） |
| `frontend/src/components/Settings/PresetManager.tsx` | 预设管理容器组件 |
| `frontend/src/components/Settings/PresetForm.tsx` | 预设创建/编辑表单 |
| `frontend/src/components/Settings/PresetList.tsx` | 预设列表示例（可选，可合入 PresetManager） |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/thumbelina/memory/models.py` | 追加 `LLMPresetRecord` SQLAlchemy 模型 |
| `src/thumbelina/llm/__init__.py` | 导出 PresetManager、preset_models |
| `src/thumbelina/config/models.py` | `LLMConfig` 追加 `active_preset_id: str \| None` 字段 |
| `src/thumbelina/config/runtime_manager.py` | 追加 `swap_llm_by_preset()` 方法，增加 `active_preset_id` 持久化 |
| `src/thumbelina/api/routes/config.py` | 追加 6 个 preset 相关路由；`_get_preset_manager()` 辅助函数 |
| `src/thumbelina/api/app.py` | lifespan 中初始化 PresetManager，启动后恢复 active preset |
| `frontend/src/api/llmConfig.ts` | 追加 preset 相关的 TypeScript 类型和 API 函数 |
| `frontend/src/components/Settings/SettingsPanel.tsx` | 集成 PresetManager 组件 |

### 依赖新增

- `cryptography` — 用于 API key 的 Fernet 加密存储（可选依赖，降级有 fallback）

---

## 7. 接口定义汇总

### 后端 API

```
GET    /api/v1/config/llm/presets
  → 200: LLMPresetResponse[]

POST   /api/v1/config/llm/presets
  Body: { name, provider, base_url?, api_key?, model?, extra_params?, is_active? }
  → 201: LLMPresetResponse

GET    /api/v1/config/llm/presets/{id}
  → 200: LLMPresetResponse
  → 404: { detail: "Preset not found" }

PUT    /api/v1/config/llm/presets/{id}
  Body: { name?, provider?, base_url?, api_key?, model?, extra_params? }
  → 200: LLMPresetResponse
  → 404: { detail: "Preset not found" }

DELETE /api/v1/config/llm/presets/{id}
  → 204: No Content
  → 404: { detail: "Preset not found" }

POST   /api/v1/config/llm/presets/{id}/activate
  → 200: { status: "ok", preset_id, preset_name, provider, model }
  → 404: { detail: "Preset not found" }
  → 422: { detail: "Provider creation failed: ..." }
```

### 前端组件接口

```typescript
// PresetManager props
interface PresetManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

// PresetList props
interface PresetListProps {
  presets: LLMPreset[]
  activeId: string | null
  onActivate: (id: string) => Promise<void>
  onEdit: (preset: LLMPreset) => void
  onDelete: (id: string) => Promise<void>
}

// PresetForm props
interface PresetFormProps {
  initialValues?: LLMPreset  // 编辑模式需要
  onSubmit: (data: PresetFormData) => Promise<void>
  onCancel: () => void
}
```

---

## 8. 前端交互状态矩阵

### PresetManager

| 状态 | 表现 |
|------|------|
| **加载中** | Skeleton/spinner，显示 "正在加载预设..." |
| **空** | 空白状态插画 + "还没有预设，创建第一个预设以快速切换 LLM Provider" + 创建按钮 |
| **有数据** | 预设卡片列表，当前激活的高亮 + "当前使用" badge |
| **创建中** | Form 提交按钮 loading，禁止复提交 |
| **激活中** | 对应预设卡片按钮变为 spinner，禁止点击其他激活按钮 |
| **删除中** | 对应预设卡片删除按钮 loading，操作完成后移除卡片 |
| **错误** | 顶部 toast 提示错误信息（API error / network error） |
| **成功** | 顶部 toast 提示成功信息 |

### PresetForm

| 状态 | 表现 |
|------|------|
| **初始** | 空表单（创建模式）或预填数据（编辑模式）|
| **验证失败** | 字段下方红色提示文字（名称必填、URL 格式校验等）|
| **提交中** | 保存按钮 spinner 并 disabled |
| **保存成功** | 关闭表单，列表刷新，toast 提示成功 |
| **保存失败** | 表单不关闭，顶部或对应字段提示错误 |

---

## 9. 实施步骤建议

1. 数据模型：新增 `LLMPresetRecord` 表 + preset_models.py
2. 加密工具：实现 `_encrypt_api_key` / `_decrypt_api_key`，依赖 `cryptography`
3. PresetManager 类：CRUD 操作 + 激活逻辑
4. 后端路由：6 个新端点 + app.py 初始化 + active preset 恢复
5. 前端 API 层：TypeScript 类型 + API 函数
6. 前端组件：PresetForm + PresetList + PresetManager
7. 前端集成：嵌入 SettingsPanel，行为联动
8. 测试：后端 pytest + 前端 vitest
9. 回归：确保旧 EndpointManager 和 SettingsPanel 直连表单不受影响
