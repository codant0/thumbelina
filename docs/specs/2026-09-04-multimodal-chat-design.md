# 聊天 / 码农模块 — 多模态对话（图片）能力 — 设计交付

- 日期：2026-09-04
- 技能：brainstorming + frontend-design-ui-ux（设计规格，含实现拆解）
- 状态：草案 v2 — 按评审与用户决策修订：免鉴权单用户（无身份模型）/ 统一标准图像块（provider 层零改动）/ ensure_schema 迁移语义（无 Alembic）/ 砍除软删 GC、秒传、EXIF 剥离等过度设计
- 影响面：
  - 前端：`frontend/src/components/Chat/{InputBox, MessageList, ChatWindow}.tsx`、`frontend/src/components/Coder/*`（共用 InputBox）、`frontend/src/hooks/useWebSocket.ts`、`frontend/src/types/chat.ts`、`frontend/src/api/{conversations,attachments}.ts`、`frontend/src/styles/chat.css`、`frontend/src/i18n/locales/{en,zh-CN}.json`
  - 后端：`src/thumbelina/api/{websocket,schemas}.py`、`src/thumbelina/api/routes/attachments.py`（新增）、`src/thumbelina/agent/graph.py`（`_build_initial_messages` + `run/stream` 接受多模态内容）、`src/thumbelina/agent/compression/base.py`（图像块 token 占位估算）、`src/thumbelina/filestore/atomic.py`（新增 `write_bytes_atomic` 字节原子写）。**provider 层（`llm/*.py`）零改动**——统一标准图像内容块由已装 LangChain 各 provider 内部转换（§3.3）

---

## 1. 用户与上下文

**用户**：Thumbelina WEB + 桌面使用者，在「聊天」「码农（Coder）」两个模块中向模型提问。当前两条路径都仅支持纯文本：

- 选不到具体 API / 工具版本时只能粘贴一长串错误日志
- 截图报错（控制台 / IDE / 浏览器 DevTools）只能口头描述，无法把图直接给模型看
- 码农场景下，前端 UI 异常、设计稿对照、像素级 bug 都需要把图喂给模型

**产品约束**：
- 聊天与码农共用同一个 `InputBox` 组件，本设计一次覆盖两处
- 不破坏现有 WS 协议（`{message, conversation_id}` 单字段）。多模态是**可选增强**，向后兼容（纯文本客户端照常工作）
- 已有的「压缩 / 停止 / 待发队列 / 打字机 / 中断续传」行为不能回退
- 不引入新依赖：图片读取走浏览器原生 `FileReader` / `URL.createObjectURL`，后端复用 `filestore` 原子写范式（新增约 20 行的 `write_bytes_atomic`），尺寸解析用纯 `struct` 读文件头（不用 Pillow）
- 图片随检查点历史持久保留并在后续轮次重放（多模态模型可回看此前图片，与主流助手行为一致）；token 估算把每张图按固定 765 token 占位计入，防止压缩阈值失真
- 个人单用户项目：无身份 / 多用户模型，附件不做归属校验（风险接受见 §8）

**设计方向**：把图片视作「临时附件」——会话级、本地预览、上传后服务端留 URL。设计语言延续现有 InputBox 的紧凑工具条美学（沿用 `.btn-pill` / `.pending-float` 玻璃态、主题令牌驱动）。

**Design Read**：附件 + 拖放悬停态 + 流式传输进度条。
**Dial**：`VARIANCE 2`（沿用现有按钮/胶囊语言）· `MOTION 1`（拖入悬停淡入，120ms）· `DENSITY 3`（上限 4 张缩略图，超出直接拒绝，无折叠态）。

---

## 2. 现状缺口清单（Gap Inventory）

### 2.1 前端
| 位置 | 现状 | 缺口 |
|---|---|---|
| `types/chat.ts` `Message` | 仅 `content: string` | 没有 attachments 字段，渲染端没法展示历史图片 |
| `InputBox.tsx` | 单 `<textarea>` + `<form>` | 无附件预览区、无文件按钮、无拖放监听 |
| `MessageList.tsx` `msg-content` | 用户消息纯字符串展示 | 无图片缩略图 / 灯箱（lightbox） |
| `useWebSocket.ts` `sendMessage` | 发送 `{message, conversation_id}` | 无附件载荷、无多模态透传字段 |
| `useWebSocket.ts` 历史回放 `loadHistory` | `messages` 仅恢复 `content + thinking` | 历史图片丢失 |
| `api/conversations.ts` | `clearConversationMessages` 走 `DELETE /conversations/{id}/messages` | 暂无附件 URL→持久化桥接 |
| `i18n` chat.* | 无 `attachment.*` 命名空间 | 缺所有新文案键 |

