# Web 前端状态栏能力设计与任务拆解

- **日期**：2026-08-19
- **状态**：设计中（待评审）
- **分支**：待定（建议 `feat/statusbar`）
- **文档**：设计 + 任务拆解（本文件）

## 1. 需求概述

为 Thumbelina Web 前端新增一个**全局状态栏**（底部横条），满足三个诉求：

1. **各栏目可配置展示**：用户可决定状态栏里展示哪些栏目（如只想要「连接状态 + 当前模型」，不想要「记忆条目数」「插件数」）。
2. **数据不依赖 LLM 调用**：状态栏所有信息必须通过**本地函数 / REST 只读端点**获得，绝不因展示状态而触发额外的大模型请求。
3. **内容对齐主流 Agent**：调研当下主流 AI Agent / IDE 状态栏（Claude Code、Cursor、VS Code、Copilot 等）展示什么，评估哪些适合本项目这种「自托管个人 AI 助手 + 通道型（QQ/微信）」的产品形态。

设计回答：**状态栏放哪、展示哪些栏目、各栏目数据从哪来、如何实现「可配置展示」**，并给出完整任务拆解。

---

## 2. 现状调研

### 2.1 前端现状（已确认）

- **布局**：`frontend/src/App.tsx` 为 `App` → `.app`（flex column）→ `Header`（顶部导航）+ `.app-body`（`.app-body` 为 `flex:1`）。**当前没有任何全局状态栏 / footer。**
- **Header**：`frontend/src/components/Layout/Header.tsx`，顶部导航条 + `ThemeToggle`，无任何连接/状态信息。
- **hooks**：仅两个。
  - `useWebSocket.ts`：维护 `isConnected` / `isStreaming` / `streamingMode` / `waitingForReply` —— 但**在 `ChatWindow` 内部使用**，是单实例局部状态。
  - `useUploadTasks.ts`：知识库上传任务轮询。
- **api 客户端**：`conversations.ts` / `llmConfig.ts` / `rag.ts` / `todo.ts`，各自定义 `const API_BASE='/api/v1'` + `request<T>()`。**无统一状态聚合客户端。**
- **设计令牌**：`frontend/src/index.css`（token）+ `frontend/src/styles/themes.css`（dark/light/warm 三主题）。
  - 状态色齐备：`--success`（绿）、`--warning`（黄）、`--error`（红），各带 `--*-muted`。
  - 主题主色 teal（`--accent`）+ 次色 orange（`--accent-secondary`）。
  - 字号 `--fs-xs:11px`、间距 `--sp-*`、图标 `--icon-*`（`--icon-sm:14px`）均适合状态栏尺寸。
  - 类名建议走 BEM（`.statusbar__item--*`）避免与 App.css 既有短类名（`.header` 等）冲突。
- **i18n**：`LocaleContext`，`en`/`zh-CN` 两个字典，点路径取值 + `{var}` 插值。**目前无 `statusBar` 命名空间。**
- **持久化先例**：主题（`ThemeToggle`）、语言（`LocaleContext`）均用 `localStorage` 持久化 —— 状态栏栏目开关的配置沿用 localStorage 即可。

### 2.2 后端现状（低成本、非 LLM 数据源，均已确认存在）

| 端点 | 返回 | 成本 | 适合栏目 |
|---|---|---|---|
| `GET /health` | `{status, version, database}`（`app.py:777`，DB ping） | 极轻 | 后端连接 / 版本 |
| `GET /config` | `{provider, model, base_url, api_key_set, auth_enabled, rate_limit_enabled, streaming_enabled, channels{qq,wechat}}`（`config.py:133`） | 读内存 | 当前模型 / 流式开关 |
| `GET /memory/status` | `{enabled, directory, entries}`（`memory.py:80`，始终 200） | 读内存 | 记忆条目数 |
| `GET /todo/status` | `{enabled}`（`todo.py:107`） | 读内存 | Todo 功能开关 |
| `GET /tasks` | `[{id, description, scheduled_time, status}]`（`tasks.py:46`） | 读内存 | 定时任务数 |
| `GET /subagents` | `[{id, task, status, result}]`（`tasks.py:13`） | 读内存 | 运行中子代理 |
| `GET /qq/status` | QQ 通道状态（`qq.py:18`） | 读内存 | QQ 在线 |
| `GET /wechat/status` | iLink 连接状态（`wechat.py:111`） | 读内存 | 微信在线 |
| `GET /plugins` | 插件列表（`plugins.py:20`） | 读内存 | 插件计数 |
| `GET /config/llm/endpoints` | 端点列表（含 `is_reachable` / `last_latency_ms`）（`config.py:487`） | 读内存 + 缓存 | 模型端点状态 |

