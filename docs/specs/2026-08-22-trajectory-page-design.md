# WEB“轨迹”页面设计文档

- 日期：2026-08-22
- 状态：已批准
- 范围：前端（导航/轨迹页/聊天页入口）+ 后端（事件落盘 + 轨迹 API）

## 1. 背景与目标

WEB 新增“轨迹”页面，用于审计历史对话记录。按对话轮次分组、时间倒序展示：用户消息、助手响应、工具调用请求、工具调用结果、上下文注入内容。

需求要点：

1. 顶部导航新增“轨迹”入口。
2. 支持按对话 session（会话名称选择）过滤，单次仅支持一个 session；默认不过滤、不展示轨迹。
3. 轨迹按轮次分组、时间倒序，展示用户消息、助手响应、工具调用请求、工具调用结果、上下文。
4. 聊天页顶部（与流式开关、模型配置同级）新增“查看轨迹”入口，跳转轨迹页并过滤当前 session。

## 2. 现状与关键决策

现状调查结论：

- `messages` 表仅持久化 user/assistant 纯文本（`agent/graph.py` `_persist_message`）。
- 工具调用请求/结果、上下文注入内容仅存在于 LangGraph checkpoint（会被压缩/清空，不适合审计）。
- 数据库无轮次（turn）概念，仅按 `created_at` 排序。
- 前端无 react-router，`App.tsx` 以 `activePage` 切页；导航定义在 `components/Layout/Header.tsx`；聊天页工具条在 `components/Chat/ChatWindow.tsx` `.chat-status`；当前会话 ID 为 `App.tsx` 的 `selectedId`。

已确认决策：

| 决策点 | 结论 |
|---|---|
| 数据来源 | 落盘新数据（不依赖 checkpoint） |
| 数据模型 | 方案 A：独立事件流表 `trajectory_events`，与 `messages` 解耦 |
| 上下文粒度 | 记录全部注入内容（角色提示词、记忆、RAG、技能等） |
| 旧会话兼容 | 展示已有 user/assistant 消息（`legacy` 合成轮次），标注无工具/上下文记录 |
| 加载策略 | 按轮次分页（页大小 20），轮次间时间倒序 |
| 空状态文案 | “请选择要查看的会话” |

## 3. 数据模型与后端写入

### 3.1 新表 `trajectory_events`

加入 `src/thumbelina/repository/models.py`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String(36) PK | UUID |
| `conversation_id` | String(36) FK→conversations, CASCADE | 所属会话 |
| `turn_id` | String(36), 索引 | 轮次标识（同一轮所有事件共享） |
| `seq` | Integer | 轮次内序号（0 起），保证回放顺序 |
| `event_type` | String(20) | `user` / `context` / `tool_call` / `tool_result` / `assistant` |
| `payload` | Text(JSON) | 事件内容（见下） |
| `created_at` | DateTime | 写入时间 |

### 3.2 轮次定义

一条用户消息开启一个轮次（生成新 `turn_id`），到该次助手最终响应结束；期间所有工具调用对共享同一 `turn_id`。

### 3.3 payload 结构

- `user` / `assistant`：`{"content": str, "reasoning": str|null}`
- `context`：`{"items": [{"kind": "role_prompt|memory|rag|skill|...", "content": str}]}`
- `tool_call`：`{"tool": str, "args": {...}, "call_id": str}`
- `tool_result`：`{"call_id": str, "content": str, "is_error": bool}`

### 3.4 写入点

`agent/graph.py` 新增 `TrajectoryRecorder`，在现有 `_persist_message` 旁挂接：

- 用户消息落盘时：开启轮次 + 写 `user` 事件
- 上下文构建处（graph.py L930-954）：写 `context` 事件
- 工具节点执行前后：写 `tool_call` / `tool_result` 事件
- 助手最终响应处：写 `assistant` 事件

### 3.5 护栏与容错

- 写入失败仅记 `warning` 日志，绝不中断对话主流程。
- payload 序列化失败时写降级事件 `{"error": "serialize_failed"}`，保证轮次结构完整。
- 单条 `payload` 超 64KB 截断并标记 `truncated: true`。
- `messages` 表与现有写入链路保持不变（聊天页零影响）。

## 4. 后端 API

新增 `src/thumbelina/api/routes/trajectory.py`，前缀 `/api/v1/trajectory`，复用现有鉴权/限流模式（与 `conversations.py` 一致）。

### 4.1 `GET /trajectory/{conversation_id}?page=1&page_size=20`

按轮次分页、轮次间时间倒序（最新轮次在前）；轮次内事件按 `seq` 正序。

响应结构：

```json
{
  "conversation_id": "...",
  "conversation_name": "...",
  "total_turns": 57,
  "page": 1,
  "page_size": 20,
  "turns": [
    {
      "turn_id": "...",
      "started_at": "2026-08-22T10:03:11",
      "legacy": false,
      "events": [
        {"seq": 0, "event_type": "user", "payload": {}, "created_at": "..."},
        {"seq": 1, "event_type": "context", "payload": {}, "created_at": "..."},
        {"seq": 2, "event_type": "tool_call", "payload": {}, "created_at": "..."}
      ]
    }
  ]
}
```

### 4.2 旧会话兼容（legacy 回退）

