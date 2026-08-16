# Thumbelina 代码检视报告（2026-08-16）

> 生成日期：2026-08-16
> 检视方式：3 个子 agent 并行检视各模块 + 1 个子 agent 规划优化方向
> 检视重点：checkpointer 并发、上下文压缩、配置迁移、通道上下文窗口

---

## 一、确认的正确性问题（8 项，按严重度排序）

### 1. `memory`→`repository` 改名导致旧配置静默丢失 — **最高优先**

- **位置**: `src/thumbelina/config/models.py:184`
- **问题**: `AppConfig` 没有 `memory` 字段，而 pydantic v2 默认 `extra='ignore'`，会静默丢弃。
- **触发场景**: 用户升级后，`thumbelina.yaml` 中仍含 `memory: {database_url: sqlite:///custom.db}`，或环境变量 `THUMBELINA_MEMORY__DATABASE_URL`。应用启动时该值被丢弃，回落到默认 `sqlite:///thumbelina.db`：旧数据库被弃用，UI 中所有对话/技能/反馈"消失"，新数据写入全新空文件。
- **验证**: 已通过 `AppConfig.model_validate({"memory": {...}})` 实测确认 `_env_overrides()` 会构建 `{"memory": {...}}`。

### 2. 摘要头永久累积，压缩策略最终退化

- **位置**: `src/thumbelina/agent/compression/summary_recent.py:155`
- **问题**: 摘要 SystemMessage 紧跟受保护 head 之后，下一轮 `leading_system_unit_count` 会把它算进 head，因此永远不会被重新摘要。
- **触发场景**: 每轮压缩返回 `head + [summary] + kept`。下一轮 head 越过该 SystemMessage 进入受保护区，摘要内容被排除在可摘要中段之外。实测 head 5 轮从 2 涨到 6 单元。在 128K 窗口（目标 64K）下，摘要 3-8K token，约 10-20 次压缩后 head 单独超过低水位，`build_summary_message` 返回 `None`（budget≤0），策略永久退化为 `sliding_window`——每轮丢弃上一轮回复，agent 丢失近期上下文，而陈旧摘要仍占用预算。

### 3. WebSocket 流失败回退导致消息重复

- **位置**: `src/thumbelina/api/websocket.py:222`
- **问题**: 回退分支在相同 checkpoint 线程上重跑同一用户消息。
- **触发场景**: `agent.stream()` 已通过 `_persist_message` 持久化用户消息并写入 checkpoint，之后才抛异常。except 分支在同一 agent/thread_id 上调用 `agent.run()`，从已含用户输入的状态再次处理该轮。实测线程状态最终为 `[Human('hello'), AI('ok'), Human('hello')]`，仓库出现两条用户行，回退回复由重复提示词生成。

### 4. 检查点锁覆盖范围不足

- **位置**: `src/thumbelina/api/websocket.py:164`
- **问题**: 每对话 checkpoint 锁只在 WebSocket 处理器中持有，但注释声称它序列化 HTTP 路由——`POST /chat` 与微信通道在同一 thread_id 上无锁修改。
- **触发场景**: 所有克隆共享一个以 `thread_id==conversation_id` 为键的 `AsyncSqliteSaver`，且其内部无锁。前端 WS 轮询与 HTTP `POST /chat` 或微信消息（`wechat_channel.py:312`）并发时，对同一 checkpoint 交错读改写：两者读到同一末态，其中一轮的上下文更新被静默丢弃，`_is_first_turn` 可能注入重复的 role/profile 系统消息。同一根因还使 `DELETE /conversations/{id}`（`conversations.py:338`）与在途 WS 轮询竞争——`delete_thread` 执行后，仍在运行的调用最终写入会把要清除的线程复活。

### 5. 批量删除不清检查点线程

- **位置**: `src/thumbelina/api/routes/data.py:80`
- **问题**: `DELETE /data/all` 循环调用 `delete_conversation`，但不像单条删除路由那样清理 LangGraph checkpoint。
- **触发场景**: 单条删除路由调用 `_clear_checkpoint`（`conversations.py:319,338`）就是为了避免 ID 复用时旧上下文复活，批量删除却跳过。`DELETE /data/all` 后所有线程行永久留在 checkpointer SQLite 文件中（无界增长），之后任何用相同 ID 重建的会话都会静默延续已删除会话的 LLM 上下文。

