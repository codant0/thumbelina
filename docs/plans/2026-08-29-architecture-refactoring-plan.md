# Thumbelina 架构与数据层重构规划

- 日期：2026-08-29
- 方法：5 个子 agent 并行只读评审（核心 Agent 层 / 数据层与表设计 / API 与基础设施层 / 前端 / 全仓依赖图与机械扫描），所有结论带 file:line 或运行库取证，跨域互相印证的问题已合并。
- 细化文档（2026-08-29 已回写本总规划，见附录 B 修订记录）：主题二 → docs/plans/2026-08-29-storage-refactor-design.md（32 任务 / 29.0 人日，偏差 Δ1–Δ10）；主题六 → docs/plans/2026-08-29-frontend-refactor-design.md（25 任务，偏差 D1–D11）。
- 范围：`src/thumbelina/`（157 py 文件 / 约 26.4k 行）、`frontend/src/`（约 15.9k 行 TS/TSX + 5.8k 行 App.css）、运行库 `thumbelina.db`、部署面（Dockerfile/compose/deploy）。
- 优先级定义：
  - **P0** = 正确性/安全/数据丢失风险，或阻塞其他一切重构的先决问题
  - **P1** = 明确架构债，重构收益大、应在中期规划内偿还
  - **P2** = 工程卫生与体验优化，可长期穿插

> **⚠️ 状态注记（2026-09-05）**：本文 §3 主题二「存储地基统一」（D1–D12，含 Alembic 落地方案）**已于 2026-08-30 回退，未实施**；配套细化文档 `2026-08-29-storage-refactor-design.md`（整篇为 Alembic 设计）已随之删除。数据库 schema 演进继续走现行机制 `Base.metadata.create_all` + `ensure_schema()`（`repository/db.py`），**不引入 Alembic**——后续决策记录见 `2026-08-30-event-timer-tasks-design.md` 的 D3 决策行。本文其余主题（前端重构等）不受此注记影响。

---

## 1. 现状总览

### 1.1 模块体量（行数取实测）

| 模块 | 行 | 健康度 | 模块 | 行 | 健康度 |
|---|---|---|---|---|---|
| api (22 文件) | 5214 | 差（God 装配+鉴权失效） | scheduler | 294 | 差（纯内存且任务空转） |
| rag (24) | 3923 | 中（重子系统，暴露面过宽） | security | 195 | 中（实现正确但没接线） |
| agent (14) | 2866 | 差（graph.py 1407 行巨石） | filestore | 166 | 良 |
| repository (11) | 2204 | 差（多引擎、无 FK/迁移） | backup | 158 | **死代码**（src 内零引用） |
| memory (9) | 2117 | 良（锁/原子写一致） | cli | 297 | 差（复制装配、缺子系统） |
| llm (9) | 1810 | 中（抽象兑现 1/3） | channels | 1391 | 差（双事件循环） |
| config (7) | 1441 | 差（三处真源、回写用户 YAML） | skills | 853 | 差（一半死代码+自建 engine） |
| plugins (7) | 1484 | 中（沙箱仪式性） | subagents | 463 | 差（取消语义是假的） |

前端热点：`Todo/TodoPage.tsx` 1105 行（18 useState）、`KnowledgeBasePage.tsx` 970 行（30 useState）、`hooks/useWebSocket.ts` 682 行、`App.css` 5790 行单文件。

### 1.2 数据资产

| 存储 | 用途 | 规模 | 状态 |
|---|---|---|---|
| SQLite 主库 9 表 | conversations / messages / trajectory_events / skills / skill_compositions / feedback / system_config / checkpoints / writes | 实测会话 5、消息 30、轨迹 169（**32 行孤儿**）、feedback 3（1 行孤儿）、system_config 18 键 | 无 FK 生效、无迁移、无统一索引 |
| 第二 DeclarativeBase | knowledge_bases / rag_documents（+raw SQL 的 rag_chunk_fingerprints 1282 行、sqlite-vec 虚拟表） | 独立一套 engine/迁移逻辑 | metadata 割裂 |
| 遗留僵尸表 | user_profiles / user_preferences | 0 行、代码零引用 | ensure_schema 只加不删 |
| 文件域 | MEMORY/、TODO/（Markdown，走 filestore 原子写+FileLocks）、backup JSON、data/chroma | — | 文件锁仅进程内；chroma 与 SQLite 无一致性协议且对话语义搜索实际未启用（app.py:221 未注入 vector_store） |

### 1.3 依赖图机械结论

- **存在一个 8 模块运行时循环**：`{api, agent, analysis, channels, config, llm, skills, subagents}`（剔除 TYPE_CHECKING-only 边后仍成环）。枢纽是 `config/runtime_manager.py`（12 处跨层引用）与 `channels/wechat_channel.py:330 → api.routes.chat`、`llm/preset_manager.py → agent`、`llm/endpoint_manager.py:11 ↔ config`。
- 分层违例 21 条；其中 6/7 处对 rag 的反向 import 只为 `rag.retrieval.context_formatter` 一个符号——rag 收敛为纯叶子只需搬一个工具函数。
- 出度为 0 的叶子模块 9 个、只被 app.py 装配的孤岛模块 5 个（security/todo/plugins/notifications/logging_config）；`api/app.py` 直引 18 个顶层模块，`cli/chat.py` 手工复制其中 8 个的装配。
- 全仓 `except Exception` 共 170 处（api 54、agent 24），静默吞错样例 `cli/chat.py:195,211,229`；≥6 行跨文件重复块 68 组（DB 引擎样板 4 份、LLM 连接测试逐行 3 抄约 180 行）。
- pyproject 卫生：用了未声明 `botpy / sentence_transformers / torch / huggingface_hub / starlette`；声明未用 `llama-index-* ×3 / pydantic-settings / python-multipart`。

---

## 2. 各层检视发现（合并去重后）

### 2.1 安全与鉴权（最严重的横切问题）

| # | 级别 | 位置 | 问题 |
|---|---|---|---|
| S1 | P0 | api/app.py:755-766 + docker-compose.yml | `secret_key` 为空即降级为**无鉴权启动**，而 compose 从不注入密钥、Dockerfile 绑定 `0.0.0.0:8000` → 默认部署全部写接口裸奔；前端全文无 `Authorization`，启用鉴权 UI 即不可用——鉴权当前是死代码 |
| S2 | P0 | api/websocket.py:175-195 | Starlette `BaseHTTPMiddleware` 对非 http scope 直通 → 两个中间件对 `/ws/chat` **完全不生效**；`conversation_id` 客户端任意提供，且 conversations 表无 user_id/owner 列 → 任意读写任意会话（IDOR by design）+ 零成本 LLM 滥用 |
| S3 | P0 | api/routes/wechat.py:93-108,74-79 | `/wechat/send` 无角色校验可向任意用户冒充机器人发消息；webhook_secret 默认空即跳过签名 |
| S4 | P0 | api/routes/fs.py:44-92 + cors `["*"]`（app.py:733-739） | `/fs/dirs` 可枚举服务器任意绝对路径（`C:\Users\…`、`/etc`），配合全开 CORS 浏览器页面即可跨源探测本机目录 |
| S5 | P0 | api/routes/data.py:86-122 | `DELETE /data/all?confirm=true` 一个 query 参数清空全部数据，无角色/二次确认 |
| S6 | P1 | routes/config.py:338-357 | `/config/export` 明文吐出 `tools.web_search.api_key`（唯一入库密钥） |
| S7 | P1 | app.py:67-86,134 | `require_roles` 定义后全仓零调用；memory 路由另写一份 `_check_roles`（空角色即放行）——CLAUDE.md 宣称的 per-route 鉴权与实现不符 |
| S8 | P1 | config/config_repo.py:42 + 端点 KV 落库 | [2026-08-29 细化复核 Δ7] 端点（bot）`api_key` 明文入库，且键名末段是 uuid、绕过 `_is_sensitive` 后缀判断 → 导出/日志脱敏为硬要求（落点：主题一修改点 6、主题二修改点 11）；细化文档不加字段级加密 |

### 2.2 数据表设计（主库 + 第二 Base + 文件域）