关键结论：**本项目几乎所有状态栏要展示的数据都已有现成只读端点，且全是内存/DB 读取，零 LLM 调用。** 这正好满足需求 2。

---

## 3. 主流 Agent 状态栏调研与取舍评估

### 3.1 主流产品常见内容

| 项 | Claude Code / Cursor / VS Code / Copilot 惯例 | 是否依赖 LLM |
|---|---|---|
| 当前模型 / provider / endpoint | 常驻展示名字 + 状态徽标 | 仅「在线真值」需真实请求 |
| 连接状态（WS / 后端） | 小圆点 已连/离线/重连 —— 状态栏「地基」 | 否 |
| 运行中任务 / 子代理计数 | spinner + 计数 | 否 |
| 记忆系统条目 / 预算占用 | 多在侧栏按需看，少常驻 | 否 |
| 渠道在线（QQ/微信） | 图标绿/灰 + 重登态 | 否 |
| context 占用 % | 近上限才高亮 | 估算即可 |
| 插件/技能计数 | 常驻偏「仪表盘自恋」 | 否 |
| 精确 token 用量 / 成本 | 不常驻，放用量面板 | 半（随响应附带） |
| CPU/内存/延迟 | 常驻是噪音，仅异常告警 | 否（psutil） |
| 版本号 | 右下角静态文本 | 否 |

### 3.2 对本项目（自托管个人 + 通道型）的推荐优先级

| 优先级 | 栏目 | 理由 | 数据源 | 依赖 LLM |
|---|---|---|---|---|
| **P0 必做** | 连接状态（WS + 后端/DB） | 自托管部署一眼看出掉线 | `useWebSocket.isConnected` + `/health` | 否 |
| **P0 必做** | 渠道状态（QQ/微信） | 通道型助手核心健康面，微信要扫码重登 | `/qq/status`、`/wechat/status` | 否 |
| **P0 必做** | 当前 LLM 模型 + 热切换 | 自托管第一诉求，`swap_llm_provider` 已成熟 | `/config` + `/config/llm/*` | 仅在线真值 |
| **P1 推荐** | 运行中任务 / 子代理计数 | 后台活动高信号 | `/tasks`、`/subagents` | 否 |
| **P1 推荐** | 记忆条目数 + 阈值占用 | 项目核心特色，接近 guardrail 才告警 | `/memory/status` | 否 |
| P2 可折叠 | context 占用 % | 复用 `estimate_tokens` 本地估算 | 前端本地算 | 否 |
| P2 抽屉 | 成本估算 / 精确 token 用量 | 不常驻 | 需改 `LLMProvider.stream()` 透出 usage | 半 |
| P3 图标 | 插件 / 技能计数 | 静态度量 | `/plugins`、`/skills/stats` | 否 |
| P3 角落 | 版本号 / 环境 | 惯例 | `/health.version` | 否 |

**取舍结论**：
- **落为常驻状态栏栏目**：连接状态、渠道状态、当前模型、运行中任务数 —— 这些都是「有状态变化就有意义」的高信号。
- **降级为折叠/抽屉**：记忆条目数、context 占用、插件数。
- **不进入状态栏主区**：实时成本、CPU/内存数字、每字符 token 仪表盘 —— 高噪音，且成本估算需要维护定价表或透出 usage。

---

## 4. 总体架构

```
frontend/src
├── components/StatusBar/
│   ├── StatusBar.tsx              # 状态栏容器（聚合各栏目、渲染开关过滤）
│   ├── StatusBarItem.tsx          # 单个栏目通用外壳（图标 + 文本 + tooltip + 状态点）
│   ├── StatusBarSettings.tsx      # 「⚙ 自定义」面板（勾选展示哪些栏目，localStorage 持久化）
│   ├── items/
│   │   ├── ConnectionItem.tsx     # 连接状态（WS + DB）
│   │   ├── ChannelItem.tsx        # QQ/微信 渠道
│   │   ├── ModelItem.tsx          # 当前 LLM + 热切换下拉
│   │   ├── ActiveItem.tsx         # 运行中任务/子代理计数
│   │   ├── MemoryItem.tsx         # 记忆条目数（折叠区）
│   │   ├── ContextItem.tsx        # context 占用 %（折叠区）
│   │   └── VersionItem.tsx        # 版本号（右下角）
│   └── StatusBar.test.tsx
├── hooks/
│   └── useStatusData.ts           # 聚合拉取状态数据（轮询 /health /config /tasks /subagents /memory/status /channels）
├── hooks/
│   └── useStatusBarConfig.ts      # 栏目展示开关（localStorage 读写 + context）
├── context/
│   └── StatusBarContext.ts(x)     # 全局状态栏上下文（把 useWebSocket.isConnected 提升到 App 层供状态栏用）
├── api/
│   └── status.ts                  # 状态聚合 API 客户端（复用 request<T> 模式）
└── i18n/locales/{en,zh-CN}.json   # 新增 statusBar 命名空间
```