若会话无 `trajectory_events` 记录，API 从 `messages` 表按时间序合成轮次：每条 `user` 消息开启一个轮次，其后的 `assistant` 消息归入同一轮次；事件仅 `user`/`assistant` 两类，`legacy: true`。

### 4.3 其他约定

- 会话选择器复用现有 `GET /api/v1/conversations`，不新增列表端点。
- 分页实现：先 `SELECT DISTINCT turn_id ... ORDER BY min(created_at) DESC LIMIT/OFFSET`，再按页内 `turn_id` 批量取事件。
- `conversation_id` 不存在 → 404；`page<1` 或 `page_size` 超 1–100 → 422。

## 5. 前端设计

### 5.1 导航入口

`Header.tsx` 4 处修改：`Page` 类型、`navKeys`、`NAV_ICONS`（`Footprints` 或 `Route` 图标）、`NAV_I18N` 新增 `trajectory`；`zh-CN.json` / `en.json` 增加 `nav.trajectory`（“轨迹”/“Trajectory”）及 `trajectory.*` 文案段。

### 5.2 轨迹页

新建 `components/Trajectory/TrajectoryPage.tsx` + `api/trajectory.ts`：

- 顶部：会话选择器（下拉，数据来自 `GET /conversations`，按更新时间倒序，显示会话名称）。默认不选中 → 空状态提示“请选择要查看的会话”，不请求轨迹数据；单选，切换会话即重置分页。
- 主体：轮次卡片列表，最新轮次在最上。每个轮次卡片：
  - 头部：轮次序号 + 开始时间
  - 事件按序渲染：用户消息、助手响应直接展示文本（带角色徽标）；`context`、`tool_call`、`tool_result` 默认折叠，点击展开（等宽代码块，超长滚动）；工具结果错误标红。
  - `legacy: true` 轮次显示提示“旧记录：无工具调用/上下文数据”。
- 分页：底部“加载更多”按钮（追加下一页轮次），页大小 20。
- 错误处理：请求失败显示错误提示 + 重试按钮；404 → 清空选择并提示“会话不存在”；`page` 超出总页数 → 隐藏“加载更多”。

### 5.3 聊天页跳转入口

`ChatWindow.tsx` `.chat-status` 工具条（与流式开关、模型选择器同级）新增“查看轨迹”按钮；通过新增回调 prop `onViewTrajectory` 上报 `App.tsx`，`App.tsx` 记录 `trajectorySessionId = selectedId` 并切换 `activePage = 'trajectory'`，作为初始过滤值传给 `TrajectoryPage`（页内切换选择器不受影响）。

### 5.4 状态说明

项目无 react-router，跳转即“切页 + 传初始会话 ID”；轨迹页内部自持过滤与分页状态。

## 6. 测试策略

后端单测（pytest，沿用现有结构）：

- `TrajectoryRecorder`：轮次开启 / 事件顺序 / 截断护栏 / 写入失败不抛异常
- `trajectory` 路由：分页倒序、`legacy` 回退合成、404/422 分支

前端单测（Vitest，沿用 `MemoryViewer.test.tsx` 模式）：

- `TrajectoryPage`：默认空状态、选择会话后加载、事件折叠展开、“加载更多”分页、错误重试
- `Header` / `ChatWindow`：新入口渲染与点击回调

手工验证：

- 发起一轮含工具调用的对话 → 轨迹页核对轮次内事件完整性与倒序
- 旧会话验证 `legacy` 提示
- 从聊天页“查看轨迹”跳转并自动过滤当前会话

## 7. 任务拆解

依赖关系：T1 → T2 → T3 → T4；T5/T6 可在 T3 完成后并行；T7 依赖 T4+T5+T6。

| # | 任务 | 内容 | 涉及文件 | 验收标准 |
|---|---|---|---|---|
| T1 | 数据模型与迁移 | 新增 `TrajectoryEvent` model（§3.1），建表 | `repository/models.py` | 表结构符合 §3.1；单测通过 |
| T2 | TrajectoryRecorder | 实现记录器（开轮次/事件写入/截断护栏/容错降级），挂接 `graph.py` 四个写入点 | `agent/graph.py`、新 `agent/trajectory.py` | §3.4/§3.5 行为；单测通过；真实对话落盘可见 |
| T3 | 轨迹 API | `GET /trajectory/{conversation_id}`（分页倒序 + legacy 回退 + 404/422） | 新 `api/routes/trajectory.py`、schema | §4 契约；路由单测通过 |
| T4 | API 测试 | 路由单测补全（分页/倒序/legacy/错误分支） | `tests/` | 全绿 |
| T5 | 轨迹页组件 | `TrajectoryPage.tsx` + `api/trajectory.ts`（选择器/轮次卡片/折叠/加载更多/空态/错误态）+ 单测 | 新 `components/Trajectory/`、`api/` | §5.2 行为；Vitest 通过 |
| T6 | 导航与跳转入口 | `Header.tsx` 新标签、`App.tsx` 切页 + `trajectorySessionId`、`ChatWindow.tsx` “查看轨迹”按钮、i18n 两语言 | `Header.tsx`、`App.tsx`、`ChatWindow.tsx`、locale 文件 | §5.1/§5.3；点击跳转并自动过滤当前会话 |
| T7 | 集成验证 | 手工验证清单（§6）+ 修复发现的问题 | 全部 | 手工验证项全部通过 |