### 6. full_summary 把当轮注入的系统消息也摘要掉

- **位置**: `src/thumbelina/agent/compression/full_summary.py:74`
- **问题**: `middle = units[head_count:-1]` 包含当轮注入的 SystemMessage（RAG 块、技能指令），在 agent 读取前就被摘要掉了。
- **触发场景**: `_build_initial_messages` 每轮在当前 HumanMessage 前注入 RAG 与技能系统消息（`graph.py:649-655`）。知识库会话触发压缩时，这些单元位于 head 与 `units[-1]` 之间，当轮检索被压进摘要而非送达模型。`summary_recent` 通过 `_split_turns` 保护它们，`full_summary` 没有——agent 在回答当前问题时拿不到刚检索到的分块。

### 7. 压缩器 summarizer 绑定构建时默认 provider，不随会话端点切换

- **位置**: `src/thumbelina/agent/graph.py:390`
- **问题**: `create_compressor(..., llm_provider=self.llm_provider)` 绑定默认 provider；`_apply_conversation_endpoint` 只通过属性 setter 设置 `agent.llm`（`chat.py:207`），而唯一会重定向 compressor 的 `swap_provider`（`graph.py:430-432`）不会被调用。
- **触发场景**: 服务无默认凭据启动（lazy placeholder）时，每个摘要都是"请配置你的 LLM"占位文本，并被持久化为摘要 SystemMessage，污染后续上下文；有真实默认值时，摘要来自与回答所用不同的模型/分词器。

### 8. 微信通道不带 context_window_tokens

- **位置**: `src/thumbelina/channels/wechat_channel.py:312`
- **问题**: 微信通道调用 `agent.run(text)` 时不传 `context_window_tokens`，永远用不到绑定端点的上下文窗口。
- **触发场景**: HTTP 与 WebSocket 路径通过 `resolve_context_window_tokens`（`chat.py:41`）解析窗口，微信 agent 的 `_run_config` 却缺省，`_resolve_context_window` 回落到构建时默认值（`app.py:468`）。绑定 1M token 端点的微信会话仍在 128K 处压缩：`_compress_node` 约在 102K token 触发，截断服务模型本可处理的上下文，长微信线程过早丢失上下文。

---

## 二、候选但被裁掉的问题（3 项）

1. **Todo 日期标签混用时区**（`frontend/src/components/Todo/TodoPage.tsx:399`，note 时间戳来自服务端 `datetime.now()`，见 `todo/service.py:110`）—— 因影响面最小（仅 UI 展示层外观标签）在 8 项上限中被裁掉。
2. **`POST /chat` 冗余查询**：4 次重复 `get_conversation` 往返（`chat.py:60/98/165/224`）—— 效率类，非正确性。
3. **CLI 重复传参**：`cli/chat.py:262-268` 重复传入 `context_window_tokens`。

**附带**: `memory`→`repository`/`analysis` 改名相关的残留导入扫描结果干净。

---

## 三、优化方向规划

由第 4 个子 agent 基于 `agent/graph.py`、`checkpointer.py`、`compression/` 及 `docs/plans/checkpoint-context-design.md` 产出，按定位（个人助手 + 编码助手）分四层：

### 短期 — 稳定性/性能（先做）

- 上下文 token/预算硬管理器，杜绝超过配置的 context-window
- 压缩（summary-recent）参数调优，修复 head 累积（对应上文问题 2） 
- checkpointer 并发可靠性（对应上文问题 3、4）
- 记忆/检索召回质量提升
- 超长会话处理

### 中期 — 能力扩展

- **编码助手方向**: 语法感知分块的代码上下文、多文件编辑、git 集成、在插件沙箱中做沙箱化代码执行、代码库索引
- **个人助手方向**: 主动提醒、日历/邮件连接器、跨会话记忆整合、跨设备同步

### 长期 — 愿景

- 自主任务执行、多智能体协作、持续学习、本地优先隐私

### 横切关注

- 成本控制（按 provider 的 token 预算）、延迟优化、评估/可观测性、安全加固（个人 agent 工具面广）

### 核心建议

**先修第一部分的所有正确性问题再谈扩张**——它们直接破坏个人助手赖以存在的长对话体验。修复后，优先做编码助手工具链（git + 沙箱代码执行）与个人助手主动提醒功能，作为两个最高杠杆的扩展点。