### 布局位置

`.app` 已是 flex column：`Header` + `.app-body`。状态栏作为 `.app-body` 之后的第三个 flex 子项（`flex-shrink:0`），即在页面**底部**恒定一条，横跨所有页面（chat / tasks / todo / memory / ... 均显示）。

```tsx
<div className="app">
  <Header ... />
  <div className="app-body">{renderPage()}</div>
  <StatusBar />          {/* 新增 */}
</div>
```

---

## 5. 详细设计

### 5.1 栏目清单与数据获取（需求 2 的核心）

| 栏目 key | 展示 | 数据获取 | 刷新方式 | 是否 LLM |
|---|---|---|---|---|
| `connection` | 圆点 + 「已连接/离线」 + DB ok/error | `useWebSocket.isConnected`（提升到 App）+ `GET /health` | WS 事件驱动 + 30s 轮询 `/health` | 否 |
| `channels` | QQ/微信各一图标（绿=在线，灰=关闭，微信黄=需扫码） | `GET /qq/status`、`GET /wechat/status` | 30s 轮询 | 否 |
| `model` | `provider/model` 名称 + 端点状态徽标 + 点击展开热切换列表 | `GET /config` + `GET /config/llm/endpoints`（含 `is_reachable`） | 30s 轮询 + 切换后立即刷新 | 仅在线真值按需 |
| `active` | 「N 运行中」+ spinner + 点击看明细 | `GET /tasks`（RUNNING 计数）+ `GET /subagents`（RUNNING 计数） | 30s 轮询 | 否 |
| `memory` | 「记忆 N 条」+ 接近阈值时高亮 | `GET /memory/status` | 30s 轮询 | 否 |
| `context` | 「context x%」 | 前端用 `estimate_tokens` 对当前会话消息估算 | 本地计算 + WS 消息更新时 | 否（估算） |
| `version` | `v0.1.0` | `GET /health.version` | 一次性 | 否 |

**「不依赖 LLM」约束落地**：
- 所有栏目只读 `GET` 端点或本地 hook，**不触发任何模型调用**。
- `model` 栏的「在线/离线」真值来自 `endpoints.is_reachable`（后端缓存的值），**不做前端主动 test-connection 轮询**；需要时用户点击才触发。
- `context` 用 `estimate_tokens` 本地估算（CJK 2token/字），不为此调用 provider。

### 5.2 可配置展示（需求 1 的核心）

- **配置项**：`Record<StatusBarItemKey, boolean>`，如 `{ connection: true, channels: true, model: true, active: true, memory: false, context: false, version: true }`。
- **存储**：`localStorage`，键 `thumbelina-statusbar-items`（沿用 ThemeToggle / LocaleContext 的既有 `thumbelina-*` 命名先例）。
- **默认值**：P0 项默认开，P1/P2 项默认开但标为「可折叠」，P3 项默认关。
- **交互**：状态栏右侧一个「⚙」按钮打开 `StatusBarSettings` 面板（或复用下拉气泡），每个栏目一个 checkbox/switch，改动即时生效并写 localStorage。
- **实现**：`useStatusBarConfig` hook 提供 `{ visible: Record<key, boolean>, toggle(key) }`；`StatusBar` 根据 `visible` 过滤渲染栏目。

### 5.3 连接状态提升（关键前置改动）

`useWebSocket` 目前在 `ChatWindow` 内部，状态栏需要全局 `isConnected`。两种方案：

- **方案 A（推荐）**：在 `App.tsx`（或独立 `StatusBarContext`）持有 WebSocket 连接，把 `isConnected` / `isStreaming` 通过 `StatusBarContext` 提供给 `ChatWindow`（现有逻辑）与 `StatusBar`。**改动最小、单一连接**。
- 方案 B：状态栏另建一条独立 WS —— 重复连接、浪费，不采用。