| # | 级别 | 位置 | 问题 |
|---|---|---|---|
| D1 | P0 | models.py:372-392；PRAGMA 实测 foreign_keys=0 | 全库未开 FK pragma → messages/trajectory 声明的 ON DELETE CASCADE 形同虚设；feedback 连 FK 都没有。实测已产生 32 条孤儿轨迹、1 条孤儿 feedback——数据正确性已受损 |
| D2 | P0 | models.py:249-252 + repository.py:150-154 | SQLite CURRENT_TIMESTAMP **秒级精度**且 messages 无 seq 列 → 同秒消息排序不确定，会话回放可乱序 |
| D3 | P0 | app.py:221/256/280/297/298/511 + repository/db.py:29 | 同一 SQLite 文件开约 5 个 engine/连接池（repository、skills×2、config、rag 各建各的）；文件库分支用默认 QueuePool，而所有操作经 `asyncio.to_thread` 跨线程 checkout 连接 → 泄漏/错用隐患 |
| D4 | P0 | models.py:22-101 + rag/common/db.py:97-211 | 无迁移机制：`create_all` + 自研 `ensure_schema`（只 ADD COLUMN 不改不删）+ RAG 手写"检测列型重建表"；僵尸表 user_profiles/user_preferences、DB 列序漂移均为实证后果；deploy/ 多版本并存时 schema 漂移不可控 |
| D5 | P0 | backup/manager.py:48-83（模块本身 src 零引用=死代码）+ routes/data.py:65-83 | 实际导出路径不含 skills/feedback/system_config/RAG/chroma；普通 `open().write` 非原子，崩溃留半截文件；SQLite+WAL 与 MEMORY/ 文件之间无统一快照点 |
| D6 | P1 | EXPLAIN 实测 | `messages WHERE conversation_id` → SCAN+TEMP B-TREE；LIKE 搜索全表扫描（无 FTS）；feedback 两个查询列、trajectory 的 event_type 排序均无索引。讽刺：唯一索引齐全的是 raw-SQL 建的 rag_chunk_fingerprints |
| D7 | P1 | models.py:16 vs orm_models.py:11 | 两套 DeclarativeBase → 跨域 FK（conversations.knowledge_base_id、skills 关联）不可声明；指纹表/虚拟表游离于任何 metadata 之外，"schema 真相"无处可查。[2026-08-29 细化决策 Δ5：不物理合并 Base 类——保留两套 DeclarativeBase，仅在 alembic env 层合并 metadata，跨域 FK 用迁移内原生 SQL 挂] |
| D8 | P1 | models.py:294,311-312,332-333 | JSON 塞裸 TEXT 无校验（trajectory.payload、skills.steps、compositions.skill_ids），非法 JSON 靠 except 兜底；100KB 内容限制只在 RepositoryManager 一处 |
| D9 | P1 | feedback_repo.py:44 vs server_default | 时区混用：库默认 UTC、Python 侧 `datetime.now()` 本地时间，同库两种时区、全部 naive。[2026-08-29 细化复核 Δ4：存量 19 位时间串实测已是 UTC——不做全库改写，残余风险仅写入侧] |
| D10 | P1 | routes/data.py:86-122 | 清理不彻底：feedback/trajectory（因 FK off）/skills/chroma 集合均不清；除 checkpoint 外全部只增不减，无归档策略 |
| D11 | P1 | system_config 实测 18 键 | 杂耍 KV：`provider` 与 `llm.provider` 新旧并存未清理、`llm_endpoints.index` 数组指针+每端点 JSON 大键、bot 身份明文入库 |
| D12 | P2 | 多处 | UUID String(36) 随机主键页分裂；mode/thinking_effort 无 CHECK；FileLocks 不跨进程（多实例部署需单写者）；根目录散落 thumbelina.db.bak、test_rag.db、3.2GB tar |

### 2.3 核心 Agent 层（agent/llm/skills/subagents/analysis/prompts）

| # | 级别 | 位置 | 问题 |
|---|---|---|---|
| A1 | P0 | graph.py:598-639 + runtime_manager.py:92-102 + routes/config.py:248,574 + app.py:578-586 | Provider 热切换的"重接线清单"散落 4 处、靠鸭子类型直改 `.llm_provider`——新增持有 provider 的子系统漏改即**静默用旧模型**（摘要/子代理/命名错模型） |
| A2 | P0 | subagents/manager.py:84,118-136 | `cancel_agent` 只改 status，协程继续跑并在结束覆写 COMPLETED → 取消是假的、API 返回撒谎；`run_agent` 用未跟踪 create_task；`_agents` dict 永不清理，内存单调增长 |
| A3 | P0 | graph.py:157-202 vs compression/base.py:138-194 | RemoveMessage/重追加的状态写回算法与压缩不变量修复拆在两模块，跨文件用 `is` 判等做契约（graph.py:768）→ 改动极易产生重复/丢失消息 |
| A4 | P1 | graph.py:1233-1407 | run/stream 前言、usage 记录、收尾三处复制已漂移：run 不传 `reasoning_content`（1276 vs 1398）→ 非流式路径丢思考内容 |
| A5 | P1 | nodes.py:88-94 + graph.py:918 | 工具异常吞成字符串，再用 `content.startswith("Error")` 反推 is_error → 正常输出以 Error 开头即被记为失败 |
| A6 | P1 | graph.py:205-412,541-578,1162-1187 | 工具装配 4 套 `_make_*` 与 memory 一套两套风格；`__init__` 16 参数 + clone() 逐参数复制 + 去重补丁（自认会重名 400）——新增一个子系统要改 5+ 处，违反开闭原则 |
| A7 | P1 | llm/base.py:130-206 + openai.py:28-80 + graph.py:117-154 | 抽象兑现不足：`list_models/speed_test` 两个 provider 直接 NotImplementedError 冒到 HTTP；stream 协议只有 str，reasoning/usage 增量靠运行时 monkey-patch OpenAI 子类 + agent 层特判，Anthropic/Ollama 走第三条路径 |
| A8 | P1 | 依赖方向 | llm/preset_manager → agent（TYPE_CHECKING 下仍实环）；api/app.py:166-213 手写不继承 ABC 的 `_LazyLLMProvider`；PresetManager 直接返回 HTTP 视图模型并逐字段手工复制 |
| A9 | P1 | skills/repository.py:24-28 等 | skills 自建第 3/4 套 engine 打同一 sqlite（见 D3）；`find_matching_skills` 每轮全表+N+1 反馈调整，结果只用 `matches[0]`；`record_usage` 无调用方 → 反馈调分链路输入端是死的 |
| A10 | P1 | 死代码 | `SkillExtractor`（仅测试）、`TitleSummarizer`（零引用）、`subagents/types.py` 整模块、`MessageQueue`、`suggest_compositions`；`prompts/` 形同虚设——全 scope 8+ 处硬编码 prompt，subagents 那份还是英文 |
| A11 | P2 | graph.py:57,1279；51 处 warning-only except | 模块级可变全局；auto_name 任务无 done_callback 异常丢失；降级一律静默、无 metrics |

### 2.4 API / 基础设施层

| # | 级别 | 位置 | 问题 |
|---|---|---|---|
| B1 | P0 | scheduler.py:77 + app.py:404-413 | 任务全内存重启即丢；更严重 `on_due_task` **只广播通知不执行任务**，而 notifications.subscribe() 全仓无调用方 → 定时任务静默空转 |
| B2 | P1 | app.py（820 行 lifespan） | God 装配：直引 18 模块、25 个 app.state 松散属性、无 try/finally（中途抛错 engine/checkpointer/线程全泄漏）、关闭清单缺 5 个子系统、反向 import 路由私有全局 `_qrcode_manager`；十余处 init 失败 `logger.debug` 吞致命错 |
| B3 | P1 | 配置系统 | 三处真源：首次启动 YAML→system_config 后**永久跳过**（改 YAML 无效）、启动时回写用户 YAML、热切换全量重写 YAML（丢注释、`${ENV}` 固化、密钥清空）；RateLimiter 用 YAML 值先于 DB 加载构造，DB 中限流配置永不生效且 enabled 热改不挂载 |
| B4 | P1 | runtime_manager.py:212-216 + routes/config.py:317-323 | 热切换渠道时不传 `runtime=` / `on_message_callback` → 切换后微信丢会话解析与前端广播，功能静默退化 |
| B5 | P1 | channels/qq_channel.py:205-215,237-265 | botpy 在 daemon 线程跑**第二个事件循环**且跨循环用主循环对象；`send_message` 是只打日志的空实现；直接共享 `agent.run()` 无 per-conversation 锁，与 HTTP/WS 交错读写同一 checkpoint |
| B6 | P1 | plugins/manager.py:141-143,265 | 有 sandboxed_loader 时提前 return，拓扑排序整段死代码 → `/plugins/dependencies` 恒空；sandbox `strict=False` 默认、`"exec*"` 字面量永不匹配、`os` 不在黑名单 → 仪式性防护 |
| B7 | P1 | routes/config.py(806) / routes/rag.py(802) | God router；路由内裸 SQL（rag.py:221）、手写流式落盘、跨层调用私有方法 `manager._persist_to_db`；错误码 422/500/502/503 混用 |
| B8 | P2 | 部署面 | 版本三源漂移（VERSION v0.0.1 vs pyproject 0.1.0）；dev 与 Docker 入口分裂；logging.yaml 相对 CWD、日志不在 compose 卷内；`config.logging` 段从未被读取；根目录脚本/大文件散落；`src/thumbelina/.claude/` 混在包内 |
| B9 | P2 | cli/chat.py:163-263 | 复制 lifespan 装配且缺 memory/namer/RAG/scheduler.start() → CLI 里 `schedule_task` 静默无效 |

### 2.5 前端