### 2.2 后端
| 位置 | 现状 | 缺口 |
|---|---|---|
| `api/schemas.py` `WebSocketMessage` | `message: str(min_length=1)` | 不允许纯图片不发文字；缺 `attachments` 字段 |
| `api/websocket.py` `_run_generation` | `agent.stream(message, ...)` / `agent.run(message, ...)` | 不能透传图片 |
| `agent/graph.py` `_build_initial_messages` | 仅追加 `HumanMessage(content=user_input)` | 没有组装 LangChain 多模态内容块 |
| `llm/base.py` `_to_langchain_messages` | `HumanMessage(content=msg["content"])` | 仅服务 channels/摘要器等次级路径；聊天路径不经过它（`agent/nodes.py` 直接调模型），**无需改动** |
| `llm/openai.py` / `anthropic.py` / `ollama.py` / `openai_responses.py` | 全部只用字符串 content | **无需改动**：标准 v1 图像内容块（§3.3）由已装 LangChain 各 provider 内部转换 |
| `repository/*` | 持久化消息表 `content TEXT` | 需 `attachments JSON` 列（可空），保留向旧消息兼容 |
| `filestore/*` | 仅有文本原子写（`write_text_atomic`）与文件锁 | 无字节原子写、无 HTTP 端点接收上传 |

---

## 3. 数据流（设计）

### 3.1 上传策略：客户端直传 + 引用发送

为避免 WS 大块 base64 拖慢流式通道：