采用**方案 A**：新建 `context/StatusBarContext.ts(x)`，内部可复用/迁移 `useWebSocket` 的 `isConnected` 信号，或将现有 `useWebSocket` 提升到 App 并通过 context 下发。**注意**：`useWebSocket` 依赖 `activeConversationId` 与 `sendMessage` 等交互，直接整体上提会扩大改动面；更稳妥的是**新增一个轻量只读连接 hook**（只监听 `isConnected`，可复用同一地址），或从现有 `useWebSocket` 拆出连接状态。任务拆解中会给出最小改动路径。

### 5.4 设计令牌与样式

- 新增类名：`.statusbar`、`.statusbar__item`、`.statusbar__item--connected/--offline/--warning`、`.statusbar__left`/`__right`、`.statusbar__settings`。
- 复用：`--fs-xs`、`--sp-2`/`--sp-3`、`--icon-sm`、`--success`/`--warning`/`--error`(及其 `-muted`)、`--bg-surface`、`--border`、`--text-secondary`。
- 高度：新增 token `--statusbar-height: 26px`（放入 `index.css`），状态栏与 header 一致 `flex-shrink:0` + 顶边框 `border-top`。
- 图标：lucide-react —— `Wifi`/`WifiOff`、`Radio`、`Bot`/`Sparkles`、`Loader`、`Database`、`Gauge`、`Settings2` 等。

### 5.5 i18n

新增 `statusBar` 命名空间（en + zh-CN 镜像一致）：

```jsonc
"statusBar": {
  "connected": "Connected",
  "disconnected": "Offline",
  "streaming": "Generating…",
  "model": "Model",
  "channels": "Channels",
  "active": "Active",
  "memory": "Memory",
  "context": "Context",
  "version": "Version",
  "openSettings": "Customize status bar"
}
```

---

## 6. 非目标（明确不做）

- **不**做实时成本估算 / 精确 token 仪表盘常驻（属高噪音，且需改 `LLMProvider` 透出 usage 或用定价表）。
- **不**用状态栏展示 CPU/内存等系统资源数字（仅做异常告警的后续项，本轮不做）。
- **不**新增后端聚合端点（`GET /api/v1/status`）作为首轮 —— 首轮前端并行拉现有端点即可，避免后端改动；若后续需要降请求数再做聚合（见 §7 任务 19 可选）。
- **不**为状态栏新增独立 WebSocket 连接。

---

## 7. 任务拆解

按可独立提交、每步可验证拆解。

### 阶段一：数据层与配置（前端）

1. **新增 `api/status.ts`**：`request<T>()` 模式，提供 `fetchHealth()`、`fetchConfig()`、`fetchTaskCount()`、`fetchSubagentCount()`、`fetchMemoryStatus()`、`fetchChannelStatuses()`（内部并行调 `/qq/status`+`/wechat/status`，各自容错）。为每个函数补单测（mock fetch）。
2. **新增 `hooks/useStatusData.ts`**：基于 `setInterval`（默认 30s）并行轮询上述端点，返回 `{ connection, channels, model, active, memory, version }` 聚合状态对象；含「组件卸载清理定时器」「fetch 失败时保留上次值 + 标记离线」逻辑。补单测。
3. **新增 `hooks/useStatusBarConfig.ts`**：读/写 `localStorage` 键 `thumbelina-statusbar-items`，提供 `visible` + `toggle(key)` + 默认值表（P0/P1 默认 true，P3 默认 false）。补单测。

### 阶段二：连接状态提升（前置）

4. **新建 `context/StatusBarContext.ts(x)`**：暴露 `isConnected`（源自 WebSocket）。实现最小改动路径 —— 复用/迁移现有 `useWebSocket` 的连接信号到 App 层，或新增轻量只读 WS hook。确保 `StatusBar` 与 `ChatWindow` 读到同一 `isConnected`。
5. **更新 `App.tsx`**：挂载 `StatusBarProvider`，导入 `<StatusBar />`，调整 `.app` 渲染顺序。

### 阶段三：状态栏 UI 组件