| # | 级别 | 位置 | 问题 |
|---|---|---|---|
| F1 | P0 | hooks/useWebSocket.ts:490-516 | **无重连、无心跳**：断线后输入永久灰死；`sendMessage` 非 OPEN 时静默丢弃（518-568 无 else）→ 消息石沉大海；onclose 不清打字机定时器（悬挂 interval + 半截文本）；[2026-08-29 细化复核 D4：浏览器无主动 ping、后端无 pong 帧，"心跳"纯前端无法闭环——前端做被动判活+对账，WS ping 协议扩展归主题五] |
| F2 | P1 | App.tsx:20-252 | 无全局 store、无 Router：CoderPage 一次透传 15 props（[细化复核 D2：含易漏计的 onViewTrajectory]）；11 个页面零 code splitting；会话 CRUD 回调在 chat/coder 两分支重复接线 |
| F3 | P1 | api/ + 组件 | 无统一客户端：3 套本地 `request<T>` + conversations/rag 逐函数手写 fetch；9 个组件绕过 api/ 裸 fetch 共 27 处（[细化复核 D9：组件内 25 + App.tsx:124 + useWebSocket.ts:589]）；错误处理三套写法 |
| F4 | P1 | types/ + tsconfig.app.json | 类型手写对齐后端且分散；**未开 strict**——[2026-08-29 细化实测 D8：`--strict` 单独 0 报错，"还 null 检查债"前提不成立；107 处报错全部来自 `noUncheckedIndexedAccess`，其中 100 处在测试文件、业务代码仅 7 处]；`WsIncoming` 实测仅一份（非两份），但 `useWebSocket.ts:245-250` 的 `connected` 帧**后端从不发送**（websocket.py:188 只 accept）→ 死分支，掩盖了"连接时报告默认会话"的未实现假设（D3） |
| F5 | P1 | TodoPage 1105 行 / KnowledgeBasePage 970 行 | [2026-08-29 细化复核 D1/D11：定性修正——TodoPage 内部已拆 6 组件+4 纯函数、useState 分布合理，真问题是 :360-474 与 :480-594 一对逐行复制，任务定性"切文件+去重"非"从零组件化"；KnowledgeBasePage 无任何轮询（全仓轮询仅 useUploadTasks.ts:53-57 一处），真问题是 30 个 useState 挤在一个函数体；两巨石与 Settings/Modal 均零测试 → 先补测再拆]；已有通用 Modal 仅 1 处使用，另两处各自复制 modal 结构（三份不同关闭逻辑实现） |
| F6 | P2 | App.css 5790 行 / useWebSocket 打字机 / Sidebar 名称匹配 | 主题系统正确（105 个 CSS 变量×3 主题）但残留 ~15 处硬编码色；打字机固定速率全列表 reconcile；用中文字符串匹配会话做默认选中 |

做得好的（重构时应保留为范例）：i18n 双语 464 键零漂移；多会话流式隔离认真设计过（sessionConvRef/historyFetchRef/completedContentRef 防乱序与补偿竞态）；memory+todo 均统一走 filestore 原子写与锁；LIKE 搜索已参数化转义无注入面；HTTP/WS 共用 chat 服务层（chat.py:274-296）。

---

## 3. 重构方向详解（六大主题 × 改动原因 / 修改点 / 收益 / 影响）

结构说明：每个主题固定四段——**改动原因**（含 §2 问题编号，个别标注"读码复核"为本次直接验证）/ **修改点**（具体到文件与新工件，标【新增|修改|删除|移动|合并|重写|决策】）/ **收益** / **影响**（破坏性、代码面、数据面、测试面、部署面、回滚难度、主题依赖）。

**主题间依赖**（§4 排期依据）：

- 主题二（迁移通道）← 先决于 → 主题一（user_id 列）、主题五（scheduled_tasks 表）
- 主题三（container / 注册表）← 先决于 → 主题二（engine 注入点）、主题四（ToolProvider、AgentDeps）、主题五（build_channel）
- 主题一（token 协议）× 主题六（client.ts 凭证注入）：原要求"必须同批合入"——[2026-08-29 细化修正 D6] 以 `AuthBridge` 接口 + `nullAuthBridge` 默认实现解耦后，client.ts 可先合入（无凭证时行为逐字节透明），主题一仅需启动处 `configureAuth(bridge)` 一行；"同批"放宽为"同版本"（心跳协议扩展、`connected` 帧、16 个弱类型 op 的 `response_model` 同理登记为对主题五的前置需求，不阻塞）
- 主题五（错误形状统一）与主题六（统一错误处理）同批；主题四与主题六的巨石拆分彼此独立，解阻后可并行

### 主题一：安全边界 fail-safe（对应 S1–S8、D11 ｜ Phase 1，前端登录面板与 client 注入在 Phase 5 合流）

**改动原因**

- 安全承诺与现状完全脱节（读码复核 `api/app.py:752-766`）：鉴权中间件**仅当 `secret_key` 非空才挂载，且"无效密钥=照常启动、鉴权关闭"**；而部署链路从不提供该密钥（docker-compose.yml 无 `THUMBELINA_AUTH__SECRET_KEY`、Dockerfile:66 绑 `0.0.0.0`）——默认部署 = 完全裸奔（S1）。
- Starlette `BaseHTTPMiddleware` 只处理 http scope，`/ws/chat` 绕过全部鉴权与限流；conversations 无 owner 列，`conversation_id` 客户端给什么读什么——IDOR 是设计级而非偶发（S2）。
- 前端全仓 0 处 `Authorization`：意味着"启用鉴权"必须与前端改造绑定发布，否则鉴权永远是死代码（S1/S7，`require_roles` 实测零调用）。
- `/fs/dirs` 任意绝对路径枚举 + `cors_origins=["*"]`，在"浏览器访问 NAS 上的服务"这一真实场景构成本机信息泄露面（S4）；`DELETE /data/all` 一个 query 参数全清库（S5）；`/wechat/send` 可冒充机器人向任意用户发消息（S3）。

**修改点**

1. 【修改】`api/app.py:752-766` 挂载策略改为 fail-safe：`secret_key` 缺省时启动生成随机密钥写入 `data/auth.json` 并将绑定地址退到 `127.0.0.1`；要对外服务必须显式配置密钥。
2. 【新增】`api/middleware.py`：以纯 ASGI 类重写 `_AuthMiddleware`/`_RateLimitMiddleware`，同时处理 `http` 与 `websocket` scope；WS 在 `accept()` 前校验 `?access_token=`，失败以 close code 1008 拒绝。
3. 【新增】`security/deps.py`：`CurrentUser` 依赖 + `require_roles(*roles)` Depends 工厂；【删除】`routes/memory.py:31-42` 自带的 `_check_roles` 重复实现。
4. 【修改】逐路由标注角色：`/data/all`（admin + body 回显确认串，替代裸 `confirm=true`）、`/wechat/send`、`/qq/*`、`/config/*` 全部写接口、`/fs/*`。
5. 【修改】`api/routes/fs.py:44-92`：新增 `fs.allowed_roots` 配置（默认仅工作区与 data 目录），realpath 前缀校验，杜绝任意目录枚举。
6. 【修改】`config/models.py`：`cors_origins` 默认从 `["*"]` 改为空（同源）；【修改】`routes/config.py:338-357` export 按密钥字段清单脱敏（清单最终由主题三修改点 8 的 `x_secret` marker 供数，过渡期手写）；手写清单必须覆盖端点 JSON 的 `api_key`（实测明文入库——S8/Δ7）。
7. 【修改】`routes/wechat.py:74-79`：`webhook_secret` 为空时启动生成随机值（不允许关签名）。
8. 【修改】会话归属：所有 repository 读写加 owner 过滤，第一版固定 `user_id="default"`；列本身走主题二迁移，本主题只改查询与仓储签名。
9. 【新增】前端 `api/auth.ts` + Settings 登录面板（口令换 JWT、token 持久化）；【修改】`App.tsx:32` WS URL 拼 `access_token`；HTTP 凭证统一经主题六 `api/client.ts` 注入。
10. 【修改】`docker-compose.yml`/`deploy/`：密钥注入指引（env-file，不入仓）；`docs/docker-deployment.md`、README 更新。

**收益**

- 默认部署从"裸奔"变为"默认关闭 + fail-safe"：NAS/内网暴露不再意味着任何人能读会话、烧 LLM、清库。
- 鉴权代码第一次变成活代码：可测试、可回归、CLAUDE.md 的承诺与实现对齐。
- owner 模型为多端/多用户演进（任务归属、按用户分区）留出结构接口。
- `/fs`、CORS、export、wechat 四类泄露/滥用面一次性收敛。

**影响**

- 破坏性：**高（接口契约级）**——所有 HTTP/WS 请求需携带凭证；后端与修改点 9 必须同批合入。实现顺序建议：先前端 client 注入（对无鉴权后端透明），再开后端 fail-safe，避免中间窗口 UI 不可用。
- 代码面：`security/`（+新文件）、约 15 个路由文件标注、app.py 中间件替换；`tests/test_api/*`（471 处引用）全部需 auth fixture——**本主题最大工时项在测试改造**。
- 数据面：conversations +1 列（主题二迁移）。
- 部署面：升级行为变化（无密钥→本机+随机口令），老部署需按 release note 重配 compose。
- 回滚：易——git revert 即回到无鉴权行为；auth.json 残留无害。

### 主题二：存储地基统一（对应 D1–D12、D3、A9 部分 ｜ Phase 0 部分小步 + Phase 2 主体）⚠️ **已回退未实施（2026-08-30，含本节全部 Alembic 方案，见顶部状态注记；schema 演进走 create_all + ensure_schema）**

**改动原因**

