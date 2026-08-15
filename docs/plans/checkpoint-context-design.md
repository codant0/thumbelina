# 方案 A：LangGraph Checkpointer 上下文层设计

> 状态：待实施
> 日期：2026-08-14

## 一、背景与现状

当前项目基于 LangGraph 实现 LLM 调用，但**会话历史从不进入 LLM 上下文**：

- 每次请求只发送：角色提示 + 用户画像 + RAG 片段 + 当前用户消息
  （`src/thumbelina/agent/graph.py:502-528`，`run()`/`stream()` 每次重建 `initial_messages`）。
- 历史消息由 `_persist_message()`（graph.py:384）写入自有 `message` 表，仅供前端展示、
  搜索与自动命名，从不回流。
- `_build_graph()`（graph.py:336-356）编译时未挂 checkpointer，state 不跨请求持久化；
  每个请求/连接通过 `agent.clone()` 获得全新实例。
- 已预留但未接线的管道：`Summarizer`（`memory/summarizer.py`）、
  `MemoryManager.set_summary()`（`memory/manager.py:173`）、`conversation.summary` 列——
  目前仅测试引用。

## 二、方案选型结论（A vs B 对比摘要）

| 维度 | A：LangGraph Checkpointer | B：get_messages() 主动装载 |
|---|---|---|
| 改动量 | 小（compile 挂 saver + 传 thread_id） | 中（装载/裁剪/配对自管） |
| 历史保真度 | 最高，工具调用链完整保留 | 需自行处理工具消息配对 |
| 附加能力 | 中断/恢复、state 历史回放 | 无 |
| 存储 | 双份：checkpoint 表（可变工作区）+ message 表（不可变日志） | 单一真相源 |
| 压缩/摘要 | 图内 compress 节点改写 state | 装载前自行处理 |
| 框架绑定 | checkpoint 为 LangGraph 私有 schema | 无绑定 |

**采用 A 的核心理由**：checkpoint 与 message 表并非"两套真相源冲突"，而是分层——
**checkpoint = LLM 的上下文工作区**（可变、可压缩、含工具结果），
**message 表 = 客观对话日志**（只追加、供 UI/搜索/RAG）。
项目不持久化工具消息，B 方案的工具消息跨轮延续需自补，A 免费获得。

## 三、架构总览

```
┌─────────────── 对话上下文层（可变工作区）───────────────┐
│  LangGraph Checkpoint 表（thread_id = conversation_id）  │
│  内容：完整 state 快照（含工具调用链），可裁剪、可摘要   │
└──────────────────────────┬──────────────────────────────┘
                           │ ainvoke/astream(config=thread_id)
┌─────────────── 对话日志层（不可变事实）─────────────────┐
│  自有 conversation/message 表                            │
│  内容：user/assistant 文本，供 UI/搜索/RAG/自动命名      │
└──────────────────────────────────────────────────────────┘
```

- 写入路径不变：`_persist_message()` 继续写日志层。
- 读取路径新增：框架按 `thread_id` 自动从 checkpoint 恢复历史。
- 两层在会话生命周期事件上联动（删除/清空 → 清 checkpoint）。

## 四、关键设计决策

### 1. Checkpointer 选型与接线

- 依赖：`langgraph-checkpoint-sqlite`（项目默认 `sqlite:///thumbelina.db`，
  `config/models.py:47`）。Postgres 支持后续按 `database_url` 前缀切换，本期不做。
- 在 `api/app.py` lifespan 创建 `AsyncSqliteSaver`（app.py:215 旁），注入共享 agent；
  **saver 挂在共享 agent 上，`clone()` 传递引用**（graph.py:477），
  克隆体共用同一 saver，不重复建连接。
- `_build_graph()` 改为 `graph.compile(checkpointer=self._checkpointer)`。
- **checkpointer 为硬性要求，不做降级开关**：缺 `langgraph-checkpoint-sqlite`
  依赖、`database_url` 非 sqlite 或初始化失败时启动直接报错（fail-fast），
  不再静默退化为无 checkpointer 运行。
- CLI（`cli/chat.py:162`）同步接入。

### 2. thread_id 映射与调用改造

- `thread_id = current_conversation_id`；`run()`/`stream()` 中
  `ainvoke(state, config={"configurable": {"thread_id": cid}})`。
- **迁移语义**：checkpoint 为空的历史会话自动按"新上下文"起步，UI 历史不受影响
  （日志层完整），无需数据迁移。

