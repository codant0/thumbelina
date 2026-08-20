# Web 前端状态栏能力设计与任务拆解（修订版）

- **日期**：2026-08-19
- **状态**：已实现（阶段一–四完成；`lib/estimateTokens` + `StatusBar` 容器/外壳协议 + `ContextUsageItem` 接线到 `ChatWindow`）。
- **分支**：待定（建议 `feat/statusbar`）
- **文档**：设计 + 任务拆解（本文件）—— 修订版，据评审反馈收缩范围

> **修订说明**：初版规划了完整状态栏（连接/渠道/模型/任务等 7 个栏目）。评审后收缩为：
> - 经评估，**仅「上下文占用」有实际价值**，其余栏目价值不高，均不实现。
> - 交付物收敛为 **① 抽象接口（栏目协议）② 上下文栏目实现**。
> - 上下文栏目**只做展示，不影响对话**。
> - 布局不另起底部横条，而是与现有「思考模式 / 默认角色 / 知识库」**同一行、展示在右侧**。

---

## 1. 需求概述

为 Thumbelina Web 前端新增「状态栏能力」，本次交付：

1. **抽象接口**：定义一种统一的「状态栏栏目」协议，使未来新增栏目只需实现该协议即可被点到这一行上，无需改动状态栏容器。
2. **上下文能力**：实现其中的第一个栏目 —— 当前对话上下文的 token 占用估算。
3. **只做展示、不影响对话**：上下文指标**纯前端展示**，不注入任何 prompt、不改写发往 LLM 的输入、不参与会话流。
4. **数据不依赖 LLM**：上下文估算基于**本地函数**对前端已持有的会话消息做 token 估算，不触发任何模型调用。
5. **位置**：与「思考模式 / 默认角色 / 知识库」保持在**同一行（`input-toolbar`）、展示在右侧**。

---

## 2. 现状与约束（已确认）

- **同一行载体**：`frontend/src/components/Chat/InputBox.tsx` 的 `toolbar` prop，渲染在 `.input-toolbar`（`display:flex; align-items:center; gap: var(--sp-2)`，`App.css:3032`）。`ChatWindow.tsx:171-198` 依次传入 `ThinkingSelector`（思考模式）、`RoleSelector`（默认角色）、`KnowledgeBaseSelector`（知识库）。
- **新增栏目放右侧**：即作为 `ChatWindow` 传给 `InputBox.toolbar` 的最后一个元素。
- **上下文窗口上限来源**：`LLMEndpoint.context_window`（`api/llmConfig.ts:10`，字符串如 `128K`、`1M`，可回落全局 `llm.context_window`）。`Conversation` 本身**不含** `context_window`；需经 `fetchEndpoints()`（`ConversationModelSelector` 已在用）按当前会话 `endpoint_id` 匹配端点取其 `context_window`（未匹配则用默认/激活端点，缺省 →「未设置」）。
- **token 估算口径（须与后端一致）**：后端 `estimate_tokens`（`rag/retrieval/context_formatter.py:39`）：CJK 字符 ≈ 2 token/字，其余 ≈ 0.25 token/字符。整会话估算 `estimate_messages_tokens` 为对每条消息 `message_text` 求和（`agent/compression/base.py:58`）。
- **前端已持有消息**：`useWebSocket` 返回 `messages: Message[]`，`Message` 含 `role` + `content`，即估算所需的全部输入，无需额外请求。
- **设计令牌**：字号 `--fs-xs`、状态色 `--success/-warning/-error(及其 -muted)`、间距 `--sp-*`、图标 `--icon-sm` 均可用。
- **i18n**：`en`/`zh-CN` 两字典镜像，点路径取值;本次上下文栏目仅数值展示、无需新增命名空间。

---

## 3. 总体设计

### 3.1 抽象接口：栏目协议

定义统一栏目协议，让新增栏目只需「声明如何取到数据 + 如何渲染」，其余（展示、空态、tooltip、i18n）由容器统一处理。

```ts
// components/StatusBar/types.ts
/** 一个状态栏栏目。多个栏目可注册到同一行，由容器统一布局在右侧。 */
export interface StatusBarItem {
  /** 唯一 key（用于 i18n 与测试定位） */
  key: string
  /** 数据获取：纯函数，读取前端已有状态/本地端点，绝不触发 LLM 调用 */
  getData: () => Promise<StatusData> | StatusData
  /** 渲染主体（占用值 / 状态文本等） */
  render: (data: StatusData) => ReactNode
  /** 当前数据是否为「异常 / 警告」状态（决定是否高亮为 warning/error 色） */
  isAlert?: (data: StatusData) => boolean
}
```

容器 `StatusBar` 对每个已注册栏目统一处理：取数 → 组装外壳（图标 + 文本 + 状态点）→ 空态/错误态 → tooltip。**本次只实现 `context` 一个栏目；后续加栏目只须新增一个实现 `StatusBarItem` 的对象，并注册进容器**——这正是「抽象接口」的交付物。