1. 用户拖入或点击选图 → 前端 `Array.from(files)` 校验（≤4 张、≤10MB/张、image/* MIME）；大于 800KB 的图先在客户端用 canvas 按最长边 2048px 缩放并重编码 JPEG（quality 0.85）——天然剥离 EXIF（GPS/设备指纹不外传），且保证 base64 低于 Anthropic 5MB 图像上限
2. 前端走 `POST /api/v1/attachments`（multipart/form-data）逐张顺序上传，得到 `{id, mime, size, width, height, sha256}`（不返回 url，前端按 §4.3 自拼）
3. 失败的图保留在本地预览，标记「上传失败」徽标（重试按钮）
4. 用户点发送：WS 帧 `{"message": "...", "conversation_id": "...", "attachments": [{"id": "att_xxx", "mime": "image/png"}, ...]}`。`message` 与 `attachments` **至少一项非空**（见 §4.1）
5. 后端校验每个 `attachment_id` 存在于 `attachments` 表（个人项目无多用户，不做归属校验），写入消息 `attachments JSON` 列；调用 LLM 时组装标准图像内容块（§3.3）
6. 服务端保留原图（`filestore` 原子写范式，目录 `attachments/{yyyy}/{mm}/{uuid}.{ext}`），提供 `GET /api/v1/attachments/{id}` 返回图片

### 3.2 历史与压缩

- 消息持久化：`messages.attachments JSON` 列存 `[{id, mime, width, height, alt?}]`（不存 base64，不存 url，url 由前端按 id 拼接）
- 历史回放：历史直接返回持久化的 attachments 数组（无软删/GC 机制）；文件已物理删除的引用由前端破图占位兜底（灰色蒙层 + 「重试加载」按钮）
- LLM context：带图 `HumanMessage`（图像内容块）会写入 LangGraph 检查点并在**后续所有轮次重放**——图片随历史保留，模型可回看（此前「仅当前轮注入」的说法与 checkpointer 机制相悖，已修正）。代价是检查点体积与 token 占用随图片数增长，个人项目可接受；`estimate_messages_tokens` 扩展为每张图固定计 765 token（GPT-4V 基线占位），否则压缩阈值失真（归入 B4）

### 3.3 统一标准图像内容块（provider 层零改动）

使用 LangChain 标准 v1 内容块，**一个格式走遍全部 4 个 provider**（已装版本 langchain-core 1.4.8 / langchain-openai 1.3.3 / langchain-anthropic 1.4.8 / langchain-ollama 1.1.0 均在内部各自转换；openai_responses 的 Responses API 亦自动转换）：

```jsonc
[
  { "type": "text", "text": "看下截图里这个按钮为什么没对齐" },
  { "type": "image", "base64": "<raw base64，不带 data: 前缀>", "mime_type": "image/png" }
]
```

**禁止嵌套结构**（如 `{type:"image", source:{type:"base64",...}}`）——langchain-ollama 的 `is_data_content_block` 只认扁平的 `base64` / `url` / `source_type` 键，嵌套会直接抛 ValueError。

不支持的模型（非视觉 Ollama 模型、老模型）**不做白名单拦截**（本项目端点为任意 OpenAI 兼容模型，按模型名白名单不可靠）：provider 报错时走现有 WS `error` 帧由前端展示，用户自行切换模型。

---

## 4. 协议增量

### 4.1 前端 → 后端（WS 上行）

```jsonc
{
  "message": "看下截图里这个按钮为什么没对齐",
  "conversation_id": "conv_abc",
  "attachments": [
    { "id": "att_xxx", "alt": "首页 hero 区按钮" }
  ]
}
```

**约束**：`message` 与 `attachments` **至少一项非空**：
- 纯文本：`message: "..."` + `attachments: null/[]`
- 仅图片：`message: ""` + `attachments: [{...}]`
- 后端用 Pydantic 自定义 validator 强制该不变量；前端发送按钮启用条件：`text.trim() !== "" || attachments.length > 0`

兼容性：纯文本客户端不传 `attachments`，后端走现有分支。

### 4.2 后端 → 前端（REST 历史）

```jsonc
{
  "id": "msg_xyz",
  "role": "user",
  "content": "看下截图",
  "attachments": [
    { "id": "att_xxx", "mime": "image/png", "width": 1280, "height": 720, "alt": "首页 hero" }
  ],
  "reasoning_content": null,
  "created_at": "..."
}
```

**过滤规则**：无软删/GC 机制——历史响应直接返回持久化的 attachments 数组。已物理删除的文件由前端破图占位兜底（§5.2.2），后端不做序列化期过滤。

### 4.3 前端 → 后端（REST 上传）

`POST /api/v1/attachments`
- `multipart/form-data`：单 `file` 字段，额外可选 `alt`
- 限速：单张 ≤10MB、白名单 `image/png|image/jpeg|image/webp|image/gif`
- EXIF 隐私：由 **F2 的客户端 canvas 重编码**天然剥离（GPS / 设备指纹不外传）；服务端不做二次处理
- 响应：`{id, mime, size, width, height, sha256}`（不返回 url，前端拼 `/api/v1/attachments/{id}`）

`GET /api/v1/attachments/{id}`
- 无鉴权（个人部署，与项目现状一致）：返回图片字节 + `Content-Type`
- 私有缓存：`Cache-Control: private, max-age=86400`

`DELETE /api/v1/attachments/{id}`
- **物理删除**：删除行 + 磁盘文件（无软删 tombstone、无后台 GC——个人项目不做 GC 调度，避免引入无人执行的清扫任务）
- 已被历史消息引用的 id 删除后，历史缩略图由前端破图占位兜底

---

## 5. UI / UX 设计

### 5.1 InputBox（聊天 + 码农共用）

#### 5.1.1 解剖

```
┌─────────────────────────────────────────────────────────┐
│  🖼 [缩略图1 ×] [缩略图2 ×] [缩略图3 ×]   （最多 4 张）  │  ← attachments-strip（条件渲染）
├─────────────────────────────────────────────────────────┤
│  📎 添加图片                                              │  ← attach-button（icon-only，32×32）
│ ┌───────────────────────────────────────────────────┐   │
│ │ 输入消息…                                          ↩│   │
│ │                                                    │   │
│ └───────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

- **工具条顺序**：`📎` 按钮 + 现有 textarea + 现有发送按钮（流式时仍并排出现停止按钮）
- **缩略图尺寸**：48×48，圆角 8px，hover 显示文件名 + 尺寸的悬浮提示
- **删除**：缩略图右上角 16×16 「×」按钮（点击立即移除，未上传的图同步中止 `XMLHttpRequest`）
- **发送按钮启用条件**：`text.trim() !== "" || attachments.length > 0`（与 §4.1 协议约束一致）

#### 5.1.2 拖放交互

- 监听 `chat-area`（含 CoderPage 包裹元素）的 `dragenter / dragover / dragleave / drop`
- 拖入时全屏覆盖一层 `.drop-overlay`：
  - 半透明深色蒙层（`background: rgba(0,0,0,0.45)`，120ms 淡入）
  - 中央卡片：「松开以上传图片」（`Drop images here`）
  - 卡片虚线边框 + 内缩 16px + 仅出现在拖动进入视口的瞬间
- `drop` 后立即开始上传，缩略图出现在 `attachments-strip` 中，进度由每张图上的小圆环（SVG stroke-dashoffset）显示
- 上传为**顺序执行**（≤4 张，无并发队列复杂度）；已有 4 张待发图时再添加直接拒绝并 toast 提示
- 不在拖放覆盖层时仍可点 📎 按钮 → 触发隐藏的 `<input type="file" accept="image/*" multiple>`

#### 5.1.3 状态

| 状态 | 视觉 |
|---|---|
| idle | 无缩略图、无拖放蒙层 |
| 拖入中 | 全屏 `.drop-overlay` 淡入 |
| 上传中 | 缩略图右下角 12×12 进度环（accent 色） |
| 上传失败 | 缩略图叠加 ⚠️ + 红色边框 + 「重试」按钮（缩略图右键 / 长按触发） |
| 已有 4 张再添加 | 拒绝并提示「最多 4 张」（与 §3.1 校验、B3 服务端上限一致，无折叠态） |
| 流式时仍可添加 | 流式按钮（stop + send）保留位；**新增/删除的 attachments 仅入队到下一轮**，不影响当前轮 LLM 调用 |
| 流式中 + 有新附件（pending） | 新缩略图带「下一轮发送」徽标（区别于立刻发送的缩略图） |

#### 5.1.4 可达性

- 📎 按钮：`aria-label="添加图片"`，键盘聚焦时回车触发
- 缩略图：`role="img"` + `aria-label="{文件名}, {尺寸}"`；删除按钮 `aria-label="移除 {文件名}"`
- 文件名超长（>30 字符）截断为前 25 + `…` + 后 4，避免 `aria-label` 溢出
- 拖放区：仅鼠标交互；键盘用户通过 📎 按钮完成等效操作（避免与系统级 a11y 拖放冲突）

### 5.2 MessageList（用户消息图片展示）

#### 5.2.1 位置

- 在 `.message.user .msg-content` **上方**插入 `.msg-attachments` 横排（≤4 张，缩略图 64×64；上限与输入端一致，无折叠态）
- 缩略图点击 → 打开 `AttachmentLightbox`（**新建轻量遮罩组件**，不复用 `FloatWindow`——后者是可拖拽迷你窗，最小 320×220、无遮罩、无方向键，定位不符）：黑色 80% 不透明遮罩 + 图片居中 + 顶部关闭按钮 + 左右切换（多图时）+ 键盘 `← / → / Esc`
- assistant 消息暂不展示用户原图（避免重复）；需要时改为「基于以下图片」的引用折叠块

#### 5.2.2 缩略图 URL 解析与失败态

- `attachments: [{id, mime, ...}]` → URL = `${API_BASE}/attachments/${id}`
- 加载失败（404 / 网络 / 服务端错误统一处理）：破图占位（灰色蒙层 + 「重试加载」按钮）——后端无过滤机制，死链由前端兜底

### 5.3 Coder 模块

- `CoderPage.tsx` 渲染 `ChatWindow`，当前 InputBox 通过 toolbar 注入 ThinkingSelector 等；本设计不修改 CoderPage 容器，**0 改动**——所有 UI 由 `InputBox` 内部完成
- Coder 页特有的 `WorkspacePicker` / `CoderSidebar` 不受影响
- **跨 Workspace 切换**：`ChatWindow` 内部 state 的 attachments 随会话切换清空（与现有「按会话切换清空」语义一致）

### 5.4 视觉令牌（沿用 themes.css）

- 拖放蒙层背景：`rgba(0,0,0,0.45)`（硬编码，因仅蒙层）
- 缩略图边框：`var(--border)`
- 缩略图 hover 边框：`var(--accent-border)`
- 上传进度环：`stroke="var(--accent)"`
- 错误边框：`var(--error)`
- 折叠徽标背景：`var(--bg-elevated)`，文字色 `var(--text-secondary)`
- 「下一轮发送」徽标：`var(--warning)` 边框 + 半透明背景

---

## 6. 前端实现拆解

### Task F1：类型与协议层
- `types/chat.ts`
  - 新增 `AttachmentRef = { id: string; mime: string; width?: number; height?: number; alt?: string }`
  - `Message.attachments?: AttachmentRef[]`
  - `ChatRequest.attachments?: { id: string; alt?: string }[]`
- `hooks/useWebSocket.ts`
  - `sendMessage(text, convId, attachments?)` 扩展签名，序列化 `attachments` 进 WS 帧
  - **`PendingEntry` 扩展携带 `attachments`**：待发队列自动发送 / 「立即执行」时随文字一起发出（否则附件会丢）
  - `loadHistory` 把后端返回的 `attachments` 字段合并进 `Message`
  - **`sendButton.enabled` 计算属性集中到 `useWebSocket` 内部**：`enabled = text.trim() !== "" || attachments.length > 0`，避免每个组件重复实现

### Task F2：附件 API 客户端 + 客户端压缩
- 新增 `api/attachments.ts`：`uploadAttachment(file, {alt?})` 与 `attachmentUrl(id)` 工具
- `lib/imageUtils.ts`：`downscaleImage(file)` —— 大于 800KB 的图用 canvas 按最长边 2048px 缩放并重编码 JPEG（quality 0.85）后返回 Blob；同时天然剥离 EXIF（GPS / 设备指纹），保证 base64 低于 Anthropic 5MB 图像上限
- `api/conversations.ts`：扩展 `ConversationDetailSchema` 类型（在 TS 侧标注 `messages[].attachments`，与 backend schema 对齐）

### Task F3：InputBox 改造
- `components/Chat/InputBox.tsx`：
  - 接受 `attachments: LocalAttachment[]` 与 `onAttachmentsChange`
  - 在 `form` 上方条件渲染 `<AttachmentsStrip>`
  - 在 `form` 左侧加入 `<AttachButton>`（icon-only）+ 隐藏 `<input type="file">`
  - 内部顺序上传（≤4 张，超出 toast 拒绝）
  - `sendMessage` 时把 `attachments` 一并通过新 props 传给上层
- `components/Chat/MessageList.tsx`：
  - 在 `MessageItem` 中 `msg.role === 'user' && msg.attachments?.length` 时渲染 `<MessageAttachments>` + `<AttachmentLightbox>`（新建遮罩组件，见 F5）
- `components/Chat/ChatWindow.tsx`：
  - 把 `attachments` 提升到 `ChatWindow` 内部 state，按会话切换清空
  - **`pendingAttachments` 单独管理流式中新加/删的图**（不入当前轮；下一轮发送时合并进 `attachments` 后清空 pending）
  - `handleSend` 改为 `sendMessage(text, convId, attachments)`
- Coder 模块：因共用 `ChatWindow` + `InputBox`，**0 改动**

### Task F4：拖放覆盖层
- 新增 `components/Chat/DropOverlay.tsx`
- `useDropZone` hook（`hooks/useDropZone.ts`）：
  - 接收 `onFiles(File[])`，内部管理 `isDragging` 状态
  - 监听 `document` 级别 dragenter/dragleave/drop（避免子元素冒泡抖动）
  - 校验 `e.dataTransfer.types.includes('Files')` 才显示蒙层，避免码农页代码拖选误触
- 挂载点：挂在 `ChatWindow` 与 `CoderPage` 的根容器（统一使用现有 `chat-area` 类名；若不存在，由 F4 任务新建该类名并替换相关选择器）

### Task F5：Lightbox
- 新建 `components/Chat/AttachmentLightbox.tsx`：轻量全屏遮罩组件（`position:fixed` 全屏遮罩 + 图片居中 + 关闭 + 左右切换 + `← / → / Esc` 键盘）
- **不复用 `FloatWindow`**——那是可拖拽迷你窗（最小 320×220、无遮罩、无方向键），与图片查看定位不符

### Task F6：CSS
- `styles/chat.css` 新增：
  - `.attachments-strip` / `.attachment-thumb` / `.attachment-thumb__remove` / `.attachment-thumb__progress`
  - `.attach-btn` / `.attach-btn:hover`
  - `.drop-overlay` / `.drop-overlay__card`
  - `.msg-attachments` / `.msg-attachment-thumb`
  - `.lightbox-toolbar` / `.lightbox-counter`
  - `.attachment-thumb--pending`（下一轮发送标记）
- 全部消费主题令牌；进度环用 SVG `stroke-dashoffset` 动画（无外部库）

### Task F7：i18n
- 新增 `chat.attachments.*` 命名空间（zh-CN / en 双语同步）
  - `addImage`「添加图片」/ `dropHint`「松开以上传图片」/ `removeAlt`「移除图片」
  - `uploadFailed`「上传失败，重试」/ `uploading`「上传中…」/ `tooLarge`「图片超过 10MB」
  - `unsupportedType`「仅支持 PNG / JPEG / WebP / GIF」
  - `lightboxOpen`「查看图片」/ `lightboxClose`「关闭」/ `lightboxPrev` / `lightboxNext`
  - `pendingNextTurn`「下一轮发送」/ `maxImages`「最多 4 张」

### Task F8：前端测试
- `InputBox.test.tsx`
  - 点击 📎 触发隐藏 file input 的 `click()`
  - 选中 2 张图 → 缩略图渲染，点击 × 移除
  - 选择 1 张 12MB 的图 → 显示「图片超过 10MB」提示（不进入上传）
  - 选择 1 个 .pdf → 「仅支持 PNG / JPEG / WebP / GIF」提示
  - 上传失败模拟：mock `uploadAttachment` reject，缩略图显示错误态 + 「重试」按钮
  - **仅传图片不发文字**：附件非空 + 文字为空 → 发送按钮启用，可成功发送
  - **仅发文字无附件**：附件为空 + 文字非空 → 行为与现有保持一致
  - **文字与附件均为空** → 发送按钮禁用
  - **同图重复上传**：mock `uploadAttachment` 返回同 id → 缩略图不重复
  - **超出上限**：已有 4 张再添加第 5 张 → toast「最多 4 张」，不上传
- `MessageList.test.tsx`
  - `attachments=[{id:"a1"}]` 渲染 1 张缩略图，`src` 拼对 `/api/v1/attachments/a1`
  - 加载失败显示破图占位 + 重试按钮
  - 点击缩略图 → `AttachmentLightbox` 出现，`Esc` 关闭
- `useWebSocket.test.ts`
  - `sendMessage(text, cid, [{id:"a1"}])` → WS 帧包含 `attachments`
  - 后端下推 `attachments` 字段被合并进 `messages[].attachments`
- 新增 `useDropZone.test.tsx`：模拟 dragenter/dragover/drop 事件链，验证回调被触发；**码农页拖代码块（`dataTransfer.types` 不含 `Files`）不触发蒙层**
- `ChatWindow` 集成：流式中排队消息携带附件；对上一条带图消息点「重新生成」时图片随文字一起重发
- Coder 页冒烟：CoderPage 复用 ChatWindow，附件发送与拖放在码农页等效可用
- 视觉回归：复用现有 `InputBox.visual.test.tsx` 风格，加一张「带 2 张缩略图 + 流式中」的快照；新增「下一轮发送 pending 徽标」快照

---

## 7. 后端实现拆解

### Task B1：持久化 schema 演进（无 Alembic —— 本项目无迁移基建）
- 项目机制是 `Base.metadata.create_all` + `ensure_schema()` 自动 `ALTER TABLE ADD COLUMN`（`repository/db.py` + `repository/models.py`），**不引入 Alembic**（存储重构方案已于 2026-08-30 回退，决策记录见 `docs/plans/2026-08-30-event-timer-tasks-design.md` 的 D3 行）：
  - `Message` 新增 `attachments TEXT NULL` 列（JSON 序列化），启动时 `ensure_schema` 自动补列
  - 新增 `Attachment` ORM 模型（`attachments` 表），`create_all` 自动建表
- `attachments` 表列：`id (TEXT PK)` / `mime` / `size` / `width` / `height` / `sha256 (NULL)` / `relative_path` / `created_at`。**无 user_id / FK 归属列、无 deleted_at**（个人单用户、无软删）
- `MessageSchema` 新增 `attachments: list[dict] | None = None`
- `ConversationDetailSchema.messages` 同步
- 读取层：老消息 `attachments` 为 `None`，前端判空按空数组处理

### Task B2：REST 上传端点
- 新增 `api/routes/attachments.py`
  - `POST /api/v1/attachments`：multipart/form-data 接收单文件，校验 size / mime；图片尺寸用纯 `struct` 解析 PNG/JPEG/GIF/WebP 文件头（**不引入 Pillow**，EXIF 已由客户端重编码剥离）；写入 `attachments/{yyyy}/{mm}/{uuid}.{ext}`（`filestore` 新增 `write_bytes_atomic`，同现有原子写范式），记录元数据到 `attachments` 表
  - `GET /api/v1/attachments/{id}`：返回字节流（无鉴权，个人部署）+ 路径穿越防护（`relative_path` 逃逸附件目录时 404）
  - `DELETE /api/v1/attachments/{id}`：**物理删除**行 + 磁盘文件（无软删 / 无后台 GC 任务）
  - 无配额（个人项目，附件目录可整目录备份/清理）
- 注册到 `app.py` 现有 `include_router` 列表
- 不在 filestore 里塞业务规则（字节写原语进 `filestore/atomic.py`，路由层只做校验与编排）

### Task B3：WS 协议扩展
- `schemas.py`
  - 新增 `AttachmentRefIn = { id: str, alt?: str }`
  - `WebSocketMessage` 增 `attachments: list[AttachmentRefIn] | None = None`
  - **约束收敛**：`message: str(min_length=0)` + 自定义 validator：`message.strip() != "" or (attachments and len(attachments) > 0)`；单轮附件 ≤4
- `websocket.py`
  - **主循环现有的 `if not parsed.message.strip(): "Empty message"` 守卫必须同步放宽**：`attachments` 非空时放行（否则纯图片发送被拦，B3 改 schema 也无济于事）
  - 存在性校验（无用户体系）：每个 attachment id 必须在 `attachments` 表中存在
  - 校验失败 → 回 `{"error": "Invalid attachment", "missing_attachment_ids": [...]}`，不开新一轮生成
  - 校验通过 → 把 `attachments` 透传给 `_run_generation`

### Task B4：Agent 接受多模态内容（真实调用路径）
- 注意：聊天路径**不经过** `llm/base.py` 的 `_to_langchain_messages`——`agent/nodes.py` 的 `call_model` 直接调 LangChain 模型，图像块随 graph state 透传即可
- `agent/graph.py`
  - `_build_initial_messages` 改为接收 `(user_text: str, attachment_refs: list[dict])`；当 `attachment_refs` 非空时按 §3.3 组装 `HumanMessage(content=[{type:"text",...}, {type:"image", base64...}])`，否则保持现状（字符串）
  - `run()` / `stream()` 签名追加 `attachments: list[dict] | None = None`，透传到 `_build_initial_messages`
  - `_persist_message` 写入时 `attachments` 序列化为 JSON 落库
  - **微信绑定的会话为纯文本通道**：检测到 WeChat 会话时忽略图像块（仅文本进入模型），轨迹记「skipped N image(s)」
- `agent/compression/base.py`：`estimate_messages_tokens` 扩展——每张图像内容块固定计 765 token（GPT-4V 基线占位），防止压缩阈值失真
- `trajectory_recorder.record_user` 同步支持：
  - **图片摘要**：`f"attached {N} image(s){', alt: ' + truncate(alt, 50) if alt else ''}"`
  - alt 文本截断到 50 字符后追加进 trajectory 摘要，避免长文本污染轨迹

### Task B5：多模态内容块构建工具（替代原「LLM 翻译层」）
- 原方案按 provider 各写一套翻译——已证实**不必要**：统一标准块 `{type:"image", base64}` 在已装 4 个 provider 上均可工作（§3.3），**`llm/*.py` 零改动**；也不做 `supports_multimodal` 白名单与 `attachment_skipped` 降级事件（端点为任意 OpenAI 兼容模型，白名单不可靠；provider 报错走现有 WS `error` 帧）
- 新增 `agent/multimodal.py`（轻量工具）：按 attachment id 从附件目录读字节 → 校验 base64 体积（>5MB 时报错帧，正常由 F2 客户端缩放兜底）→ 产出标准图像内容块列表，供 B4 的 `_build_initial_messages` 使用

### Task B6：后端测试（注意：实际目录是 `tests/test_api/`，非 `tests/api/`）
- `tests/test_api/test_attachments.py`：上传 / 下载 / 删除 / size 超限 / mime 不支持 / 路径穿越防护（无鉴权场景）
- `tests/test_api/test_websocket_attachments.py`：WS 帧携带 attachments → 持久化记录 → LLM 调用收到多模态内容（mock LLM provider）；**`message="" + attachments=[...]` 通过验证**（Empty message 守卫放宽）；**不存在的附件 id → 错误帧且不开始生成**
- `tests/agent/test_multimodal_blocks.py`：`_build_initial_messages` 组装的图像块结构（含 base64）单元测试；WeChat 会话忽略图像块
- `tests/repository/test_message_attachments.py`：JSON 字段读写、**老消息读取返回 `None`**、图像块 token 占位估算

---

## 8. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 历史消息里 `attachments=null` vs `attachments=[]` 行为不一致 | 老消息读出为 `None`，前端统一判空按空数组处理；B6 显式覆盖该 case |
| attachment id 引用死链（附件被物理删除后历史图片 404） | 前端破图占位兜底（灰色蒙层 + 重试）；无软删/GC 机制，个人项目可接受 |
| LLM 不支持图片（老模型、Ollama 非视觉模型） | 不做模型名白名单（端点为任意 OpenAI 兼容模型，白名单不可靠）；provider 报错走现有 WS `error` 帧由前端展示，用户自行切换模型 |
| WS 帧携带 attachments 引用 id（不是数据本身），但历史回放要还原图片 | attachments id 持久化到 messages JSON 列，回放时按 id 拉 URL |
| 单用户免鉴权：附件接口无归属校验 | 个人助手项目定位、部署在可信本机/内网；未来多用户需求出现时再加归属列 |
| base64 超 Anthropic 5MB 图像上限 | F2 客户端 canvas 缩放重编码兜底；B5 服务端再校验一次并报错帧 |
| EXIF 隐私泄漏（GPS / 设备指纹） | F2 客户端重编码天然剥离；服务端不做二次处理 |
| 服务端磁盘占用 / 检查点体积随图片数增长 | 单张 ≤10MB + 客户端压缩；个人项目不做配额，附件目录可整目录备份/清理 |
| 客户端 base64 直传 vs URL 引用 | 本设计走「客户端先上传拿 id，WS 只传 id」：避免 WS 大块延迟（WS 帧上限 1MB）、便于历史回放 |
| 历史压缩逻辑把图片 base64 算进 token | `estimate_messages_tokens` 每张图固定计 765 token 占位（见 §3.2，归入 B4） |
| 拖放覆盖层影响码农页的代码块拖选 | 用 dragenter/dragleave 计数器 + 校验 `e.dataTransfer.types.includes('Files')`，只在携带文件时显示蒙层；F8 测试覆盖码农页拖代码不触发蒙层 |
| 流式中修改 attachments 破坏 LLM 调用 | 流式中的 attachments 操作仅入队到 `pendingAttachments`，下一轮发送时合并；不影响当前轮 |
| 微信通道纯文本，绑定会话收到附件 | WeChat 会话忽略图像块（B4），仅文本进入模型 |
| 待发队列 / 重新生成丢附件 | `PendingEntry` 携带 attachments（F1）；重新生成重发上一条用户消息时带上其附件（F8） |

---

## 9. 验收标准

- [ ] 聊天页：拖入 1 张 PNG → 缩略图出现 → 发送 → 助手消息内容与图片相关
- [ ] 聊天页：同时上传 4 张图，全部成功发送，UI 不溢出
- [ ] **聊天页：仅传图片不发文字可成功发送**（P0 边界）
- [ ] **聊天页：文字与附件均为空时发送按钮禁用**
- [ ] 聊天页：上传 1 张 12MB 图，提示「图片超过 10MB」且不发起请求
- [ ] 聊天页：上传 .pdf，提示「仅支持 PNG / JPEG / WebP / GIF」
- [ ] 聊天页：上传中网络断开，缩略图显示错误态 + 「重试」按钮，恢复后能继续发送
- [ ] **聊天页：流式回复中添加/删除图片仅入队到下一轮，当前轮 LLM 不受影响**
- [ ] **聊天页：流式回复中排队的待发消息携带图片，自动发送时不丢失**
- [ ] **聊天页：对上一条带图消息点「重新生成」，图片随文字一起重发**
- [ ] 聊天页：历史消息中的图片在会话切换后仍能正确显示（缩略图 + 灯箱）
- [ ] 聊天页：灯箱支持 ← / → / Esc 键盘操作
- [ ] **码农页：拖代码块（不带文件）不触发拖放蒙层**
- [ ] **码农页：切换 WorkspacePicker 后 attachments 清空**
- [ ] 码农页：以上行为一致（共用 InputBox）
- [ ] 后端：mock 一个 Ollama llama3.2-vision 模型发送 1 张图 → LLM 收到 `{type:"image", base64}` 标准块
- [ ] 后端：mock 一个 OpenAI gpt-4o-mini 发送 1 张图 → LLM 收到转换后的图像块
- [ ] **后端：WS 帧引用不存在的附件 id → 错误帧 `missing_attachment_ids`，且不开始新一轮生成**
- [ ] **后端：纯图片无文字的 WS 帧通过验证（Empty message 守卫放宽）**
- [ ] 前端单测：`pnpm test` 全绿；视觉快照：流式 + 2 张图快照稳定
- [ ] 后端单测：`pytest tests/test_api/test_attachments.py tests/test_api/test_websocket_attachments.py` 全绿
- [ ] **既有 thumbelina.db 直接启动：ensure_schema 自动补 `messages.attachments` 列、create_all 建 `attachments` 表，旧消息附件显示为空**
- [ ] 无新增前端依赖；无新增 Python 第三方依赖
- [ ] `pnpm typecheck` 与 `mypy` 全绿

---

## 10. 任务排期建议（依赖顺序）

```
B1 schema 演进（ensure_schema）─┐
                     ├─► B3 WS 协议 ─► B4 Agent 多模态 ─► B5 块构建工具 ─► B6 测试
B2 上传端点 ──────────┘                                          ▲
                                                                 │
F1 类型 ─► F2 API 客户端 ─► F3 InputBox/MessageList ─► F4 拖放 ─► F5 Lightbox ─► F6 CSS ─► F7 i18n ─► F8 测试
                                                                 │
                                                          集成联调 ◄┘
```

**调整后排期**：
- 后端 6 个子任务 1 人 3 天（provider 层零改动，无软删 GC / 秒传，工作量较 v1.1 回落）
- 前端 8 个子任务 1 人 4 天（F4 拖放覆盖层单列 1 天；F5 Lightbox 为新建遮罩组件）
- 集成联调 + 视觉回归（明/暗主题双快照）1.5 天

总估算：**8.5 工作日 / 2 人**。

---

## 附录 A：消息结构最终态（TS）

```typescript
export interface AttachmentRef {
  id: string                       // server-assigned, att_xxx
  mime: 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif'
  width?: number
  height?: number
  alt?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  attachments?: AttachmentRef[]    // user role only, first version
  toolCalls?: ToolCall[]
  thinking?: string
}

export interface SendAttachmentInput {
  id: string
  alt?: string
}

export interface ChatRequest {
  message: string
  conversation_id?: string
  attachments?: SendAttachmentInput[]
}
```

## 附录 B：本地附件状态机（前端）

```
idle ──drop / pick──► uploading ──ok──► ready ──send──► (consumed)
                          │ ▲              │
                          ▼ │ retry        ▼ remove
                       failed ─────────► idle
                                        │
                            (流式中新增/删除) ──► pending ──下一轮 send──► (consumed)
```

**新增 `pending` 状态**：流式回复进行中时，attachments 操作不立即发送，仅打 `pending` 标记；下一轮发送时与新文字合并后清空 pending。