### 3. 即时上下文处理：纯 append，不逐轮清理（保护 KV cache）

现状每轮把 RAG/技能等作为 `SystemMessage` 塞进 input state（graph.py:505-525）。
挂上 checkpointer 后这些消息会持久化进 checkpoint。处理原则：

- **不逐轮清理 ephemeral 消息**。RAG/技能消息注入后留在 state 中，仅在
  上下文 token 占用达到压缩阈值（见第 5、7 节）时随最旧消息一起删除。
- 由此消息序列每轮**纯 append**：第 N+1 轮发送的前缀完整包含第 N 轮，
  provider 侧前缀缓存（OpenAI/DeepSeek 自动前缀缓存、Anthropic cache_control）
  每轮可命中到上一轮末尾。
- 代价：压缩触发前残留过期的 RAG 片段（少量噪声 + token），由压缩阈值兜底；
  压缩本身是中段删除，但只在占用达阈值时发生（每 N 轮一次），成本被摊薄。

三类上下文的生命周期归类：

| 上下文 | 生命周期 | 处理方式 |
|---|---|---|
| 角色提示 | 会话级，恒定 | 序列最前，每次调用随 input 携带（内容不变，前缀稳定） |
| 用户画像 | 用户级，准静态 | 仅首轮注入一次，见下一节 |
| RAG / 技能 | 单轮 | 每轮随 input 注入，不单独清理，压缩时统一删除 |

### 4. 用户画像：仅首轮注入

- 仅在 thread **首轮调用**（checkpoint 为空）时，把最新用户画像作为一条
  SystemMessage 注入一次，位置在角色提示之后、对话历史之前。
- 首轮判定：`await graph.aget_state(config)` 返回空 values 即为首轮。
- 后续轮次不再注入、不更新：会话进行中的画像变化不影响本会话，
  自下一个新会话起生效。
- 收益：序列头部 `[角色sys, 画像sys, ...]` 整个会话完全稳定，
  对前缀缓存最友好，且无累积。

### 5. 上下文压缩（模型级窗口 + 可替换压缩策略）

#### 5.1 窗口来源：模型级配置，不用全局配置

- 上下文窗口大小配置在**模型/端点层**：
  - `LLMConfig.context_window`：默认 provider 所用模型的窗口（配置库管理，
    `PUT /config/llm`），默认 `"128K"`；
  - `LLMEndpoint.context_window`：endpoint 级窗口字段（新增，Pydantic 加默认值
    字段即可，JSON blob 存储零迁移）。
- 每轮调用前按会话解析，顺序：**会话绑定的 endpoint → 全局激活 endpoint →
  `llm.context_window` 默认值**（解析逻辑与 `chat.py:_apply_conversation_endpoint`
  同源），解析结果作为参数传入 compress 节点。
- CLI 不走 EndpointManager，直接取 `llm.context_window`。

#### 5.2 压缩抽象：`ContextCompressor`（不复用 Summarizer）

现有 `Summarizer`（memory/summarizer.py）定位是"1-2 句话"的快速概括，
不适合大量上下文压缩，**不接入压缩链路**；同时为避免与压缩摘要器混淆，
将其重命名为 `TitleSummarizer`（文件、引用与测试同步更新）。新建独立抽象：

```
src/thumbelina/agent/compression/
├── base.py              # ContextCompressor 抽象基类 + CompressionResult
├── sliding_window.py    # 策略 1：滑动窗口
├── full_summary.py      # 策略 2：全文摘要
├── summary_recent.py    # 策略 3：摘要 + 最近 K 轮
├── summarizer_context.py # 压缩专用 LLM 摘要器（ContextSummarizer：长提示词、输入截断、分批递归）
└── factory.py           # 按配置名注册/创建，可扩展第三方策略
```

- 抽象接口：`async compress(messages, window_tokens) -> 压缩后的消息序列`，
  由 compress 节点（入口 → compress → agent）在占用达
  `window × context.compress.threshold` 时调用。
- **占用估算**：复用 `ContextFormatter` 现成估算器
  （`rag/retrieval/context_formatter.py:39-46`，CJK 2 token/字 + 其他 0.25 token/字符）。
- **公共约束**（三种策略均满足）：
  - 压缩到占用 ≤ 窗口 **50%**（低水位，避免逐轮反复压缩）；
  - 删除边界保证 `AIMessage(tool_calls)` 与 `ToolMessage` 配对完整；
  - 摘要/压缩结果被 checkpointer 固化，下一轮恢复即为压缩后状态。