6. **新增 `components/StatusBar/StatusBar.tsx`**：布局容器（`.statusbar__left` + `.statusbar__right`），按 `visible` 过滤渲染各栏目，右侧渲染「⚙」设置按钮与版本号。补 RTL 单测（渲染/过滤/交互）。
7. **新增 `StatusBarItem.tsx`**：通用外壳（图标 + 文本 + tooltip + 状态点），接收 `state: 'connected'|'offline'|'warning'`。
8. **新增 `items/ConnectionItem.tsx`**：WS 圆点 + `/health` DB 状态（`status:ok+db:ok` → 绿；否则红），点击 tooltip 显示 DB 详情。
9. **新增 `items/ChannelItem.tsx`**：遍历 `channels.qq`/`wechat`（来自 `/config.channels`），按 `/qq/status`、`/wechat/status` 点亮绿/灰/黄（微信需扫码重登中间态）。
10. **新增 `items/ModelItem.tsx`**：显示 `provider/model`；点击展开下拉列出 endpoints（含 `is_reachable` 徽标），选中即调 `activateEndpointModel` 完成热切换并刷新。复用「设置/EndpointManager」的既有能力，本组件只做展示 + 轻量切换入口，**不做**完整测试（复用 `llmConfig.ts`）。
11. **新增 `items/ActiveItem.tsx`**：`tasks`+`subagents` 的 RUNNING 数合计，>0 时显示 spinner + 「N 运行中」，点击打开明细（可导航到 Tasks 页或 tooltip 列表）。
12. **新增 `items/MemoryItem.tsx`**：`memory.entries` 条数，接近 guardrail（若 `memory.status` 扩展返回，或前端常量阈值）时高亮为 warning。默认放入折叠区。
13. **新增 `items/ContextItem.tsx`**：本地 `estimate_tokens`（此处可在前端实现一个简易估算，或前端已有则复用）对当前会话消息估算 context 占用 %，>70% 高亮。默认放入折叠区。
14. **新增 `items/VersionItem.tsx`**：`v0.1.0`（`health.version`），左下角/右下角静态文本。

### 阶段四：配置面板与样式

15. **新增 `components/StatusBar/StatusBarSettings.tsx`**：「⚙ 自定义」下拉/弹层，列出所有栏目 + checkbox/switch，绑定 `useStatusBarConfig.toggle`，改动即时生效写 localStorage。
16. **样式**：`App.css`（或独立 `statusbar.css`）新增 `.statusbar*` BEM 类；`index.css` 新增 `--statusbar-height: 26px`；三主题下验证 `--success/-warning/-error` 的对比度。
17. **i18n**：`en.json` + `zh-CN.json` 新增 `statusBar` 命名空间（§5.5）。

### 阶段五：测试与收尾

18. **测试补齐**：`StatusBar.test.tsx`（渲染/开关过滤/交互）、`useStatusData`、`useStatusBarConfig`、`api/status` 单测；`npm run test`、`npm run lint`、`npm run build` 全绿。
19. **（可选，后端聚合端点）** 若首轮前端拉取端点过多（约 7 次轮询 × 30s），可后续新增 `GET /api/v1/status` 一次性聚合返回（后端再评估）；本轮不做，作为后续项。
20. **文档同步**：按项目惯例，功能落地后检查是否需同步更新 `README.md` / `README_CN.md`（新增「状态栏能力」说明）与 `CLAUDE.md`（前端结构描述）。

### 里程碑对照

| 阶段 | 提交粒度 | 验证 |
|---|---|---|
| 一 | `feat(statusbar): status 数据层与配置` | 单测通过，`npm run build` |
| 二 | `feat(statusbar): 提升连接状态到全局` | ChatWindow 行为不变，状态栏读到 isConnected |
| 三 | `feat(statusbar): 状态栏 UI 组件` | 各栏目正常渲染与刷新 |
| 四 | `feat(statusbar): 配置面板 + 样式 + i18n` | 开关过滤生效，主题下可见 |
| 五 | `test(statusbar): 补测试 + 收尾` | `npm run test/lint/build` 全绿 |

---

## 8. 风险与权衡

- **连接状态提升改动面**：方案 A 需动 `App.tsx` 与 `useWebSocket` 归属。为控风险，首轮用「新增轻量只读 WS hook」承载 `isConnected`，**不动**现有 `ChatWindow` 的 `useWebSocket`，避免回归。
- **轮询频率**：30s 轮询 7 个端点对个人自托管可接受；若在意，可在页面聚焦才轮询 / `visibilitychange` 暂停（后续优化项）。
- **model 在线真值**：不主动轮询 `test-connection`（会触发真实请求），只用 `endpoints.is_reachable` 缓存值；如需更实时，后端需提供缓存刷新端点（后续项）。
- **context 估算准确性**：`estimate_tokens` 是近似值，仅用于展示百分比，不作精确计费依据。