- **数据正确性已受损（实测，非理论）**：`PRAGMA foreign_keys=0` → 声明的 ON DELETE CASCADE 全部形同虚设，运行库实测 32 条孤儿轨迹 + 1 条孤儿 feedback；messages 以秒级精度 `CURRENT_TIMESTAMP` 排序且无 seq，同秒消息回放可乱序（D1/D2）。
- 同一 sqlite 文件约 5 套 engine（skills×2、config、repository、rag 各建各的，DB 样板 4 份逐行重复）；文件库用默认 QueuePool 而所有操作经 `asyncio.to_thread` 跨线程 checkout 连接——写锁/超时/线程策略在三套拷贝间漂移（D3）。
- 无迁移机制是主题一/三/五的**硬阻塞**：`user_id`、`seq`、`llm_endpoints`、`scheduled_tasks` 的建表加列都需要可靠演进通道；自研 `ensure_schema`（只加不删不改）已实证产生僵尸表 user_profiles/user_preferences 与列序漂移，RAG 又另写一套"检测列型→重建表"（D4）——两套土法演进都必须终止。
- 备份线最薄弱：`backup/manager.py` 全仓零引用（死代码），实际 `/data/export` 非原子写 JSON、域不全（缺 skills/feedback/system_config/RAG/向量）、SQLite+WAL 与 MEMORY/ 文件域间无快照点——"有备份"不等于"能恢复"（D5）。

**修改点**

1. 【新增】`alembic/`：init + baseline。[2026-08-29 细化 Δ1/Δ3] baseline **手写成"现网漂移态镜像"**（含 skills.created_at=TIMESTAMP、rag_documents 列序漂移），不用对目标 schema 的 autogenerate（否则把 D4 漂移固化成基线）；`include_object` 排除 `checkpoints`/`writes`（LangGraph SqliteSaver 私有）与 `simhash_index*`（sqlite-vec shadow）；收编其余 9+2 应用表与 raw-SQL `rag_chunk_fingerprints`（虚拟表在迁移内做幂等方言分支）；`alembic upgrade head` 由启动脚本/Docker CMD 显式执行，app 启动仅校验当前 revision、不符拒起。
2. 【修改】`repository/db.py:create_db_engine`：connect 事件统一 `PRAGMA foreign_keys=ON` + `journal_mode=WAL` + `busy_timeout`；sqlite-vec checkout 加载（rag/common/db.py:67）并入同一 engine 工厂。
3. 【删除】4 处自建 engine 样板（skills/repository.py:24-28、skills/composition_repo.py:23-27、config/config_repo.py:56、repository/feedback_repo.py:57）→ 构造函数改注入共享 engine/SessionLocal，样板照 trajectory_repository.py:27-29；注入点为主题三 container。
4. 【新增】迁移①：messages 加 `seq INTEGER` + 唯一索引 `(conversation_id, seq)`，回填用 `row_number() OVER (PARTITION BY conversation_id ORDER BY created_at, id)`；`get_messages` 排序改 seq；feedback 两列补 FK + 级联（conversation_id→conversations、skill_id→skills；[细化 Δ2：message_index 是会话内位置序号 INTEGER，不是 messages.id，勿挂错]）；trajectory_events 补 relationship 或依赖库级联。
5. 【新增】迁移②：孤儿行回填后删除（32+1 条留清单日志）、DROP 僵尸表；所有后续迁移带 `PRAGMA foreign_key_check` 门。
6. 【新增】迁移③索引：messages(conversation_id,seq)、feedback(conversation_id)、feedback(skill_id)、trajectory_events(event_type,created_at)；`messages_fts`（FTS5 external-content + 触发器），SearchEngine 关键词路径改 MATCH、LIKE 降为降级路径。[2026-08-29 细化实测 Δ8/Δ9：.venv=3.51.1、容器 python:3.11-slim≈3.40.1，满足 ≥3.35（FTS5/json_valid 探针已过），但须 CI 双解释器跑迁移 + 启动版本断言；unicode61 分词对 CJK 差 → LIKE 保留为降级主判据、trigram 列为可选增强，防中文召回回退]。
7. 【修改】时间统一：写入侧 `datetime.now(timezone.utc)`、server_default 保持 `func.now()`；[2026-08-29 细化 Δ4] 存量实测已是 UTC——**不做全库 UPDATE**，迁移只做"库内即 UTC"语义声明 + feedback 本地时间行留痕不纠（防无意义抖动与二次错）。
8. 【修改】JSON 化：trajectory_events.payload、skills.trigger_conditions/steps、skill_compositions.skill_ids → SQLAlchemy `JSON` + `CHECK(json_valid(...))`；100KB 校验下沉仓储基类统一。
9. 【新增】`repository/lifecycle.py`：`DataLifecycleService` 编排 `delete_conversation`（messages/trajectory/feedback/checkpoint/向量文档），`/data/all` 补全 skills/feedback/system_config/chroma 清理（修 D10 清理不彻底）。
10. 【重写】`backup/manager.py`（由死代码转为 `/data/export` 与恢复脚本的真实现）：SQLite Backup API 一致快照 + filestore 域 tar + `manifest.json`（VERSION、alembic revision、逐文件 sha256）；恢复按 manifest 校验、原子写。
11. 【修改】system_config 治理：迁移拆出 `llm_endpoints` 实体表（供主题三 EndpointRegistry；[`Δ10`] `models` 保留 JSON 数组单列不拆子表——元素异构（context_window 可为 null/"128K"）且天然按端点整体读写）；清理新旧并存键——[`Δ6`] 裸 `provider/model/base_url` 实测为异值死键（`load_from_database` 只读 `llm.*`），M4 一并删；[`Δ7`] 端点 `api_key` 明文入库且绕过 `_is_sensitive` → 导出/日志脱敏硬要求（S8，修 D11）。
12. 【修改】`repository/models.py:22-101` ensure_schema：降级为启动期"模型 metadata vs 库实际"漂移**只读告警**，不再执行 ALTER。
13. 【删除】仓库卫生：test_rag.db、thumbelina.db.bak 脱离跟踪；核查 `.gitignore` 覆盖 `*.db-wal`/`*.db-shm`/`*.tar`（3.2GB tar 见 §5.7）。
14. 【决策】不引入 PG/APScheduler/Celery（个人单机够用）；FileLocks 不跨进程 → "单写者"约束写入文档与 compose 注释。

**收益**

- schema 单一真相 + 可逆演进，主题一/三/五的列与表全部落在迁移轨道；"列序漂移/僵尸表/双份土法迁移"终结。
- 删除级联生效、孤儿清零（`foreign_key_check` 进回归断言）、消息回放顺序确定、主干查询 EXPLAIN 无 SCAN、搜索脱离全表扫描。
- 备份/恢复从"可能写一半的 JSON"升级为"校验和 + 域完整 + 可验证"，个人数据项目最重要的兜底。
- 5 套 engine 归一：跨线程连接隐患与写锁策略漂移消除。

**影响**

- 破坏性：中——API 不变、库结构变；新结构对旧代码**向后兼容**（列与表均为增量，升级安全），降级受 alembic revision 限制。
- 数据面：对现存库一次性真实迁移——上线前全量备份 + 在 db 副本演练一遍迁移。
- 代码面：repository/skills/config/rag 全部仓储构造与 close 路径；`tests/` fixture 需共享 engine + 迁移执行路径（repository/agent 测试域引用量大，改造集中于此）。
- 部署面：启动流程多一步 `alembic upgrade head`（建议 compose command 而非进程内）。
- 回滚：**难**——代码可 revert，但数据迁移（seq 回填、孤儿删除）不可逆，依赖迁移前快照。
- 依赖：engine 注入需要主题三的装配点；建议"容器骨架"先行、本主题拆为多个迁移 PR 跟进。

### 主题三：依赖解环与装配统一（对应 §1.3、A1、A8、B2、B3、B9 ｜ Phase 3，容器骨架建议 Phase 2 并行起步）

**改动原因**

- ast 实测 8 模块运行时 SCC `{api,agent,analysis,channels,config,llm,skills,subagents}`（剔除 TYPE_CHECKING 边后仍成环）、分层违例 21 条——现状下任何"只动一层"的修改实际都动 8 个模块，是主题四/五/六所有拆分的安全前提。
- 热切换漏接线 P0（A1）正是环的产物：没有"谁持有 provider"的统一机制，只能靠 4 处手工接线（graph.py:598-639、runtime_manager.py:92-102、routes/config.py:248/574、app.py:578-586），漏一处即静默错模型。
- 装配不可控：`api/app.py` 820 行 lifespan 直引 18 模块、25 个 app.state 松散属性、**无 try/finally**（中途失败 engine/checkpointer/线程全泄漏）、5 个子系统 init 失败被 `logger.debug` 吞、反向 import 路由私有全局 `_qrcode_manager`；`cli/chat.py` 手工复制 8 模块装配且缺件（B9）。
- 配置三处真源（B3）：YAML→DB 一次性导入后**永久跳过**（改 YAML 无效），启动与热切换还回写用户 YAML（丢注释、固化 `${ENV}`、清空密钥）——"配置文件驱动"的语义已经破产。
- 对 rag 的 7 处反向 import 中 6 处只为 `estimate_tokens/context_formatter` 一个符号——全仓最便宜的解环机会。

**修改点**

