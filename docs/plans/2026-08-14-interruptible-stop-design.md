# 可打断（Stop 停止生成）特性设计

> 状态：待实施（**前置依赖**：`docs/plans/checkpoint-context-design.md` 上下文特性完成后执行）
> 日期：2026-08-14

## 一、目标与范围

用户在流式生成过程中点击 Stop 按钮，立即中断本轮生成：

- 已生成的部分内容**保留痕迹**入库（user 消息 + 半截回复，带 `interrupted` 标记），
  UI 可见；
- LLM 上下文（checkpoint）天然不含本轮——取消发生在节点执行中途，
  checkpointer 只提交完成的 super-step，thread 停留在上一轮完整快照；
- 停止后可立即发起新一轮对话。

**范围内**：Web 端 WS 流式链路（前端 + `api/websocket.py` + `agent.stream()`）。
**范围外**：HTTP `/chat`（只有非流式 `run()`，无 SSE）；WeChat/QQ 渠道（走 `run()`）。

## 二、现状与关键障碍

| 位置 | 现状 | 问题 |
|---|---|---|
| `api/websocket.py:146-158` | 流式期间 handler 阻塞在发送循环，不回到 `receive_text()`（L69） | **stop 帧无法被读取**，是核心障碍 |
| `api/websocket.py:82-96` | 已有 `switch_conversation` 命令分支模式 | stop 命令可仿此实现 |
| `agent/graph.py stream()` | L548 先落库 user 消息；assistant 只在流自然结束后落库（L631）；无 try/finally、无 CancelledError 处理 | 取消后留下孤儿 user 消息、半截内容丢失 |
| `useWebSocket.ts` | 有 `isStreaming`/打字机/90s 超时，无任何取消逻辑 | 需新增 stop 发送与回执处理 |
| `InputBox.tsx` / `ChatWindow.tsx:168` | 生成中 `disabled` 禁用整个输入框 | Stop 按钮无处可点 |

## 三、一致性策略：方案 B（保留痕迹）

| 层 | 停止后的状态 |
|---|---|
| 自有 message 表（日志层） | user 消息已存在；**追加半截 assistant 回复，`interrupted=true`** |
| checkpoint（上下文层） | 停留在上一轮完整快照，本轮 user/AI 均不在图状态中 |
| UI | 显示半截回复 + "已停止"标记 |

**推论**：

- 下一轮 LLM 上下文不含本轮（checkpoint 无记录），行为等同"这轮没发生过"，
  无需在压缩/裁剪逻辑中做任何特殊处理；
- 日志层保持只追加（不删 user 消息），`interrupted` 记录可用于审计与 UI 展示；
- 消息 schema 需新增 `interrupted` 字段（`memory/models.py` Message 模型 +
  repository + `MemoryManager.add_message` 参数），旧记录默认 `false`，JSON/ORM
  加列带默认值即可，无迁移脚本负担。

**部分内容的来源**：后端流式批量推送（30 字符/50ms，graph.py:583）导致前端
buffer 可能领先于后端已发送量。以**前端 buffer 为准**：stop 帧携带
`{"stop": true, "conversation_id": ..., "partial": "<前端已渲染全文>"}`，
后端直接用它落库，保证 DB 与用户所见一致。

## 四、链路设计

```
前端 Stop 点击
  → 发送 {"stop": true, conversation_id, partial}
  → 打字机立即追平收尾、isStreaming=false（乐观更新）

后端 WS handler（并发化后）
  → 收到 stop 帧 → cancel 流式 task
  → stream() finally：落库 partial（interrupted=true）、不触发自动命名
  → 回执 {"stopped": true, conversation_id}
  → 释放 per-conversation 锁（见 checkpoint 文档 T7）
```

### 4.1 后端 WS 并发化（websocket.py）

- 流式迭代从 handler 主循环拆出为 `asyncio.Task`；主循环并发等待
  "新帧到达 / 流事件产出"（如 `asyncio.wait(FIRST_COMPLETED)` 或
  receive task + 逐事件转发），收到 stop 帧即 `task.cancel()`；
