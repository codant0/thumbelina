# 聊天流内实时工具调用卡 — 设计

- 日期：2026-09-05
- 状态：已评审通过，待实施
- 影响面：`src/thumbelina/agent/nodes.py`、`src/thumbelina/agent/graph.py`、`src/thumbelina/api/websocket.py`、`src/thumbelina/agent/trajectory.py`（payload 增字段）、`frontend/src/types/chat.ts`、`frontend/src/hooks/useWebSocket.ts`、`frontend/src/components/Chat/MessageList.tsx`、i18n zh/en、chat 样式、前后端测试

## 1. 背景与目标

当前 agent 的工具调用过程对用户不可见：`ThumbelinaAgent.stream()`（`agent/graph.py:1215`）只产出 `content`/`reasoning` 两类事件，带 `tool_calls` 的消息被主动过滤（`graph.py:1279-1282`）；工具执行信号仅写入 trajectory 表（事后可在 Trajectory 页回放），不推送 WebSocket。

目标：对话进行中，聊天流内实时显示工具卡——工具被调用时出现"运行中"卡片（参数可展开），执行结束变为完成/失败态（含耗时、结果预览可展开）。

**范围决策（已与用户确认）**：
- 仅聊天流内实时工具卡，不做轮次进度面 / run 账本。
- 仅实时：重新打开历史会话时不回填旧消息的工具卡（事后查看走 Trajectory 页）。
- `run()` 路径（QQ/微信通道、定时任务等非 WS 调用方）不涉及。

**既有可复用资产**：
- 前端骨架已存在：`types/chat.ts` 的 `Message.toolCalls?: ToolCall[]`、`MessageList.tsx` 的 `ToolCallItem` 折叠工具卡、i18n `toolCalls.*` 键——只是无数据供给。
- WS 实时事件帧先例：`subagent_event`（`websocket.py:361-376`）及前端模块级订阅模式。
- 工具执行天然 hook 点：`_tool_node_node`（`graph.py:751-784`）已在此写 trajectory `tool_call`/`tool_result`。

## 2. 机制选型

**选定：LangGraph custom stream writer（`get_stream_writer()`，langgraph 1.2.7 已验证支持）。**

备选与放弃理由：
- agent 实例回调（on_tool_event sink）：开辟绕过生成器的第二通道，事件与 token 流无顺序保证，回调生命周期需跟随 `clone()` 管理。
- `astream_events` v2：事件噪声大，需重写整个 `stream()` 消费逻辑，改动面与收益不成比例。

选型理由：保持"agent ↔ WS 唯一通道是 `stream()`"的现有架构约束；`stream_mode=["messages", "custom"]` 下 custom 事件与 token 流在同一个异步生成器内天然交错，工具执行期间事件立即可达；不引入 agent 实例可变状态，`clone()` 天然安全；`run()` 零影响。

## 3. 事件模型（后端）

`stream()` 产出从 2 类扩展为 4 类（dict，向下兼容）：

```python
{"type": "content",   "text": str}                                       # 现状
{"type": "reasoning", "text": str}                                       # 现状
{"type": "tool_start", "call_id": str, "name": str, "args": dict}        # 新增
{"type": "tool_end",   "call_id": str, "duration_ms": int,
 "is_error": bool, "result_preview": str, "result_truncated": bool}      # 新增
```

- `call_id` 取 AIMessage 自带的 `tool_calls[].id`，start/end 配对与前端 React key 均依赖它。
- 工具事件**不进批量缓冲**，立即 yield；token 批量缓冲逻辑（30 字符 / 50ms）不变。
- `result_preview` 截取结果前 2KB，`result_truncated` 标记是否有更多；`args` 序列化超过 8KB 时截断并置 `args_truncated: true`（完整参数仍随 trajectory 落库）。

## 4. 后端改动

### 4.1 `agent/nodes.py` — `tool_node()`

- 签名增加可选 `on_tool_event` 异步回调：`async def tool_node(state, tools, on_tool_event=None)`。
- `_invoke_one` 内部记开始时间（`time.monotonic()`），在三个出口回调（**逐工具实时触发**，不等 `gather` 整批完成）：
  - 成功：`{"call_id", "is_error": False, "duration_ms", "content": str}`
  - 异常（含未知工具）：`{"call_id", "is_error": True, "duration_ms", "content": str}`
  - **错误状态由控制流直接给出**，不再依赖 `content.startswith("Error")` 字符串反推。
- 回调异常必须吞掉（记 debug 日志），不影响工具执行本身。
- 返回值结构不变（`{"messages": [ToolMessage, ...]}`，顺序与 tool_calls 对齐）。

### 4.2 `agent/graph.py` — `_tool_node_node()`

- 执行前：对每个 call `writer({"tool_start": {call_id, name, args}})`（writer 由 `get_stream_writer()` 获取；图外调用返回空 writer，判空降级——保证 `run()` 路径不受影响），并照旧写 trajectory `tool_call`。
- 把 writer 包装成 `on_tool_event` 传入 `tool_node`：wrapper 收到回调即**立即**发射 `writer({"tool_end": {call_id, duration_ms, is_error, result_preview, result_truncated}})`（preview/截断在 wrapper 内按 §3 规则加工），同时把 `(call_id, is_error, duration_ms)` 存入状态表供 trajectory 使用。
- `gather` 结束后：照旧写 trajectory `tool_result`，但 `is_error` 改用状态表真实状态（见 §4.1），payload 增加 `duration_ms`。

### 4.3 `agent/graph.py` — `stream()`