1. 【新增】`container.py`：`AppContext` dataclass（全部子系统句柄）+ `build_xxx(cfg) -> tuple[obj|None, err|None]` 工厂族 + `AsyncExitStack` 统一注册关闭；`build_app_context(cfg) -> (AppContext, degraded_list)`。
2. 【修改】`api/app.py`：lifespan 重写为 ~50 行（build → 注入 `app.state.ctx` → 启动尾打印 degraded 清单）；子系统 init 失败日志 debug→warning 且带影响面；路由经 `api/deps.py` 的 `get_ctx`/`get_xxx` Depends 取上下文——【删除】25 个 app.state 直读与 9 处函数级 lazy import；禁止触碰私有属性（`_qrcode_manager` 归位渠道管理器、`agent._rag_*` → 显式 `attach_rag()`）。
3. 【修改】`cli/chat.py`：复用 `build_app_context`，只保留 REPL（修 B9：CLI 内 `schedule_task` 等静默无效消失）。
4. 【新增】`llm/aware.py`：`ProviderAware` Protocol（`update_llm(provider)`；memory extractor 已有同名方法，统一命名）+ `ProviderRegistry`（构造期自注册）；`swap_provider` 收敛为单点 fanout——【删除】A1 的 4 处手工重接线。
5. 【修改】切断 4 条运行时环：
   - `config/models.py:10 → channels`：config 模型改纯字段 dataclass/pydantic，不 import 渠道具体类；
   - `config/runtime_manager.py:12 ↔ llm/endpoint_manager.py:11`：runtime_manager 只依赖 `LLMProvider` ABC 与工厂函数（`create_provider` 移入 `llm/factory.py`）；
   - `channels/wechat_channel.py:330 → api.routes.chat`：`channels/base.py` 定义 `ChannelCallback` Protocol，装配时注入 chat 服务实现，反向边删除；
   - `llm/preset_manager.py → agent`：`activate_preset` 改返回 `ActivateIntent`（provider 规格），执行上移 runtime_manager/container——llm 层不再反向驱动 agent（修 A8）。
6. 【合并】`PresetManager`+`EndpointManager` → `EndpointRegistry`（持久化走主题二 `llm_endpoints` 表，返回领域对象，删逐字段 `_to_response` 复制）；【移动】HTTP 视图模型转换归 `api/schemas.py`；【移动】`_LazyLLMProvider`（app.py:166-213）→ `llm/lazy.py` 并真正继承 `LLMProvider` ABC。
7. 【新增】`util/tokens.py` + `util/context_fmt.py`：从 `rag/retrieval/context_formatter.py` 上提共享符号；【修改】memory/agent/compression 7 处 import——rag 出度归零成纯叶子。
8. 【修改】配置单一真源：`config/models.py` 每个 Field 打 `x_hot/x_persist/x_secret` marker；【重写】`runtime_manager.load_from_database` 为 marker 驱动遍历（删 64 行手写 if）；`export_to_dict` 按 marker 自动脱敏（与主题一修改点 6 合流）；【修改】`persistence.py` 只写受管片段 `thumbelina.state.yaml`，用户 YAML 只读；优先级显式化为 `env > DB > state.yaml > YAML > defaults`，`/config` 响应带每字段来源回显。
9. 【修改】RateLimiter 构造时机移到 `load_from_database()` 之后（修"DB 限流配置永不生效"）；或明确声明"启动期-only"并从 `POST /config` 白名单移除（推荐后者，单实例场景简单优先）。
10. 【修改】渠道热切换统一走 `build_channel(cfg, callbacks)` 工厂（runtime_manager.py:212-216 与 app.py:624-631 共用一份），B4 的 runtime/callback 丢接线结构性消失。
11. 【修改】`pyproject.toml`：补 botpy/sentence_transformers/torch/huggingface_hub 声明（归入对应 extras）；【删除】llama-index×3、pydantic-settings、python-multipart 死依赖；【删除】`src/thumbelina/.claude/` 包内脏物。

**收益**

- 依赖图无环：分层可独立测试与重构，主题四/五/六在安全区内动工。
- "新增子系统"从改 5+ 处收敛到 container 一处注册；热切换漏接在结构上不可能发生（A1 根治）。
- 启动失败可见（degraded 清单）、不泄漏（ExitStack）；CLI 与 API 行为对齐。
- 用户 YAML 永不被污染；配置来源可查询；密钥脱敏与导出共用同一 marker 清单（一处声明三处生效）。
- 安装体积收缩（llama-index 链移除），绕环的函数级 import 补丁随环消失。

**影响**

- 破坏性：低中——对外 HTTP/WS 契约不变；内部构造签名大改（api 22 个文件的 app.state 引用机械替换）。
- 代码面：全部子系统装配点、cli、conftest（TestClient 经 lifespan 注入的模式不变，fixture 改注入 AppContext）、llm/config/channels import 面。
- 数据面：仅 `llm_endpoints` 表拆分（走主题二迁移）。
- 部署面：行为变化——热切换结果的持久化从"回写 YAML"迁到 state.yaml + DB；老用户需知悉手改 YAML 在优先级链中的新位置。
- 适配成本：ProviderAware 要求 4–6 个 provider 持有者（agent/extractor/compressor/namer/subagent manager）实现 `update_llm`，一次性。
- 回滚：中——纯代码可整体 revert；但 state.yaml 拆出后旧代码不再读该层，回滚需配迁移小工具。
- 依赖：与主题二互为前提（engine 注入需要容器落点）；主题四 ToolProvider、主题五 build_channel 都以本主题的 container 为载体——**排期上容器骨架最先**。

### 主题四：Agent 核心演进（对应 A2–A7、A9–A11 ｜ Phase 4）

**改动原因**

- `agent/graph.py` 1407 行占核心层 49%：`__init__` 16 参数、`clone()` 逐参数复制并整图重编译、4 套 `_make_*` 与 memory 一套双风格、还要靠去重补丁维持（566-572 注释自认"否则重名 LLM 400"）——每个新特性都落在这个文件，演进摩擦第一名（A6）。
- 三颗**已实证**的正确性炸弹，全部源于复制粘贴式结构：① run/stream 前言、usage、收尾三段复制已漂移——非流式路径丢 `reasoning_content`（A4）；② 工具异常吞成字符串再 `startswith("Error")` 反推失败，正常输出以 Error 开头即误判（A5）；③ 消息状态写回算法与压缩不变量拆在两文件、`repaired is messages` 用 `is` 判等当跨文件契约（A3，P0）——极易造成重复/丢失消息。
- 子代理取消是假的（A2，P0）：`cancel_agent` 只改 status，协程继续跑并在结束时覆写 COMPLETED，API 返回值撒谎；`run_agent` 不跟踪 Task，`_agents` 只增不减（内存单调增长）——"长任务管理"能力整体不可信。
- LLM 抽象不兑现（A7/A8）：3 个 provider 中 2 个的 `list_models/speed_test` 直接 `NotImplementedError` 冒到 HTTP；流式 reasoning/usage 靠 OpenAI 子类运行时 monkey-patch + agent 层特判——新增 provider 或思考模式要穿三层。
- 学习闭环是幌子（A9/A10）：`SkillExtractor`/`record_usage`/`suggest_compositions` 零调用方；每轮 `list_all()` 全表 + N+1 调分、结果只用 `matches[0]`；`prompts/` 仅 42 行空壳、8+ 处 prompt 散落硬编码（含英文一份）——宣称的技能学习系统实际未接线。

**修改点**

1. 【新增】`agent/context.py`：迁 graph.py:63-202（工作区上下文、`_strip_markdown_syntax`、`_extract_chunk_parts`、`_messages_state_update`、`_is_ordered_subset`）与 1061-1103 memory 注入格式化。
2. 【新增】`agent/compression/state_update.py`：消息状态增量写回唯一归属（与配对不变量同处）；graph 只调用返回 RemoveMessage 列表的函数签名——【删除】graph.py:768 `is` 判等契约（A3 根治）。
3. 【新增】`agent/deps.py`：frozen `AgentDeps`（16 参数收敛）+ `TurnContext`（conversation_id 等每轮可变量）；`clone()` = `dataclasses.replace(deps, ...)` + **复用已编译 graph**（同时修掉每请求 compile 的 P2）。
4. 【新增】`agent/tools_registry.py`：`ToolProvider` Protocol（`build(AgentDeps) -> list[BaseTool]`）+ `ToolRegistry.register(name, factory)`；迁移 4 套 `_make_*` 与 `make_memory_tools`；【删除】去重补丁与 `_remember_tool` isinstance 反查（566-578）；注册动作挂主题三 container。
5. 【修改】run/stream 合并：`_begin_turn()/_finish_turn(text, reasoning, usage)` 共用前言/usage/收尾，同时修 run 丢 reasoning（A4）；`_maybe_auto_name` 的 create_task 补 done_callback（A11）。
6. 【修改】`agent/nodes.py:88-94`：工具异常改 `ToolMessage(status="error")`（LangChain 原生语义），【删除】`startswith("Error")` 字符串协议（A5）。
7. 【修改】`agent/state.py`：State 增 `conversation_id`/`context_window_tokens` 并在节点入口校验，替代 `config.configurable` 走私（graph.py:688-701、822-825）。
8. 【新增】`llm/stream.py`：`StreamDelta(text, reasoning, tool_call, usage)`；`LLMProvider.stream()` 改 yield StreamDelta——openai.py:28-80 的子类 patch 与 graph.py:117-154 的 agent 特判【下移】进各 provider；anthropic/ollama 补实现，三条分裂路径归一。
9. 【修改】`llm/base.py`：`list_models`/`speed_test` 从 abstractmethod【降级】为 `ModelListing`/`LatencyProbe` 可选 mixin，endpoint_manager 按 `supports()` 判断（NotImplementedError 不再冒到 HTTP）；ollama `__init__` eager 构造 `ChatOllama` 改惰性（对齐 lazy-provider-creation 假设）。
10. 【修改】`subagents/manager.py`：维护 `{id: asyncio.Task}`，`cancel_agent` 真 `task.cancel()` + 状态修正 + done 回调（复用 extractor 的回调模式）；`_agents` 终态 TTL 清扫（A2 修复）；【删除】`subagents/types.py`、`MessageQueue`、Monitor/Worker 私有 `SharedState()`（若保留则改 manager 持有并真共享）。
11. 【删除】`analysis/title_summarizer.py`（零引用且与 ConversationNamer/ContextSummarizer 命名撞车）。
12. 【新增】`prompts/<subsystem>/<name>.md` + `load_prompt(name, **vars)`（沿用 roles.py 的 importlib.resources 机制）；迁移 compression/skills×3/namer/subagents/memory extractor 等 8+ 处硬编码，subagents 英文份统一中文。
13. 【决策】skills 二选一：推荐【删除】`SkillExtractor`/`record_usage`（学习闭环宣称从 CLAUDE.md/README 撤下，接通另立产品评估）；无论取舍，`find_matching_skills` 改批量取反馈 + 关键词倒排预索引 + top-k 注入（替代全表 N+1 只用 matches[0]）；仓储注入走主题三。