### 3.2 上下文栏目：只展示、不影响对话

- **输入**：当前会话的 `messages`（来自 `useWebSocket`）+ context 窗口上限。
- **计算**（前端本地函数）：
  ```
  usedTokens = Σ estimate_tokens(msg.content)  // 与后端口径一致
  limit      = parseContextWindow(endpoint.context_window ?? 全局默认)
  pct        = usedTokens / limit
  ```
- **展示**：`x%`（如 `8%`）；> 某阈值（如 70，接近压缩阈值）时高亮为 `--warning`。
- **「只展示、不影响对话」保证**：该功能**不**修改 `sendMessage`、**不**注入系统消息、**不**改写发往后端的任何负载；仅由 `messages` state + 一个本地估算函数驱动 UI。可加一个显式注释/测试断言「无副作用」。

### 3.3 布局：与思考能力同行、右侧

在 `ChatWindow.tsx` 的 `InputBox.toolbar` 末尾追加 `<ContextUsageItem … />`（或由 `StatusBar` 对外暴露的对应组件），使其成为 `ThinkingSelector → RoleSelector → KnowledgeBaseSelector → ContextUsage` 序列的最后一项，天然落在 `.input-toolbar` 右侧，样式与三个既有 selector 保持一致的胶囊形触发按钮。

---

## 4. 详细设计

### 4.1 目录结构

```
frontend/src
├── components/StatusBar/
│   ├── types.ts                 # StatusBarItem 协议（抽象接口）
│   ├── StatusBar.tsx            # 容器：注册栏目、统一取数/外壳/空态/tooltip
│   ├── StatusBarItem.tsx        # 通用外壳（胶囊按钮 + 图标 + 文本 + 状态点 + tooltip）
│   ├── ContextUsageItem.tsx     # context 栏目：估算 + 展示（只读）
│   └── StatusBar.test.tsx
├── hooks/
│   └── useStatusBarConfig.ts    # 栏目展示开关（localStorage）；Settings 面板可切换 context 栏目
├── lib/
│   └── estimateTokens.ts        # 前端 token 估算（对齐后端 estimate_tokens）+ parseContextWindow
```
> i18n：上下文仅数值展示，无需新增 `statusBar` 命名空间（英文/中文共用既有文案）。

### 4.2 前端估算函数 `lib/estimateTokens.ts`

对齐后端 `estimate_tokens`（CJK≈2，其余≈0.25）：

```ts
// CJK 字符按约 2 token/字，其余按约 0.25 token/字符 —— 与后端
// rag/retrieval/context_formatter.estimate_tokens 口径保持一致。
export function estimateTokens(text: string): number {
  let cjk = 0
  for (const ch of text) if (/[⺀-鿿豈-﫿＀-￯　-〿]/.test(ch)) cjk++
  return Math.round(cjk * 2 + (text.length - cjk) * 0.25)
}

export function parseContextWindow(s?: string | null): number | null {
  if (!s) return null
  const m = /^(\d+)\s*([kKmM])?$/.exec(s.trim())
  if (!m) return null
  return parseInt(m[1], 10) * (m[2] && m[2].toLowerCase() === 'k' ? 1000 : m[2] ? 1000000 : 1)
}
```

### 4.3 上下文栏目组件

`ContextUsageItem` 接收 `{ conversationId, endpointId, messages }`，内部：
- `fetchEndpoints()` 解析 context 窗口上限（按 `endpointId` 匹配，缺省用默认/激活端点）;
- `useMemo` 对 `messages` 做 `estimateTokens(content)` 求和 → `usedTokens`；除以 `contextWindow` → `pct`。
- 渲染为胶囊按钮，右侧一行最后一个元素；`pct` 接近阈值（>60% warning、>85% error）时套 `.is-alert` 类变 `--warning/-error`。
- `title`/tooltip 显示 `usedTokens / limit`。
- **纯展示**：不持有状态、不触发网络、不改写对话流。

### 4.4 StatusBar 容器与协议

`StatusBar` 接收栏目注册列表（`StatusBarItem[]`），当前仅 `[contextItem]`。职责：
- 遍历调用 `getData()`（无依赖串行/并行均可），统一渲染 `StatusBarItem` 外壳；
- `isAlert()` 决定状态点颜色；
- `getData` 抛错时展示降级文案而非崩溃；
- 对外导出 `registerStatusItem(item)` / 或通过单一 `items` prop 注入，供未来加栏目。

> 因本版栏目数少，容器保持极简，**不引入过度抽象**：不做复杂插槽/插件注册运行时机制，仅「props 传入 items 数组 + 统一外壳」即满足「抽象接口」要求且可扩展。

### 4.5 接线（ChatWindow）

`ContextUsageItem` 通过 `fetchEndpoints()` 解析出当前会话的 context 窗口上限（按 `conversation.endpoint_id` 匹配，缺省用默认/激活端点），对 `messages` 估算占用：