#### 5.3 三种初始策略

| 策略 | 行为 | 特点 |
|---|---|---|
| `sliding_window` 滑动窗口 | 直接删除最旧消息至低水位，不做摘要 | 零 LLM 开销、零延迟；旧信息彻底丢失 |
| `full_summary` 全文摘要 | 将超出低水位的全部旧消息交给压缩摘要器生成一条摘要 SystemMessage，替换原文 | 信息保留最省 token；摘要调用开销最大 |
| `summary_recent` 摘要+最近 K 轮 | 旧消息摘要替换，最近 K 轮（`context.compress.recent_turns`）完整保留 | 平衡项，**默认策略** |

- 压缩专用摘要器（`summarizer_context.py`，类名 `ContextSummarizer`）要求：
  长文提示词（保留事实、决策、未完成事项）；单次输入超限时分批摘要再归并
  （递归）；剥离 thinking 块与超长工具输出后再摘要；失败时降级为纯删除
  （不阻塞对话）。
- **K 收缩边界**：若最近 K 轮原文本身已超过低水位（50%），K 自动收缩——
  至少保留当前轮，其余消息照常纳入摘要；收缩后仍须满足工具消息配对完整。

### 6. 生命周期联动（防"上下文复活"）

| 事件 | 现状位置 | 新增动作 |
|---|---|---|
| 删除会话 | `api/routes/conversations.py:296` | `await saver.adelete_thread(cid)` |
| 清空消息 | `api/routes/conversations.py:279` | 同上 |
| 同会话并发请求 | `api/websocket.py`（单连接内顺序处理） | 加 per-conversation `asyncio.Lock`，避免 checkpoint 写冲突 |

### 7. 配置项

窗口（模型级，见 5.1）：

```yaml
llm:
  context_window: "128K"   # 默认 provider 模型的上下文窗口（配置库管理）
```

- endpoint 级：`LLMEndpoint` 新增 `context_window` 字段（可选，缺省回落
  `llm.context_window`），同步扩展 Create/Update/Response schema 与前端表单。
- 单位：字符串，支持 `K`（千 token）/ `M`（百万 token），大小写不敏感；
  Pydantic `field_validator` 解析，非法格式启动时报错，内部统一为 int token 数。

压缩策略（全局，新增 `ContextConfig`）：

```yaml
context:
  compress:
    strategy: summary_recent   # sliding_window | full_summary | summary_recent
    threshold: 0.8             # 占用达到窗口 80% 时触发压缩
    recent_turns: 6            # summary_recent 策略保留的最近轮数
```

- 不再提供功能开关：checkpointer 能力固定开启且为硬性要求——缺依赖、
  非 sqlite 配置或初始化失败时启动报错（fail-fast），修复方式为修复环境或回滚代码。
- 策略经 factory 按名称注册，新增策略只需实现 `ContextCompressor` 并注册。

### 8. 已知边界（本期不处理，仅记录）

- 无功能开关：checkpointer 固定开启且为硬性要求（缺依赖/非 sqlite 配置
  启动即报错），出问题修复环境或回滚代码；上线初期需重点观察 token 消耗与回复质量。
- 窗口为模型级配置但存在回落链（会话 endpoint → 全局激活 endpoint →
  `llm.context_window`）：endpoint 未填窗口时仍落到默认值，可能与实际模型不符，
  需在 endpoint 表单中引导填写。
- 同一 endpoint 下多个模型共用一个窗口值（`models` 为字符串列表，无每模型
  元数据）；需要每模型粒度时再升级为 `model_settings` 结构。
- 现有 `Summarizer` 重命名为 `TitleSummarizer`，不接入压缩链路
  （定位是快速命名式概括）。
- 会话中途切换角色/模型：checkpoint 内旧消息沿用旧角色上下文
  （现状根本不保留历史，无回归）。
- 用户画像仅首轮生效：会话中画像更新不影响当前会话，下一新会话生效。
  画像生成（`analyze_conversation`）当前未在生产接线且属低频操作，可接受。
- 压缩触发前残留过期 RAG/技能上下文：为保持纯 append 与前缀缓存命中的有意取舍，
  由压缩阈值限制其上界。
- Anthropic thinking 块回传问题：compress 节点对压缩后首条 assistant
  消息剥离 thinking 内容块，防 400。
- 中断/停止生成能力：Stop 按钮方案已单独规划，见
  `docs/plans/2026-08-14-interruptible-stop-design.md`，本特性完成后实施；
  human-in-the-loop（`interrupt()`/`resume`）本期不开放 UI 交互。