---

## 四、建议修复优先级

| 优先级 | 问题 | 影响面 | 改动量 |
|--------|------|--------|--------|
| P0 | #1 配置静默丢失 | 用户升级数据丢失 | 小（加 alias/warning） |
| P1 | #3 消息重复 | 会话数据污染 | 小 |
| P1 | #4 检查点锁范围 | 并发丢上下文 | 中 |
| P1 | #5 批量删除不清线程 | 数据残留/复活 | 小 |
| P2 | #2 head 累积 | 长会话质量退化 | 中 |
| P2 | #6 full_summary 吞系统消息 | RAG 回答错误 | 小 |
| P2 | #7 summarizer 不随端点切换 | 摘要模型错配 | 中 |
| P3 | #8 微信通道上下文窗口 | 长微信线程丢上下文 | 小 |

---

## 五、修复状态（2026-08-16 已全部实现）

| # | 确认方案 | 实现摘要 | 验证 |
|---|----------|----------|------|
| 1 | 自动迁移写回 | `config/loader.py`：`_env_overrides` 映射 `THUMBELINA_MEMORY__*`→`repository`；`_migrate_memory_config` 在文件合并前把 `memory` 键改写为 `repository`，并通过 `_rewrite_yaml_top_level_key` 原地写回 yaml（保留注释）。 | `tests/test_config/test_loader.py` 新增 4 个迁移测试；配置套件 130 passed |
| 2 | 重算 head 边界 | `agent/compression/summarizer_context.py` 新增 `is_summary_message`、`split_turns`、`flatten_turns`、`leading_protected_head_count`；`summary_recent.py` 与 `full_summary.py` 改用共享的 `leading_protected_head_count`，摘要 SystemMessage 不再计入受保护头部。 | `tests/test_agent/test_summary_compression.py` 新增 TestHeadBoundary 4 个测试；压缩套件 75 passed |
| 3 | 只报错不重跑 | `api/websocket.py`：流式失败时向客户端发送 `Streaming failed` 错误并 `continue`，不再用同一线程重放用户消息。 | 全量 API 套件 195 passed |
| 4 | 锁收口共享管理器 | 新建 `concurrency.py`（`per_conversation_lock` / `conversation_lock_for`）；websocket / HTTP `/chat` / 微信通道 / 对话删除/清空路由统一走同一把 per-conversation 锁。 | `tests/test_api/test_websocket.py` 锁测试更新；API 套件通过 |
| 5 | 循环内清线程 | `api/routes/data.py`：`DELETE /data/all` 在循环内对每个会话持锁执行 `delete_conversation` + `_clear_checkpoint`。 | `tests/test_api/test_app.py` 新增 3 个 `/data/all` 测试 |
| 6 | 复用 _split_turns | `full_summary.py` 改用 `split_turns` 划分，保护最后一个轮次（当前输入 + RAG/技能系统消息注入）；共享辅助函数迁至 `summarizer_context.py`。 | `test_current_turn_system_injections_are_preserved` 等测试；压缩套件通过 |
| 7 | 切换时重建压缩器 | `agent/graph.py` 新增 `apply_conversation_provider` / `_redirect_compressor`，`swap_provider` 复用；`chat.py` 的 `_apply_conversation_endpoint` / `_apply_default_provider_thinking` 全部改走该方法，端点切换时压缩器 summarizer 同步重定向。 | `test_apply_conversation_provider_repoints_compressor_summarizer`；agent 套件 148 passed |
| 8 | 抽取公共逻辑 | `chat.py` 新增 `apply_conversation_runtime` / `resolve_run_window` 共享 helper，HTTP / WebSocket / 微信三端复用；`wechat_channel.py` 新增 `runtime` 参数（app.py 传入 `SimpleNamespace(app=app)` 惰性引用），消息路径解析端点与上下文窗口后传入 `agent.run`。 | `test_handle_message_passes_context_window_tokens`；微信套件 30 passed |

**全量回归**：`pytest` 1507 passed；`ruff check` / `ruff format` 全绿；mypy 未新增错误（既有 112 项为历史存量，涉及 `-> dict` 泛型缺参、yaml 存根、graph.py:579 等，不在本次改动范围）。