```tsx
<InputBox
  onSend={handleSend}
  disabled={...}
  toolbar={conversationId ? (
    <>
      {onSetThinking && <ThinkingSelector … />}
      {onSetRole && <RoleSelector … />}
      {onSetKnowledgeBase && <KnowledgeBaseSelector … />}
      {/* 新增：上下文占用，展示在行尾（右侧） */}
      <ContextUsageItem
        conversationId={conversationId}
        endpointId={activeConversation?.endpoint_id ?? null}
        messages={messages}
      />
    </>
  ) : undefined}
/>
```

`ContextUsageItem` 内部：`fetchEndpoints()` → 取匹配端的 `context_window`（`parseContextWindow` 解析）→ 对 `messages` 求和估算 → 渲染 `x%`。

### 4.6 i18n

上下文栏目仅展示 **数值占比**（`x%`）/ 占位符（`—`），**无任何需要翻译的文案**，故本次**未新增 `statusBar` i18n 命名空间**（避免死 key）。若未来新增带文案的栏目再补。已接入的 WebSocket/选择器等文案沿用既有 `common.*` / `chat.*`。

---

## 5. 非目标（明确不做）

- **不做**连接状态、渠道、模型、任务、记忆等其他栏目（评审判定价值不高）。
- **不做**全局底部状态栏横条（改到 `input-toolbar` 行内右侧）。
- **不做**成本估算 / 精确 token 仪表盘。
- **不改后端**：不需要新端点；context 窗口上限走既有 `LayerConversation`/`ConversationModelSelector` 已带出的 context_window 字段。
- **上下文的展示不影响对话**：不改 `sendMessage` / 后端负载 / prompt 注入。

---

## 6. 任务拆解（按可独立提交拆）

### 阶段一：基础（估算函数 + 接口）
1. **新增 `lib/estimateTokens.ts`**：`estimateTokens` + `parseContextWindow`，与后端口径一致；补单测（CJK/英文/空串/`128K`/`1M` 解析）。
2. **新增 `components/StatusBar/types.ts`**：`StatusBarItem` 协议（`key/getData/render/isAlert?`）。仅类型，无逻辑。

### 阶段二：栏目外壳
3. **新增 `components/StatusBar/StatusBarItem.tsx`**：通用胶囊外壳（图标 + 文本 + 状态点 + tooltip + 空态/错误态）。
4. **新增 `components/StatusBar/StatusBar.tsx`**：容器，遍历 `items` 调 `getData` → 渲染外壳；错误降级。

### 阶段三：上下文栏目 + 布局
5. **新增 `components/StatusBar/ContextUsageItem.tsx`**：接收 `conversationId` + `endpointId` + `messages`，经 `fetchEndpoints()` 解析窗口上限、`useMemo` 估算 → 渲染 `x%`，阈值高亮。补 RTL 单测。
6. **接线 `ChatWindow.tsx`**：在 `InputBox.toolbar` 序列**末尾**追加 `ContextUsageItem`，处于 `.input-toolbar` 右侧；确认与思考/角色/知识库同行。**确认无对话副作用**（不碰 sendMessage）。

### 阶段四：样式 + 收尾
7. **i18n**：因上下文仅展示数值、无翻译文案，**跳过** `statusBar` 命名空间（避免死 key）。
8. **样式**：`.statusbar`（胶囊，`margin-left:auto` 定位到 `input-toolbar` 右侧）+ 状态点 `--ok/--warning/--error`；三主题下 `--success/-warning/-error` 令牌已验证。
9. **测试与收尾**：`estimateTokens`（9 例）、`StatusBar` 容器（4 例）、`ContextUsageItem`（6 例）共 19 项单测全绿；headless Chrome 实跑确认状态栏为 `input-toolbar` 行尾兄弟节点（thinking→role→kb→statusbar，展示 `—` 优雅降级）。`npm run test / lint / build` 全绿。

### 里程碑

| 阶段 | 提交 | 验证 |
|---|---|---|
| 一 | `feat(statusbar): token 估算与栏目协议` | 单测通过 |
| 二 | `feat(statusbar): 状态栏容器与外壳` | 组件渲染正常 |
| 三 | `feat(statusbar): 上下文占用显示（只读）` | 与思考/角色/知识库同行右侧；无对话副作用 |
| 四 | `chore(statusbar): i18n+样式+收尾` | `npm run test/lint/build` 全绿 |

---

## 7. 风险与权衡

- **估算准确性**：`estimateTokens` 是近似值，仅用于展示百分比；若需精确值须后端透出 `usage`（本版不做）。
- **context 窗口上限缺省**：若 `context_window` 未设置，展示「未设置」而非百分比，避免分母为 0。
- **对话副作用**：为满足「只展示、不影响对话」，接线处刻意不碰 `sendMessage` 与后端负载；测试中加断言防护回归。