- `astream(..., stream_mode=["messages", "custom"])`，事件变为 `(mode, payload)` 元组：
  - `mode == "custom"`：payload 形如 `{"tool_start": {...}}` / `{"tool_end": {...}}`，直接映射为 §3 的 tool_start/tool_end 事件 yield。
  - `mode == "messages"`：现有 token 处理逻辑不动（含 compress 过滤、AIMessage 过滤、批量缓冲）。
- 旧事件形状完全兼容；`run()` 不改。

### 4.4 `api/websocket.py` — `_run_generation()`

- 流式分支：新增分支转发 `{"tool_event": {...}, "conversation_id": cid}`（沿用 `subagent_event` 帧形状先例；`tool_event` 内为 §3 的 tool_start/tool_end 字段）。
- **非流式分支统一改为消费 `stream()`**：只转发 tool_event 帧，content 累积后仍按现有 `{"response": ...}` 单帧发送——两种模式下工具卡行为一致，`streaming_enabled` 仅决定 token 是否逐字到达。`done` 帧的 `streaming_mode` 字段语义不变。

### 4.5 `agent/trajectory.py`（小幅）

- `record_tool_result` payload 增加 `duration_ms`（可选字段，缺失时省略）。Trajectory 页后续可展示耗时；页面本身不在本期改动。

## 5. 前端改动

### 5.1 `types/chat.ts`

```typescript
export interface ToolCall {
  call_id?: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: 'running' | 'ok' | 'error' | 'interrupted';
  durationMs?: number;
  resultTruncated?: boolean;
}
```

`WsIncoming` 增加 `tool_event`：`{ phase: 'start' | 'end', call_id, name?, args?, duration_ms?, is_error?, result_preview?, result_truncated? }`。

### 5.2 `useWebSocket.ts`

- 收到 `tool_event` 时：若当前会话没有进行中的 assistant 占位消息则先创建（工具调用可以先于任何文本出现）；按 `call_id` upsert 到该消息 `toolCalls[]`。一个 turn 多轮"LLM↔工具"循环的工具按时间序排列在同一 assistant 消息下（与后端一个 turn 持久化为一条 assistant 消息一致）。
- 路由复用 chunk 现有的按会话分桶机制，避免跨会话串话。
- `done/stopped/error` 时把残留 `running` 状态标记为 `interrupted`。
- 历史加载（`loadHistory`）不填充 `toolCalls`（范围决策：不回填）。

### 5.3 `MessageList.tsx` — `ToolCallItem` 升级为实时卡

| 状态 | 视觉 |
|---|---|
| running | 脉冲/旋转动画 + "调用中…" + 可展开参数 |
| ok | ✓ + 耗时 + 可展开参数与结果预览（截断提示"完整内容见轨迹页"） |
| error | 红条 + 结果预览（错误信息）+ 可展开参数 |
| interrupted | 中断态小字提示（i18n），保留参数可展开 |

- 参数/结果折叠展开沿用现有 `ToolCallItem` 模式（摘要 120 字）；视觉对齐 Trajectory 页 `ToolCallCard`，色值全部走主题令牌。
- 渲染条件仍为 `msg.toolCalls?.length > 0`。

### 5.4 i18n 与样式

- 中英各加 4 键（沿用现有 `toolCalls.*` 命名空间）：`toolCalls.running`（"调用中…"/"Running…"）、`toolCalls.interrupted`（"已中断"/"Interrupted"）、`toolCalls.durationMs`（"{ms} ms"）、`toolCalls.truncatedHint`（"完整内容见轨迹页"/"Full content in Trajectory page"）。
- 样式沿用 chat.css 现有设计令牌（复用 `--error` 等），running 动画仅 transform/opacity。

## 6. 边界与错误处理

- **Stop 取消**：生成任务被 cancel 时后端不补发 tool_end；前端在 `stopped` 处理分支把残留 `running` 统一标为 `interrupted`。
- **并发工具**：同一 AIMessage 的多个 tool_call 并发执行（`asyncio.gather`），各自独立成卡，`call_id` 区分。
- **超大参数/结果**：按 §3 截断；完整版仍在 Trajectory 页。
- **多 WS 客户端**：tool_event 帧带 `conversation_id`，与 chunk 现状一致只发给发起生成的连接。
- **writer 判空降级**：`get_stream_writer()` 在图外为空 writer，`_tool_node_node` 判空后跳过事件发射，`run()`/通道路径零影响。
- **事件先于文本**：前端占位消息机制覆盖"首个事件是 tool_start"的 turn。

## 7. 附带改进（与特性直接相关）

- 修复 review 文档 P0-13 的错误状态误判：trajectory `is_error` 与实时卡同源（`tool_node` 控制流），`startswith("Error")` 反推退役。
- trajectory `tool_result` payload 增加 `duration_ms`（见 §4.5）。

## 8. 测试策略

**后端**（`tests/test_agent/`、`tests/test_api/`）：
- `tool_node` 回调三态（成功/异常/未知工具）+ duration 计算；回调抛异常不影响执行。
- `stream()` 混合模式：产出 tool_start/tool_end 且与 content 交错；纯文本轮无工具事件；`run()` 路径无事件且行为不变。
- WS 层：tool_event 帧转发；非流式分支统一消费 `stream()` 后 `{"response"}` 帧与 done 帧语义不变。
- trajectory：`tool_result` payload 含真实 `is_error` 与 `duration_ms`。

**前端**：
- `useWebSocket`：tool_event upsert / 占位消息创建 / 残留 running 清理（done/stopped/error）/ 跨会话分桶。
- `MessageList`：四态渲染（扩展现有 toolCalls 测试样例）。

## 9. 里程碑

1. 后端事件源 + WS 层（§3、§4）+ 后端测试
2. 前端消费与实时卡（§5）+ 前端测试
3. 集成验证：前后端测试全量通过，手工冒烟（流式 + 非流式各一轮带工具对话）