- stop 命令分支仿 `switch_conversation`（命令帧不经 `WebSocketMessage` 校验）；
- 停止后**跳过微信回发同步**（现 L178-196 在流结束后回发全文，半截内容不发）；
- 断连（`WebSocketDisconnect`）走与 stop 相同的清理路径（取消流任务 + 落库 partial）。

### 4.2 Agent 层（graph.py stream()）

- `try/finally` 包裹 `astream` 循环；取消时按调用方传入的 partial 内容落库
  （`interrupted=True`），跳过 `_maybe_auto_name`；
- 正常结束路径不变（落库完整回复，`interrupted=False`）；
- **自动命名守卫**：`_maybe_auto_name` 的消息计数应跳过 `interrupted` 记录
  （避免半截对话触发命名）。

### 4.3 前端

- `useWebSocket.ts`：
  - 新增 `sendStop()`：发送 stop 帧（携带当前 buffer 全文）；
  - 乐观收尾：点击即打字机追平、`setIsStreaming(false)`，不等回执；
  - 处理 `stopped` 帧：仅做幂等确认（收尾已提前完成）；
- `InputBox.tsx`：`isStreaming` 时渲染 Stop 按钮（替换 Send），可点；
  textarea 保持可用与否按产品定（建议可用，但回车发送在流式期间无效）;
- `ChatWindow.tsx`：解除整框 `disabled`，改为只禁用发送路径；
- 消息气泡渲染：`interrupted` 消息显示"已停止"标记（i18n）；
- 测试：`InputBox.test.tsx` / `ChatWindow.test.tsx` 增补 Stop 场景。

## 五、边界情况

- **重复 stop / 竞态**：stop 到达时流已自然结束 → 忽略 stop，正常 done 流程；
  以"流是否已结束"为幂等判断，前端收尾幂等；
- **stop 后 90s 回复超时计时器**：需取消，避免误报超时；
- **连续快速发新消息**：stop 清理完成（锁释放）前，新消息排队等待，
  与 checkpoint 文档 T7 的 per-conversation 锁语义一致；
- **工具调用中途停止**：正在执行的工具随 task 取消而中止；工具副作用
  （如已发出的定时任务）不回滚，日志中保留工具消息痕迹不可行
  （checkpoint 未提交），接受此边界；
- **多标签页同会话**：一个页面 stop，另一页面流仍在渲染——本期不处理跨连接
  同步，仅本连接生效。

## 六、任务拆解

| # | 任务 | 改动文件 | 验收标准 |
|---|---|---|---|
| S1 | interrupted 字段支持 | `memory/models.py`、`memory/repository.py`、`memory/manager.py` | 消息可带 `interrupted=true` 落库/读取；旧记录默认 false；`_maybe_auto_name` 跳过 interrupted 记录 |
| S2 | WS 并发化 + stop 协议 | `api/websocket.py` | 流式期间可接收 stop 帧；取消流任务；落库 partial（interrupted）；发 stopped 回执；断连走同一清理路径；微信回发跳过 |
| S3 | stream() 取消处理 | `agent/graph.py` | 取消时按传入 partial 落库且不触发自动命名；正常路径无回归 |
| S4 | 前端 Stop 交互 | `useWebSocket.ts`、`InputBox.tsx`、`ChatWindow.tsx`、i18n | 流式中显示可点 Stop；点击即收尾并落库痕迹；stopped 帧幂等 |
| S5 | 测试 | 后端（stop 帧/竞态/断连）+ 前端组件测试 | 现有套件全绿；新增场景覆盖"stop 后立即可发新消息" |
| S6 | 手工验证 | — | 长回复中途停止：UI 半截+标记、DB interrupted 记录、下一轮上下文不含本轮、微信不回发半截 |

**依赖关系**：S1 → S2 → S3 → S4 → S5、S6。
**预估改动量**：后端约 200 行（含测试），前端约 120 行。

**前置说明**：本特性整体排在 checkpoint 上下文特性（T1–T9）之后实施——
"LLM 上下文天然不含被打断的本轮"依赖 checkpointer 的节点级原子持久化；
无 checkpointer 时现状本就无多轮上下文，Stop 仅需 S1–S4 的日志层语义即可，
但为避免两套行为返工，统一后置。