**收益**

- graph.py 1407 → ~300–400 行；新增子系统工具从"改 5+ 处"到"注册 1 项"；clone 从每请求重编译图降为 dataclass 替换。
- 三处正确性问题同时消除：非流式丢思考、工具错误误判、取消谎报；消息写回不变量获得唯一归属与单测抓手。
- 流式协议统一后，新 provider / 思考模式 / usage 统计只改 provider 层——llm 抽象第一次名副其实。
- 净删约 600+ 行死代码；prompt 文件化后可审计、可 diff、可翻译。

**影响**

- 破坏性：低中——Agent 对外 run/stream 签名基本不变；但 `stream()` 协议变更**破坏 plugins 中 PROVIDER 类型第三方兼容**（本仓无外部 provider，changelog 注明即可）。
- 代码面：agent 14 文件、llm 9 文件、memory/tools、api 的 chat/websocket 分发面；clone 语义变化需复核 chat.py:119 / websocket.py:195 的每连接隔离。
- 测试面：全仓最重测试域随拆分迁移（agent 656 / llm 360 引用行）；**必须先补行为回归网**——多轮工具调用、中断 stop、压缩触发、思考流、会话切换并发五场景集成测试，现有 conftest 的 mock 面可能不足。
- 节奏：严格拆 3–5 个小 PR（①context/state_update ②deps/registry ③run-stream 合并 ④provider 协议 ⑤死代码+prompts），避免单发大爆炸。
- 回滚：中——纯代码可 revert；PR 间交叉 import 决定回滚需按序。
- 依赖：主题三的 ProviderRegistry/ToolRegistry 机制先决；A1 的根治由主题三四共同完成。

### 主题五：基础设施正确性（对应 B1、B4–B8 ｜ Phase 0（调度真执行最小步）+ Phase 5 其余）

**改动原因**

- 调度器是产品卖点但当前是**演示态**（读码复核 app.py:404-413）：`_on_due_task` 只广播一条"task_completed"通知、不执行任何任务；且 `NotificationManager.subscribe()` 全仓零调用方——连广播都没人收；任务全内存 dict，重启即蒸发（B1，P0）。
- 渠道层双事件循环（botpy daemon 线程内跑第二个 loop 且跨 loop 用主 loop 的 `asyncio.Event`）、`send_message` 是只打日志的空实现、共享 `agent.run()` 无 per-conversation 锁——与 HTTP/WS 交错读写同一 checkpoint，可写脏会话状态（B5）；渠道热切换丢 `runtime=`/callback 参数，切完微信静默退化（B4）。
- 插件系统自欺：manager 有 loader 时提前 return，其后 120 行拓扑排序是死代码，`/plugins/dependencies` 恒返回空图；沙箱 `strict=False` 默认、`os` 不在黑名单、`"exec*"` 字面量前缀永不匹配——看起来有防护，实际没有（B6）。
- 两个 God router（config 806 行/21 路由、rag 802 行/15 路由）在路由内裸 SQL（rag.py:221）、手写流式落盘、跨层调私有方法 `_persist_to_db`；错误形状 422/500/502/503 混用、`RuntimeError("RAG not initialized")` 冒 500——前端拿不到稳定契约（B7）。
- 部署面三源漂移：版本（VERSION v0.0.1 vs pyproject 0.1.0）、dev 与 Docker 入口分裂、日志目录不在容器卷——部署不可复现（B8）。

**修改点**

1. 【修改】`scheduler/scheduler.py`：注入共享 SessionLocal；任务持久化 `scheduled_tasks` 表（id/description/scheduled_at/condition_type/condition_args/status/conversation_id/last_result，建表走主题二迁移）；启动 recover PENDING 未过期；终态 TTL 清扫。
2. 【新增】任务执行链：`_on_due` → `agent.clone()`（经主题四 AgentDeps 构建）+ per-conversation 锁 + `apply_conversation_runtime` → 真执行 → 结果落库并广播（B1 根治）。
3. 【新增】`scheduler/triggers.py`：条件 checker 注册表（`{"file_changed": …, "http_status": …}`，app 装配期注入实现），`check_condition` 从注册表取，替代裸字符串回调。
4. 【决策】`notifications.py`：删除 `subscribe()` 孤儿接口，广播并入 `api/websocket.py` 的真实连接表（或保留模块但重写为 WS 薄适配器）。
5. 【修改】`channels/qq_channel.py`：`_handle_message` 改 `asyncio.run_coroutine_threadsafe(…, main_loop)` 桥接（先原型验证 botpy 线程模型；若 SDK 支持直接在主 loop 起任务则更优）。
6. 【新增】`channels/base.py: dispatch_incoming()` 模板方法：clone + per-conversation 锁 + apply_runtime + 调 chat 共享服务（对齐 chat.py:274-296 三入口，QQ 就此不再绕路）；`send_message` 不支持抛 `NotSupportedError`；【修改】wechat poll 循环内 create_task 并发处理、`_sync_buffer` 处理成功后才推进（at-least-once）。
7. 【修改】plugins：`PluginSandbox(strict=True)` 默认（`plugins.sandbox_strict` 可降回 advisory）；黑名单修复——补 os/subprocess/shutil/socket/ctypes、前缀匹配改 `startswith(("exec","spawn","system"))`、加 dunder 属性链检查；【删除】manager.py:145-265 重复加载路径（拓扑排序移入 SandboxedPluginLoader）→ `/plugins/dependencies` 输出真实图；文档明确安全定位："白名单 + 拓扑排序，非对抗性隔离"。
8. 【修改】路由治理：`routes/config.py` 按资源拆四文件（config_system / llm_endpoints / llm_presets / config_channels）；rag 路由编排（chunk/去重/索引/临时文件）【下移】`rag/application/service.py`，路由只做 DTO↔service；【删除】路由内跨层私有调用；tools.py 并入 config 命名空间。
9. 【新增】`api/errors.py`：`AppError` 异常层级 + 全局 handler 统一输出 `{error:{code,message,details}}`；"RAG not initialized" → 503；建立错误码语义清单（422 校验 / 503 降级 / 502 上游 / 500 bug）。
10. 【修改】部署面：VERSION 唯一版本源（pyproject dynamic + `importlib.metadata`，Dockerfile `ARG APP_VERSION` 构建期注入）；入口统一 `thumbelina.main:create_app`（dev 加 `--reload`）；日志目录 `data_dir/logs` 并入 compose 卷；`config.logging` 段实现或删除；根目录 `diagnose_wechat.py`/`reset_wechat.py`【移动】至 `scripts/`。

**收益**

- 定时任务从"演示"变"可用"：重启后真执行、结果可查可推送——本主题回收整个卖点功能。
- HTTP/WS/渠道三入口一条 chat 管线，checkpoint 不再交错脏写；渠道热切换不再静默退化。
- 插件依赖视图变真；沙箱从仪式到"至少防手滑"且定位有文档共识。
- 前端获得可预期错误契约（供主题六统一消费）；版本/入口/日志三件事单源，"本机好使容器死"类问题收敛。

**影响**

- 破坏性：中——路由文件拆分不动 URL；**错误形状变化破坏前端现有解析**（`detail` → 结构化），必须与主题六第 5 条同批；调度从"只广播"到"真执行"后，存量 PENDING 任务上线即开始调用 LLM（成本与副作用须在 release note 说明，上线前人工清一遍存量）。
- 数据面：`scheduled_tasks` 新表（主题二迁移建）。
- 代码面：scheduler/channels/plugins/rag、api 两文件；测试补调度 recover、triggers 注册表、沙箱黑名单 case。
- 风险：QQ 桥接方案依赖 botpy 实现细节（先原型）；错误形状变更需清点前端全部解析点。
- 回滚：中——代码可 revert；scheduled_tasks 表保留无害。
- 依赖：修改点 1/2 被主题二（表）与主题三（装配）阻塞；修改点 9 供主题六消费；调度"最小可用执行链"可在 Phase 0 以临时手工方式先落地（不等表）。

### 主题六：前端工程化（对应 F1–F6 ｜ Phase 0（F1）+ Phase 5 其余）