- checkpoint 表随版本链增长，压缩只减小最新 state；长对话需定期清理
  （删除/清空会话时 `adelete_thread` 已覆盖主要场景）。

## 五、任务拆解

| # | 任务 | 改动文件 | 验收标准 |
|---|---|---|---|
| T1 | 依赖与基础配置 | `pyproject.toml`；`config/models.py`（`LLMConfig.context_window`、新增 `ContextConfig`：strategy/threshold/recent_turns，K/M 单位解析）；`thumbelina.yaml.example` | 配置解析测试通过（含 `"128K"`/`"1M"`/非法格式报错）；旧配置兼容 |
| T2 | Endpoint 层窗口配置 | `llm/endpoint_manager.py`（`LLMEndpoint`/Create/Update 加 `context_window`）；`api/routes/config.py`（Response schema）；前端 `llmConfig.ts`、`EndpointForm.tsx`、`EndpointList.tsx`、i18n | 新字段 CRUD 往返正确；旧记录（无该字段）正常加载；前端表单可填写 |
| T3 | Checkpointer 接线 | `agent/graph.py`（构造参数、`clone()`、`_build_graph`）；`api/app.py`（lifespan 创建/关闭 saver）；`cli/chat.py` | 多轮对话上下文连续；无 conversation_id 路径不受影响 |
| T4 | thread_id 调用改造、注入逻辑与窗口解析 | `agent/graph.py` `run()`/`stream()`；`api/routes/chat.py`、`api/websocket.py`（窗口解析链：会话 endpoint → 全局激活 → 默认） | 两处调用均传 config；画像仅首轮注入；RAG/技能每轮注入不单独清理；compress 节点拿到正确的模型级窗口 |
| T5 | 压缩框架与 compress 节点 | 新建 `agent/compression/`（base/factory）；`agent/graph.py`（入口 → compress → agent） | 占用达 `window × threshold` 触发；`sliding_window` 策略可用：压缩后 ≤ 窗口 50%、`tool_calls`/`ToolMessage` 配对完整 |
| T6 | 压缩摘要器、摘要策略与旧类重命名 | `agent/compression/summarizer_context.py`（`ContextSummarizer`：长提示词、分批递归、thinking/超长工具输出剥离）；`full_summary.py`；`summary_recent.py`；`memory/summarizer.py` `Summarizer` → `TitleSummarizer`（引用与测试同步） | 两种策略压缩后占用达标且保留最近 K 轮原文（K 可收缩至当前轮）；摘要 LLM 失败时降级纯删除不报错；`TitleSummarizer` 重命名后既有测试通过 |
| T7 | 生命周期联动 | `api/routes/conversations.py`；`api/websocket.py`（per-conv 锁） | 删除会话后同 id 重建不复活旧上下文；并发请求无 checkpoint 冲突 |
| T8 | 测试 | checkpoint 连续性/压缩三策略/窗口解析/删除清理测试（单测用 MemorySaver）；跑通现有套件 | `pytest` 全绿；ruff 通过；前端测试通过 |
| T9 | 手工验证 | — | Web 端多轮追问"我刚才说了什么"；工具调用跨轮延续；切换三种压缩策略观察行为；删除会话后重建 |

**依赖关系**：T1 → T2 → T3 → T4 → T5 → T6 → T7、T8 并行 → T9。

**预估改动量**：后端约 500 行（含测试），前端约 100 行（endpoint 表单）。

**分批建议**：第一批 T1–T4（最小可用的多轮上下文）；第二批 T5–T6（压缩框架与三策略）；
第三批 T7–T9（生命周期、测试与验证）。

## 六、后续扩展特性：可打断（Stop）

**上下文特性（T1–T9）实现完成后，可继续实施可打断特性**：
设计文档见 `docs/plans/2026-08-14-interruptible-stop-design.md`。

要点摘要：

- 流式生成中途 Stop：user 消息 + 半截回复以 `interrupted` 标记入库（方案 B，
  保留痕迹、UI 可见）；
- LLM 上下文依赖 checkpointer 的节点级原子持久化，天然不含被打断的本轮，
  无需压缩/裁剪逻辑特殊处理——这正是本特性先行实施的原因；
- 主要改动：WS 层并发化（流式期间可收 stop 帧）、`stream()` 取消处理、
  前端 Stop 按钮与收尾逻辑（任务 S1–S6）。