**改动原因**

- F1 是**最严重的用户可见故障且修复面最小**（读码复核）：`onclose/onerror` 只置位不重连（useWebSocket.ts:490-508），effect 依赖 `[url]` 且 url 恒定 → 断线一次页面永久失能；`sendMessage` 非 OPEN 时整段 if 无 else（533-567）→ 连用户自己的消息都不显示，静默消失；打字机 interval 只在卸载清理（510-512）→ 断线时半截文本 + 悬挂定时器。
- 无 store/无 Router：App.tsx 是唯一状态中枢，CoderPage 一次透传 15 props（[细化复核 D2]），ws 对象逐层下钻；11 个页面全进主 bundle（F2）。
- API 层 3 套封装 + 9 组件绕过 api/ 裸 fetch 共 27 处（[细化复核 D9]：组件 25 + App.tsx:124 + useWebSocket.ts:589；ChannelsPage 独 8 处），错误处理 3 套写法并存（吞 / 置空 / Toast）——主题一的凭证注入与主题五的错误契约没有统一落点（F3）。
- 类型手写对齐后端（`WsIncoming` 实测仅一份内联，但 `connected` 帧是后端从不发送的死分支——[细化复核 D3]）、tsconfig **未开 strict**（[细化实测 D8]：`--strict` 单独 0 报错，真实债在 `noUncheckedIndexedAccess` 的 107 处、100 处位于测试文件）——后端字段改名编译零感知（F4）；TodoPage 1105 行/18 useState、KnowledgeBasePage 970 行/30 useState 两座巨石，Modal 已有通用件却仅 1 处使用、另两份复制各写关闭逻辑（F5）。

**修改点**

1. 【新增】`hooks/useWsConnection.ts`：显式连接状态机（connecting/open/reconnecting/closed）、指数退避重连（1s→30s 封顶）、重连成功与 `visibilitychange` 回前台时 `loadHistory` 对账；【新增】`hooks/useStreamBuffer.ts`（chunk 缓冲 + 打字机 + stopGeneration）+【新增】`state/wsReducer.ts`（消息 reducer 纯函数）；682 行 useWebSocket 拆分，现有多会话隔离设计（sessionConvRef/historyFetchRef/completedContentRef）**原样保留迁移**进新模块。[D4] 心跳不可纯前端闭环：实现"被动判活三件套+对账"，`heartbeat?: …|null` 钩子预留，WS ping 归主题五、不阻塞 Phase 0
2. 【修改】`sendMessage`：非 OPEN 时入队重发 + UI"离线重连中"态；打字机定时器在 onclose 即清理（F1 三患同修）。
3. 【移动】`WsIncoming` 与消息形状类型 → `types/ws.ts`，并与后端 WS schema 做对齐单测（契约测试）。[D3] `connected` 帧为后端未发送的死分支：reducer 保留 `ws/connected` action 加单测并注释"后端未实现"，默认会话真实路径是 `conversation_created`
4. 【新增】`state/ConversationContext.tsx`：会话列表/selectedId/CRUD 回调 Provider 化，与 Locale/Theme 并列（[D5] 现状并无 ThemeContext——主题在 ThemeToggle.tsx:24-35 局部实现，需并行抽出 ThemeProvider 作为 ConversationProvider 外层前置）；App.tsx 收缩为组合壳；CoderPage 15 props（实测） → context；chat/coder 两分支的重复接线合并。
5. 【新增】`api/client.ts` 单例（baseURL、凭证注入〔经 AuthBridge 与主题一解耦，可先合〕、错误规范化〔消费主题五 `{error:{code,…}}` 形状〕、401 → 登录引导、超时）；【修改】conversations.ts/rag.ts 改用之；【移动】27 处裸 fetch 逐文件迁移（[D9] 组件 25 + App.tsx:124 + useWebSocket.ts:589），顺序：ChannelsPage(8) → MemoryViewer(4) → Tasks(4) → ChatWindow/SettingsPanel/Plugins(各 2) → 其余；完成判据：`grep -n "fetch(" frontend/src/components frontend/src/App.tsx frontend/src/hooks` 零命中。
6. 【新增】类型归口：TodoItem/LLMEndpoint/UploadTask 等全部收进 `types/`；引入 `openapi-typescript` 从后端 openapi.json 生成 API 类型 + `npm run gen:api`；【删除】手写重复接口。[D10 实测] /openapi.json 可用（app.py:728 未关，且 :64 鉴权白名单已含）：75 paths/93 ops/72 schemas，79 个 op 已类型化先覆盖；16 个弱类型恰集中在 memory(6)/wechat(5)/trajectory(2)/rag 上传(3)——补 `response_model` 登记为对主题五的显式前置需求
7. 【新增】`components/ui/Modal.tsx`（overlay + focus trap + ESC + portal 唯一实现）；【修改】TrajectoryDetailModal、WorkspacePicker 改用（三份关闭逻辑合一）；【拆分】TodoPage → 容器(TodoPage)/TodoList/TodoEditor/TodoStatsBar；KnowledgeBasePage → 容器/文档列表/上传队列/检索面板。[D1/D11] TodoPage 拆分定性"按职责切 6 文件+去重复制段"（估 1.0d）；KBPage 为"30 state 重新归属切 7 文件"；两者与 Settings/Modal 零测试覆盖，拆前先补测
8. 【修改】`tsconfig.app.json`：两阶段拆分（[2026-08-29 细化实测 D8] 原"一次性还 null 检查债"口径反转——`--strict` 单独 0 报错；107 处全部来自 `noUncheckedIndexedAccess` 且 100 处在测试文件）：① `strict: true` 立即合入并给 CI 加显式 typecheck 步骤；② `noUncheckedIndexedAccess` 随测试迁移还债（细化任务 T6-20）。
9. 【修改】样式：App.css（5790 行）按页拆入 `styles/pages/*.css`；清 15 处硬编码色值改用主题变量（修正 warm 主题不跟随）；【修改】Sidebar 以 `'微信Clawbot'` 中文字符串匹配默认会话 → 改会话稳定标识字段（[细化 §6.3 推荐] `system_key` 派生字段方案可零迁移；如需实体列则走主题二迁移）。
10. 【决策】Router 深链：react-router 7 + `React.lazy` 按页分包**仅在出现深链/分享需求时引入**（非本轮目标；第 1/4/7 条拆分已为其铺好结构）。
11. 【新增】测试：wsReducer 单测、useWsConnection 重连状态机测试（mock WebSocket）、client.ts 错误归一测试；现有 38 个 test 文件随拆分迁移。

**收益**

- 消除 #1 用户可见故障：断线自愈、消息不丢、无悬挂定时器——改动小收益立现（这就是它排在 Phase 0 的原因）。
- 鉴权、错误、重试、日志四件事在 client.ts 一次落地：主题一/五的契约不再需要在 27 处各自抄写。
- 类型有编译期保护（strict + codegen）：后端字段变更即刻报错，杜绝静默漂移。
- 两个 1000 行页面变可维护；Modal/ui 体系与页面拆分为未来组件复用与（可选的）按页分包铺路。

**影响**

- 破坏性：低——前端内部为主；唯一产品级变化是登录界面（主题一配套），需确认 UX。
- 风险：**WS 重构是最大单点**——必须回归"流式中 / 切换会话 / 断线重连"三场景并保留 DB 写竞态补偿逻辑（completedContentRef）的行为等价性；先 reducer 化再动连接层，分两步 PR。
- 代码面：hooks/state/components/api 约 30 文件；类型归口触及全部消费方（机械修改）。
- 时序：第 5 条经 AuthBridge 与主题一解耦（同版本即可，不必同批）；第 6 条 16 个弱类型 op 与第 1 条心跳依赖主题五协议面，登记需求、不阻塞合入；第 1–3 条（F1）无依赖、Phase 0 先行。
- 回滚：易——纯前端静态资源，可独立回退。

---

## 4. 优先级与实施路线图

> 排序原则：安全与正确性止血 → 数据地基（其他一切改动要过迁移）→ 依赖解环（让分层重构变安全）→ 巨石拆分与死代码 → 工程打磨。工作量以"单人专注日"粗估。（2026-08-29 修订：Phase 0/2/5 工时已按两份细化文档实测口径修正；主题一/三/4 尚未细化拆解，其数字仍为粗估，细化后同样回写）

### Phase 0 — 止血（P0 正确性/丢数据，约 9–13 日 [修订：前端 F1 实测 7.0d + 存储小步 2.0d，其余 A1/A2/A3/B1/D3 粗估]，可并行）
- A2 子代理真取消 + TTL 回收
- B1 调度持久化表 + `on_due_task` 真执行 + notifications 接线
- A1 ProviderAware 注册表收口热切换（4 处改 1 处）
- F1 前端 WS 重连/发送队列/定时器清理
- D2 messages 加 seq 并回填（先走手工脚本，Phase 1 归入迁移）
- D1 `PRAGMA foreign_keys=ON` + 孤儿行回填 + trajectory relationship 补级联
- A3 状态写回算法收进 compression 单模块，删 `is` 判等契约
- D5/A9 skills 等 4 处自建 engine 收敛为注入共享 engine（D3 的前置小步）

### Phase 1 — 安全边界（P0 安全，约 5–7 日，依赖 Phase 0 的 seq/迁移雏形）
- S1 鉴权 fail-safe + compose 注入密钥 + 前端 Authorization/access_token
- S2 纯 ASGI 中间件覆盖 WS + accept 前验 token
- conversations 加 `user_id` 列 + 全部读写按 owner 过滤（数据与接口改造绑定）
- S3/S4/S5 wechat/fs/data 三类裸奔接口逐个挂 `require_roles`；CORS 收敛；S6 export 脱敏
- **验收**：docker-compose 默认起法下匿名请求所有写接口 401；WS 断网 30s 自愈；重启后未过期任务继续执行。

### Phase 2 — 数据地基（约 24 日 [修订：主题二 32 任务合计 29.0 人日，扣除预置 Phase 0 的 2.0d 与合流主题三的骨架 3.5d]）
- Alembic baseline 收编全部表（含指纹/虚拟表方言）、DROP 僵尸表、schema 漂移告警替代 ensure_schema
- FK/索引一次补齐（D6 清单）；UTC aware 统一；JSON 列类型化 + CHECK；`llm_endpoints` 出 KV 表
- FTS5 external-content 搜索；DataLifecycleService 统一删除/导出/备份（Backup API 快照 + manifest）；`/data/all` 完整清理路径
- 仓储层 async 包装归一（一处装饰器）
- **验收**：`alembic upgrade/downgrade` 双向可跑；EXPLAIN 无 SCAN；备份→恢复→行数一致。

### Phase 3 — 依赖解环与装配（约 5–8 日，建议与 Phase 2 并行启动只读改造）
- 切 4 条最小环（主题三·修改点 5）；`estimate_tokens/context_formatter` 上提使 rag 成纯叶子
- container.py + AppContext + AsyncExitStack；cli 共用 build_agent；B2 吞错降级→warning+degraded 清单
- B3 配置声明式 marker 化、停写用户 YAML；RateLimiter 生效链修复
- pyproject 依赖补删；版本/入口/日志/根目录清理（B8、§1.3 脏物）
- **验收**：无 SCC（pytest 前后 ast 扫描归零）；新增子系统只改 container 一处。

### Phase 4 — 巨石拆分与死代码（约 8–12 日，依赖 Phase 3 的注册表机制）
- graph.py 拆分（context/state_update/deps/TurnContext）；ToolProvider 注册表；run/stream 合并（A4/A5 一并修）
- LLM 层：StreamDelta 统一、LazyProvider 归位、Endpoint/Preset 合并（A7/A8）
- 死代码清除：A10 清单 + backup 模块去留决断 + plugins 双加载器归一（B6）+ prompts 迁移
- QQ 渠道主循环桥接 + Channel dispatch 收敛（B5）
- **验收**：graph.py <400 行；`ruff/mypy/pytest` 全绿且行为回归通过；`/plugins/dependencies` 返回真实图。

### Phase 5 — 前端与体验打磨（约 17.5 日 [修订 D7：主题六 25 任务实测合计；必须压缩时砍序：T6-25 决策门→T6-18/19 CSS 色值→T6-24 打字机→KBPage 拆分延后]）
- ConversationContext + Modal 提升 + 巨石页面拆分
- api/client.ts + 27 处裸 fetch 迁移（实测口径，见 D9）+ openapi 类型生成（凭证经 AuthBridge 注入，与主题一"同版本"即可、不必同批）
- tsconfig strict、路由/lazy、App.css 拆分与硬编码色清理
- 打字机渲染 memo 化/虚拟化
- **验收**：`tsc --noEmit` strict 绿；bundle 按页分包生效。

### 优先级速查

| 优先级 | 问题编号 | 说明 |
|---|---|---|
| P0（Phase 0/1） | S1–S5, D1–D5, A1–A3, B1, F1 | 安全裸奔、假取消、任务空转、消息乱序、孤儿数据、多引擎、无迁移、备份不一致、WS 断线失联、热切换漏接线 |
| P1（Phase 2–4） | S6–S8, D6–D11, A4–A10, B2–B7, F2–F5 | 架构债主体：God 文件/路由、配置三真源、双渠道循环、抽象不兑现、状态管理缺失 |
| P2（Phase 5+/长期） | D12, A11, B8–B9, F6 + 各层小项 | 工程卫生，随改动顺手做，不单独立项 |

---

## 5. 风险与开放问题

1. **FK ON 的历史包袱**：开启 `PRAGMA foreign_keys=ON` 前必须先回填/删除孤儿行（已实测 32+1），否则旧查询报错；迁移脚本需带 `PRAGMA foreign_key_check`。
2. **`user_id` 改造的接口面**：会话归属引入会触及 conversations/scheduler/channels/备份全链路，建议先在单用户语义下"固定 default 用户 + owner 过滤"，角色模型后置。
3. **Alembic baseline 的现场风险**：运行库有 WAL 与列序漂移，baseline 前停写并以 Backup API 快照；sqlite-vec 虚拟表在迁移中用方言分支处理，勿 `create_all`。
4. **热切换语义变更**（preset 只发意图）影响 `/config/llm` 路由响应形状，前端需同步。
5. **学习闭环去留**（skills 接通 vs 删除）是产品决策而非纯技术决策——建议先删除死链路，接通另立需求评估其对个人助手的真实价值。
6. **调度器不引入 APScheduler** 的前提是可接受轮询精度（秒级）；如未来要多实例，需先解决 FileLocks 不跨进程与单写者约束。
7. 3.2GB `thumbelina-amd64-latest.tar`、`test_rag.db`、`.venv` 内的构建产物建议尽快确认 git 跟踪状态（当前 `git status` 干净，tar 已 3GB+，疑似仓库体积隐患，值得单独核查 `.gitignore`/history）。
8. [细化新增·协议缺口登记] WS 心跳与"连接时报告默认会话"后端均未实现（`connected` 帧死分支）：前端已按被动判活+`conversation_created` 真实路径闭环止血，正式方案（WS ping/pong、connected 帧）归主题五协议面，各附跨主题 issue 追踪。
9. [细化新增·版本矩阵] .venv SQLite 3.51.1 与容器 python:3.11-slim ≈3.40.1 版本漂移（且 pyproject requires-python>=3.11 vs mypy 3.13）：迁移与 CI 需双解释器矩阵，应用启动加 `check_sqlite_version>=3.35` 断言（FTS5/json_valid 前提）。

## 附录 A：评审覆盖与证据说明

| 域 | 评审对象 | 取证方式 |
|---|---|---|
| 核心 Agent 层 | agent/llm/tools/prompts/skills/subagents/analysis | 逐文件阅读 + 行数统计 + 全仓 grep 引用验证死代码 |
| 数据层 | repository/rag/memory/todo/filestore/backup + 运行库 | ORM 源码 + `mode=ro` 实查（表 DDL、PRAGMA、EXPLAIN、孤儿行 JOIN） |
| API/基础设施 | api/config/security/scheduler/channels/plugins/cli/deploy | 逐路由鉴权覆盖 grep、lifespan 装配清单、异常路径追踪 |
| 前端 | frontend/src 全部 15 子目录 | 行数/useState 统计、裸 fetch 定位、locale 键差集比对 |
| 横向 | 全仓 157 py | ast 依赖图（SCC/违例/孤岛）、重复块 hash、except/Any/type:ignore 计数、pyproject-import 对照 |
| 主题二/主题六细化（2026-08-29 追加） | 存储层全链路（models/db/仓储/备份/迁移/测试 fixture/启动流程）；前端全文件 + 后端 WS/OpenAPI 契约面 | 实查库（mode=ro）+ CHECK/FK 可满足性验证 + strict/openapi tsc/进程内实测；偏差 Δ1–Δ10、D1–D11 已回写本文 §2–§5，任务拆解见两份细化文档 §6/§7 |

本报告不修改任何代码；实施各 Phase 时请以对应小节为 PR 描述锚点，逐条引用问题编号（S/D/A/B/F-序号）。两份细化文档（storage/frontend refactor-design）为各自主题的执行口径，与本文冲突时以细化文档的实测修正为准并回写本文。

## 附录 B：修订记录

| 轮次 | 日期 | 内容 |
|---|---|---|
| ① 初版 | 2026-08-29 | 5 个子 agent 并行只读评审合成（本文 §1–§5、附录 A 原始结论） |
| ② 同步两份细化文档偏差 | 2026-08-29 | 回写主题二（存储层，偏差 Δ1–Δ10）与主题六（前端，偏差 D1–D11）实测修正，关键项：F3 裸 fetch 改 27 处（D9）、F2 改 15 props（D2）、D8 `strict` 口径反转（`--strict` 0 报错、107 处全在 `noUncheckedIndexedAccess`）、D1 TodoPage/KBPage 定性"切文件+去重/重归属"非从零组件化、Δ4 存量已 UTC 免全库改写、Δ5 保留双 DeclarativeBase 仅 env 层合并、Δ1 alembic `include_object` 排除 LangGraph `checkpoints/writes` 与 sqlite-vec shadow、Δ2 feedback 第二 FK 挂 `skill_id`（非 `message_index`）、Δ7 端点 `api_key` 明文入库（新增 S8，导出/日志脱敏硬要求）、Δ9 .venv 3.51.1 与容器 3.40.1 双解释器 CI、Phase 0/2/5 工时改为实测口径（§4）、D6 经 `AuthBridge` 把"同批合入"放宽为"同版本"（§3 依赖） |
