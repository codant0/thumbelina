# Thumbelina 项目多维检视报告

> **📌 复核更新(2026-09-05 晚)**:本报告发布后,项目合入 18 个提交(多模态链路修复 + 微信图片渠道)。各条意见的修复状态与新增代码的检视结论见 **[2026-09-05-review-findings-recheck.md](2026-09-05-review-findings-recheck.md)**——本报告的 P0"后端附件断链"、UI F1(T7)、F4(i18n)已修复,其余结构性结论(鉴权、部署持久化、存储地基、异常路径静默)复核确认原样有效。

- **日期**:2026-09-05
- **检视基线**:分支 `multimodal` @ `664be57`,含未提交的多模态附件改动(`InputBox.tsx`、`MessageList.tsx`、`AttachmentLightbox.tsx`、`DropOverlay.tsx`、`useAttachments.ts`、`useDropZone.ts` 等)
- **检视方式**:主 agent 并行派发 5 个独立子 agent,分别从**架构设计、代码逻辑、代码规范、UI 设计、前端易用性**五个维度做只读静态检视;子 agent 结论均须附 `文件:行号` 级证据。两处子 agent 结论冲突处已由主 agent 亲自读码复核(见 §2.2 勘误与 §5 发现 6 编者注)。
- **严重度定义**:
  - **P0** — 可致数据丢失 / 崩溃 / 安全事故,或功能整体断链;
  - **P1** — 明确 bug 或明显阻碍使用,应尽快修复;
  - **P2** — 边界隐患 / 摩擦点 / 一致性缺陷;
  - **P3** — 建议级改进。

---

## 0. 执行摘要

**总体结论**:这是一个功能密度很高、局部工程质量(记忆子系统、filestore、concurrency、调度器 v2、三主题 token 设计体系、流式渲染滚动状态机)显著高于同类个人项目的代码库;静态纪律优秀(ruff/format 零违规、527 个前端测试全绿、模块 docstring 覆盖 166/167)。当前最大的风险不是单个 bug,而是三类结构性问题:

1. **多模态分支处于"前端已上线、后端未跟上"的断链状态**——后端 WS 协议连 `attachments` 字段都没有,纯图片发送直接报 "Invalid message format",附件引用被静默丢弃;
2. **安全承诺与实现脱节**——鉴权 fail-open、WebSocket 完全绕过中间件、`/fs`、`/data/all`、`/config/export` 三个高危端点零门槛,默认 Docker 部署即裸奔;
3. **异常路径普遍静默**——WS 断线无重连把用户锁死、错误伪装成空状态、破坏性操作无确认。

另外:架构重构计划(2026-08-29)发布一周后,六个主题中只有"调度器 v2"一条被真正做完,安全边界与依赖解环两个前提完全未启动,且 app.py、TodoPage.tsx、useWebSocket.ts 等巨石文件仍在变大。

### 0.1 P0 问题(4 条,跨维度汇总)

| # | 问题 | 维度 | 证据位置 |
|---|------|------|---------|
| P0-1 | **后端附件链路未落地**:`WebSocketMessage` 无 `attachments` 字段(前端发的附件被 Pydantic 静默丢弃);`message` 有 `min_length=1` 导致纯图片发送直接报错;`_persist_message` 不落附件引用,历史重载缩略图消失;模型永远看不到图 | 逻辑 | `api/schemas.py:75-82`、`api/websocket.py:298-307`、`agent/graph.py:890-903` |
| P0-2 | **docker-compose 未把附件目录放进持久卷**,`THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY` 相对路径按 CWD 解析到 `/app/attachments`(非卷)→ 容器重建后全部用户上传图片永久丢失(DB 元数据还在,坏链不可恢复) | 逻辑 | `docker-compose.yml:30-35`、`api/routes/attachments.py:137-148` |
| P0-3 | **鉴权 fail-open + WS 完全绕过**:`_AuthMiddleware` 只处理 http scope 且密钥缺失/非法时告警后继续启动;`websocket_chat` 无条件 `accept()`;前端全仓 0 处 Authorization;`/fs` 任意绝对路径枚举、`DELETE /data/all?confirm=true` 一参清库、`/config/export` 不脱敏 API key | 架构 | `api/app.py:981-995,962-968`、`api/websocket.py:200`、`api/routes/fs.py:44-58`、`api/routes/data.py:86-101` |
| P0-4 | **FK 从未开启 + 5 套 engine 打同一 SQLite**:`messages/trajectory/attachment` 声明的 `ondelete="CASCADE"` 形同虚设,已造成孤儿行数据损伤;`run()` 与 `stream()` 落库逻辑复制漂移(非流式丢 `reasoning_content`) | 架构 | `repository/db.py:13-29` 等 5 处、`agent/graph.py:1144 vs 1278-1281` |

### 0.2 P1 问题摘要(按主题归并)

| 主题 | 问题(来源维度) |
|------|----------------|
| 连接与输入 | WS 断线无自动重连、输入区整体禁用,用户只能刷新页面(逻辑/易用性);中文 IME 组合期 Enter 直接发送半截文字,无 `isComposing` 守卫(易用性);InputBox 的 Enter 绕过 `hasBlockingAttachments` 门禁,上传中/失败附件被静默清掉;流式分支绕过 `pendingMessage` 守卫,二次 Enter 覆盖丢失已排队消息(逻辑,已复核确认) |
| 交互安全 | 删除会话一键直删无确认无撤销,同项目其他删除却有确认,模式不统一(易用性) |
| 后端正确性 | SubagentManager 永不清理 `_agents`,累计第 6 次创建起子代理功能永久失效直到重启(逻辑);cancel 后 `_execute` 无条件覆写为 COMPLETED 并发矛盾事件(逻辑);上传端点整读 body 后才校验大小 + 事件循环内同步哈希/写盘(逻辑);messages 无 seq 列,同秒消息回放顺序不稳定(架构/逻辑交叉印证) |
| 新 UI 收尾 | 附件 UI 全部 CSS 类零定义(T7 未落地),Lightbox 以普通文档流插入消息内直接打乱布局;`--danger` 变量从未定义致错误态颜色整链失效;两代命名变量(`--text-muted`/`--bg-input` 等)4 个空引用(UI) |
| 工程基线 | mypy strict 声明了 133 错;前端 tsconfig 未开 strict,68 处 `res.json()` 后裸访问属性类型检查全放行(规范);Provider 热切换重接线散落 4 处,漏改即静默用旧模型(架构);WS 断线后前端无重连(逻辑/易用性/UI 交叉印证) |

### 0.3 值得肯定的亮点(跨维度)

- **调度器 v2**(TaskStore/EventBus/Heartbeat/Dispatcher)是计划外的高质量交付;`concurrency.py` 的 WeakValueDictionary 会话锁设计正确。
- **三主题 token 设计体系自校准**:TSX 内硬编码色值 0 处、动效全部走时长/缓动 token、全局 `prefers-reduced-motion` 兜底、hljs 配色映射回主题变量。
- **流式阅读体验打磨扎实**:打字机阶梯提速、stick-to-bottom + 上滚即停 + ResizeObserver 看门狗、待发消息悬浮条(含 held 态)带完整 aria 标注。
- **附件管道(前端侧)工程质量高**:📎 与拖放共用一条管道、客户端压缩 + EXIF 剥离、逐张重试、"被移除条目不被复活"。
- **静态纪律**:ruff/format 零违规、裸 except 0 处、console.* 0 处、显式 any 0 处、TODO 技术债接近零、i18n 中英 554 键完全成对。
- **KB 上传任务列表**是全项目进度反馈的范本(阶段化文案 + 百分比 + 取消 + 失败原因)。

### 0.4 优先修复路线图(Top 10)

1. **【P0】一行配置保住用户数据**:两个 compose 文件补 `THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY=/app/data/attachments`(§2 P0-1)。
2. **【P0】落地后端附件链路(设计文档 B3/B4/B5)**:`WebSocketMessage` 增加 attachments 字段并放宽空文本守卫 → `_run_generation` 透传 → `_persist_message` 落附件引用 → `_build_initial_messages` 构建图像内容块;在此之前先在前端隐藏附件入口或返回明确错误码,避免静默丢数据(§2 P1-1)。
3. **【P0】鉴权 fail-safe 闭环**:纯 ASGI 双 scope(http+websocket)中间件、缺省密钥 fail-safe(随机密钥 + 退绑 127.0.0.1)、`/fs` 白名单、`/data/all` 回显确认、`/config/export` 脱敏;前端以 `api/client.ts` 作为凭证注入点(§1 P0-1/3/4、§3 P1-4)。
4. **【P1】InputBox 发送门禁收口**:`handleSend` 开头统一 `if (hasBlockingAttachments) return` 与 `if (pendingMessage) return`(流式分支同样生效);同时补 IME `isComposing` 守卫(§2 P1-2、§5 发现 2)。
5. **【P1】WS 自动重连状态机**:onclose 指数退避重连、重连后 `switch_conversation` 重放 + `loadHistory` 对账、断线期间保持输入可编辑并显示"重连中"(§5 发现 1)。
6. **【P1】删除会话补 ConfirmDialog + 统一破坏性操作确认模式;错误可见化**:列表加载失败与空状态区分、任务操作失败 toast、统一走现成的 Toast/ConfirmDialog(§5 发现 3/9/15)。
7. **【P1】SubagentManager 生命周期**:活跃数替代累计数上限、`{id: asyncio.Task}` 真 cancel、终态清理、`_execute` 写结果前检查 RUNNING(§2 P1-4/P2-1)。
8. **【P1】落地 T7**:补附件 UI 全部 CSS + i18n 键,合入前不得带着裸奔状态发布;顺手全局替换 `var(--danger)` → `var(--error)` 并做变量定义/使用差集 lint(§4 F1/F2/F3/F4)。
9. **【P1】DB 地基**:统一开 `PRAGMA foreign_keys=ON + WAL + busy_timeout`、归一 5 套 engine、messages 加 `seq` 列;`run()/stream()` 用 `_begin_turn/_finish_turn` 收口(§1 P0-5/§2 P2-5、§1 #13)。
10. **【P1】工程基线对齐承诺**:mypy 133 错清零并接 CI 门禁;前端 tsconfig 开 strict(实测单独开 0 报错)、抽 `api/client.ts` 消除 9 处 API_BASE 与 25 处错误样板复制(§3 P1-1/2、P2-4)。

---

下面为五个维度的完整检视报告(内容保持子 agent 原始结论,主 agent 复核产生的勘误以【编者复核】标注)。

---

## 1. 架构设计检视

> 检视方式:只读。以 CLAUDE.md 自述架构、`docs/plans/2026-08-29-architecture-refactoring-plan.md`(下称"重构计划")为参照系,对 `src/thumbelina/`(167 个 py 文件)与 `frontend/src/` 抽样精读 + grep 依赖分析。所有行号均为当前工作区实测。

### 1.1 架构总览(实测)

```
┌────────────────────────── 前端 React 19 + TS + Vite ──────────────────────────┐
│ App.tsx(367行, BrowserRouter + 9 个 React.lazy 页面)                          │
│  ├ hooks/useWebSocket.ts(905行,流式/排队/打字机)  ├ api/*(14 个模块,无统一 client) │
│  └ components/(Chat/Coder/Todo/KnowledgeBase/Memory/Settings/...)             │
└─────────────── HTTP /api/v1/*  +  WS /ws/chat ───────────────────────────────┘
                                                               │
┌────────────────────────── API 层 (api/) ─────────────────────────────────────┐
│ app.py(1050行): create_app + ~550行 lifespan God 装配(30+ 个 app.state)      │
│  ├ 中间件: CORS / _RateLimitMiddleware / _AuthMiddleware(仅 http scope)      │
│  ├ routes/(17 个路由文件; config.py 806行 / rag.py 802行)                     │
│  └ websocket.py(347行): WS 端点 + 模块级 _chat_ws_clients 全局广播            │
└──────┬───────────────────────────────────────────────────────────────────────┘
       │  ⚠ 循环依赖环(8 模块 SCC 仍在,见 1.2 #6)
┌──────┴───────── 领域层 ───────────────────────────────────────────────────────┐
│ agent/graph.py(1287行 ThumbelinaAgent)+ nodes/edges/state/checkpointer       │
│ agent/compression/(5 策略) ← 反向 import rag 的 estimate_tokens              │
│ llm/(4 provider + endpoint_manager + preset_manager → 反向依赖 agent)        │
│ memory/(分层 Markdown 记忆,质量最高)  skills/  subagents/  analysis/  prompts/ │
│ scheduler/(v2: TaskStore+EventBus+Heartbeat+Dispatcher,已真执行)✅           │
│ channels/(wechat 539行 / qq 265行,qq 仍有第二事件循环)                        │
│ plugins/(manager + sandbox + sandboxed_loader)   tools/ rag/ todo/            │
└──────┬───────────────────────────────────────────────────────────────────────┘
       │
┌──────┴────────── 基础设施层 ────────────────────────────────────────────────────┐
│ repository/(models 507行 + manager + search + trajectory_repo + feedback_repo)│
│   ⚠ 5 套独立 engine 打同一 sqlite;ensure_schema 只加不删;FK pragma 从未开启     │
│ config/(loader/models/persistence/runtime_manager/config_repo:三处真源)        │
│ filestore/(原子写+FileLocks,被 memory/todo 共用,质量高)✅  concurrency.py ✅   │
│ security/(auth/rate_limit,仍是"没接线的活代码")  notifications.py(僵尸层)      │
│ backup/(死代码)  migrations/(versions/ 为空,Alembic 已回退)                    │
└────────────────────────────────────────────────────────────────────────────────┘
```

**关键数据流**:
- **三条 chat 入口已统一**:HTTP `POST /chat`(routes/chat.py:98-136)、WS(websocket.py:54-166)、微信渠道(wechat_channel.py:330-350)都走 `apply_conversation_runtime` + `resolve_run_window` + `per_conversation_lock(cid)`——`concurrency.py`(WeakValueDictionary 锁表)是新增的正确设计。
- **配置链**:YAML `${VAR}` 替换 → 首启导入 system_config → 之后 DB 优先;热切换经 RuntimeConfigManager → `agent.swap_provider()` + 4 处手工重接线。
- **调度链(新)**:TaskStore(共享主 engine)→ EventBus(每事件类型双 hook:event_log + web_push)→ DeliveryDispatcher(渠道表 + prompt_runner)→ Heartbeat。

### 1.2 主要发现(18 条)

**安全边界**

1. **【P0】鉴权 fail-open 未修,WS 完全绕过** — `api/app.py:981-995`、`app.py:99`、`api/websocket.py:200`
   `_AuthMiddleware` 仍继承 Starlette `BaseHTTPMiddleware`(只处理 http scope),且"secret_key 为空→不挂载,密钥非法→warning 后裸奔启动"(app.py:984-988);docker-compose.yml 无任何 secret 注入、Dockerfile:69 绑 `0.0.0.0:8000`;`websocket_chat` 第 200 行无条件 `accept()`,两个中间件对 WS 均不生效;前端全仓 grep `Authorization` 为 0 处。计划主题一(Phase 1)整体未动。
   **建议**:纯 ASGI 中间件同时处理 http/websocket scope,accept 前校验 `?access_token=`,缺省密钥时生成随机密钥并退绑 127.0.0.1。
2. **【P0】会话无归属列,IDOR 是设计决策** — `repository/models.py:284`、`api/websocket.py:317-326`
   Attachment 模型注释明写"个人单用户免鉴权:无 user_id/FK 归属列";conversations 同样无 owner 列。单用户免鉴权作为产品决策可以接受,但它与 CLAUDE.md 宣称的 "role-based access control via require_roles()" 直接矛盾(app.py:77 定义了 `require_roles`,routes/memory.py:31-42 另写了一份 `_check_roles`)。
   **建议**:至少修正文档口径;若维持单用户,删掉 security/ 中死掉的 per-route 鉴权与 memory 的重复实现,避免"看似有防护"的仪式代码。
3. **【P0】`/fs` 任意绝对路径枚举且面扩大** — `api/routes/fs.py:44-58`
   `_resolve_dir` 只要求绝对路径+存在性,无 allowed_roots 白名单;新增的 `/fs/git` 接 `subprocess.run git`,把信息探测面扩大到 git 元数据。配合 `cors_origins` 默认 `["*"]`(app.py:962-968),浏览器页面可跨源探测本机目录与仓库分支。
   **建议**:加 `fs.allowed_roots` 配置 + realpath 前缀校验;CORS 默认收敛为空。
4. **【P1】`DELETE /data/all?confirm=true` 与 `/config/export` 泄密仍在** — `api/routes/data.py:86-101`、`api/routes/config.py:338-355`、`config/config_repo.py:243-272`
   前者一个 query 参数全清数据、无回显确认;后者对任何 key 不脱敏,allowlist 明文持久化 `tools.web_search.api_key`(config_repo.py:33);端点 api_key 以 `llm_endpoints.<uuid>` JSON blob 入库,键名后缀是 uuid,绕过 `_is_sensitive` 后缀判断。
   **建议**:export 按密钥字段清单脱敏;data/all 改 body 回显确认串 + 角色门槛。

**分层与依赖**

5. **【P0】Provider 热切换重接线散落 4 处** — `agent/graph.py:395-437`、`config/runtime_manager.py:92-99`、`api/routes/config.py:249,576`、`api/app.py:765-772`
   `swap_provider` 只管 agent 内部(compressor/extractor);skill_engine、composition_engine、subagent_manager 的重接线在 runtime_manager 手写一遍,conversation_namer 在 routes/config.py 又手写两遍,启动恢复路径 app.py:765-772 再抄一遍。新增持有 provider 的子系统漏改即静默用旧模型。
   **建议**:构造期自注册的 ProviderRegistry,swap 单点 fanout;这是解环主题里性价比最高的一项。
6. **【P1】8 模块循环依赖环原样保留,且新增一条边** — `config/models.py:10`、`channels/wechat_channel.py:337`、`agent/graph.py:292-293`、`llm/preset_manager.py:21-23`、`config/runtime_manager.py:12` ↔ `llm/endpoint_manager.py:11-12`
   四条环边实测全部健在:① config.models → channels.config;② wechat_channel.py:337 函数级 import `api.routes.chat`(注释自认"惰性导入避免循环");③ preset_manager TYPE_CHECKING import `ThumbelinaAgent`;④ runtime_manager ↔ endpoint_manager 互指。另有 7 处跨层 import `rag.retrieval.context_formatter.estimate_tokens`(agent/compression/base.py:24 等)。
   **建议**:先做零风险的符号上提(`util/tokens.py`)与 `ChannelCallback` Protocol 注入(删 ②),再处理 ①④。
7. **【P1】God 装配进一步膨胀:app.py 1050 行** — `api/app.py:378-928`
   lifespan 约 550 行,30+ 个 `app.state.*` 松散属性;跨层私有访问:`agent._rag_store_manager`(685-687)、`wechat_channel._agent`(826-827)、websocket.py:99 访问 `wechat_channel._agent`;反向 import 路由私有全局 `_qrcode_manager`(app.py:920);`AsyncExitStack` 只管 checkpointer 一项,中途抛错已建资源无统一回收;chroma 路径写死 CWD 相对 `"./data/chroma"`(app.py:510)。
   **建议**:建 `container.py` + `AppContext` + AsyncExitStack 全量注册;私有属性改显式 `attach_rag()`。
8. **【P1】配置三处真源未动** — `api/app.py:709-714`、`config/runtime_manager.py:264-272`、`config/persistence.py:49-65`、`api/app.py:971-979`
   YAML 导入 DB 后永久跳过(改 YAML 无效);热切换 `_persist()` 全量重写用户 YAML(丢注释、`${ENV}` 固化);RateLimiter 在 `create_app`(YAML 值)构造,而 `load_from_database()` 在 lifespan(app.py:730)才执行 → DB 中限流配置永不生效。
   **建议**:marker 化真源标记 + state.yaml 拆分;RateLimiter 至少移到 load_from_database 之后。

**数据与一致性**

9. **【P0】FK 从未开启 + 5 套 engine 打同一 SQLite** — `repository/db.py:13-29`、`repository/repository.py:84`、`repository/feedback_repo.py:59`、`skills/repository.py:27`、`skills/composition_repo.py:26`、`config/config_repo.py:58`
   全仓无任何 `PRAGMA foreign_keys=ON`;messages/trajectory/attachment 声明的 `ondelete="CASCADE"`(models.py:243,349)形同虚设。正向进展:TaskStore(scheduler/store.py:115)与 RAG(app.py:502)已改为复用主 engine。
   **建议**:`create_db_engine` 的 connect 事件统一 `PRAGMA foreign_keys=ON + WAL + busy_timeout`;其余 repo 构造函数改注入共享 engine(先回填/清理孤儿行)。
10. **【P1】messages 仍无 seq,回放排序靠秒级时间戳** — `repository/repository.py:220`、`repository/models.py:270`
    trajectory_events 有了轮次内 `seq`(models.py:356),但 messages 表仍只有 `created_at`(SQLite 秒级精度),`get_messages` 仍 `order_by(Message.created_at)`。同一秒内的 user/assistant 消息回放顺序不确定。
    **建议**:messages 加 `seq` + `(conversation_id, seq)` 唯一索引。
11. **【P1】存储演进机制原地打转** — `repository/models.py:22-62`、`migrations/versions/`(空)、`tests/test_migrations/`(空)
    Alembic 已正式回退,`ensure_schema`仍是"只 ADD COLUMN"的土法迁移;migrations/ 目录只剩空壳。任何"改类型/改约束/删列"依旧无解,列序漂移/僵尸表风险持续累积。
    **建议**:接受回退决策的前提下,把 ensure_schema 升级为"模型 vs 实际 schema 漂移只读告警";清掉空目录。
12. **【P2】backup/ 仍是死代码,导出非原子** — `backup/manager.py:29`(全仓唯一自引用)、`api/routes/data.py:65-83`
    BackupManager 零引用;实际 `/data/export` 仍是普通 `open().write`、域不全。根目录 5 个 `thumbelina.db.*.bak`、`test_rag.db`、3.2GB tar 是"靠手工拷库当备份"的直接证据。
    **建议**:重写 BackupManager 接管 `/data/export`(SQLite Backup API 快照 + manifest);根目录脏物清出 git 跟踪。

**Agent 与子系统**

13. **【P0】run/stream 复制漂移 + 字符串协议判错** — `agent/graph.py:1144` vs `graph.py:1278-1281`、`graph.py:755`
    非流式 `run()` 落库不带 `reasoning_content`,流式版带;工具节点仍用 `is_error=content.startswith("Error")` 反推失败状态,工具正常输出以 "Error" 开头即被记为 error。`repaired is messages` 的 `is` 判等跨模块契约仍在(graph.py:578)。
    **建议**:`_begin_turn/_finish_turn` 收口 + `ToolMessage(status="error")`。
14. **【P1】子代理"取消"仍撒谎、注册表只增不减** — `subagents/manager.py:145,203-208`
    代码注释自认:"The asyncio task running the LLM call is not currently tracked"——`cancel_agent` 只翻状态,协程继续跑;`_agents` 无终态清理,长会话内存单调增长。相对计划是净进步:新增了 SubagentEvent 监听协议与 WS 桥接(websocket.py:223-249)。
    **建议**:`{id: asyncio.Task}` 跟踪 + `task.cancel()` + 终态 TTL 清扫。
15. **【P1】插件系统仍是仪式性防护** — `plugins/manager.py:145-147`、`plugins/sandbox.py:297,123,144`、`api/routes/plugins.py:20,60`
    装配 sandboxed_loader 时 manager 提前 return,其后约 120 行拓扑排序是死代码;沙箱 `strict` 默认宽松,黑名单含 `"exec"` 字面量模式(前缀匹配语义存疑);计划点名的 `/plugins/dependencies` 端点不存在。
    **建议**:双加载器归一、`strict` 默认 True;黑名单补 os/subprocess/shutil/socket 并改前缀匹配。
16. **【P2】notifications.py 是僵尸层** — `notifications.py:41-48`、`api/app.py:556,265-283`
    `_subscribers` 全仓零填充 → `notification_manager.broadcast` 永远返回 0;真正生效的是 `broadcast_chat_message`。App 还常驻一个空 NotificationManager 实例。
    **建议**:删掉 legacy 帧与 NotificationManager,或重写为 websocket.py 连接表的薄适配器。

**前端契约**

17. **【P1】WS 断线无重连;"排队"只解决了一半** — `frontend/src/hooks/useWebSocket.ts:764-783`
    `onclose/onerror` 只置状态位,无重连、无心跳,断线一次直到用户刷新。净进步:新增 queuePendingMessage 排队浮窗,断线消息不再静默丢。
    **建议**:显式连接状态机 + 重连 + 重连后 `loadHistory` 对账。
18. **【P1】API 层无统一 client,类型无编译期保护** — `frontend/src/api/`(14 个模块)、23 处组件内裸 fetch、`tsconfig.app.json` 无 strict
    无 `client.ts` 单例;`types/` 手写无 openapi-typescript;TodoPage.tsx 从计划时 1105 行涨到 1562 行。正向:Router + 9 页面 React.lazy 分包已落地。
    **建议**:先落 client.ts(错误归一 + 凭证注入点),再迁 23 处裸 fetch;两阶段开 strict(实测 strict 单独 0 报错)。

**其他快速记录**:QQ 渠道 `send_message` 仍是空实现,`_ready` Event 跨线程/跨循环使用(botpy 第二事件循环未桥接);LLM stream 仍只 yield `str`,ollama 的 list_models/speed_test 仍 NotImplementedError;graph.py 1287 行、`__init__` 16 参数;版本三源漂移(VERSION=v0.0.3、pyproject=0.1.0、app.py 硬编码 "0.1.0");pyproject 未声明 `botpy`,mypy python_version 3.13 与 requires-python >=3.11 不一致。

### 1.3 与重构计划(2026-08-29)的差距对照表

| 计划主题 | 状态 | 证据 |
|---|---|---|
| **主题一 安全边界 fail-safe**(S1-S8) | ❌ **基本未动** | 中间件仍 BaseHTTPMiddleware、fail-open、compose 无密钥、前端 0 处 Authorization、/fs 无白名单、/data/all 裸 confirm、export 不脱敏 |
| **主题二 存储地基**(D1-D12) | ⚠️ **整体回退,Phase 0 小步部分完成** | 计划顶部注记宣布回退 Alembic;migrations/versions 空、messages 无 seq、FK pragma 未开、backup 死代码。已完成:trajectory 轮次内 seq、TaskStore/RAG 复用主 engine |
| **主题三 依赖解环与装配** | ❌ **未动,且 app.py 更肥** | 4 条环边全在;app.py 1050 行、无 container;botpy 未声明、llama-index 仍在主依赖 |
| **主题四 Agent 核心演进**(A2-A7) | ⚠️ **少数小步,主体未动** | 完成:工具构造下沉 tools/ 包、并行工具调用、Anthropic list_models、subagent 事件协议。未动:`is` 契约、丢 reasoning、startswith("Error")、16 参构造、stream 仍 str |
| **主题五 基础设施正确性**(B1,B4-B8) | ✅ **B1 已根治(计划外高质量交付)**,其余部分推进 | 完成:调度器 v2 真执行+持久化+recover+Heartbeat+Dispatcher;微信走共享 chat 管线+per-conversation 锁。未动:配置三真源、QQ 双循环、插件、两个 God router、版本三源 |
| **主题六 前端工程化**(F1-F6) | ⚠️ **F1/F2 部分完成,F3-F6 未动** | 完成:Router+React.lazy 分包、断线排队消息、attachment 协议层。未动:重连、client.ts + 23 处裸 fetch、tsconfig strict、类型生成;TodoPage 反而 1105→1562 行 |

**总体判断**:计划发布后一周的实际开发走的是"按产品功能推进 + 顺手修最痛正确性问题"路线——调度器 v2、子代理事件流、附件系统、openai-responses 通道、前端 Router/排队都是实打实的新能力;但六个主题中只有主题五的 B1 被真正"做完",安全边界与依赖解环这两条其他一切重构的前提完全未启动,且部分巨石在继续变大,"先解环再拆分"的窗口正在收窄。计划本身质量很高(取证扎实、敢回退),主要问题是**执行没跟上计划**;唯一值得修正的计划问题是:Alembic 回退后,主题二应显式改写为"create_all + ensure_schema 告警化 + 手工 seq 回填"的轻量路线。

### 1.4 架构维度 Top 3 优先改进

1. **鉴权 fail-safe + WS 中间件**——默认部署下全部写接口与 `/ws/chat` 裸奔,三个高危端点零门槛;这是唯一"越拖越可能出事故"的项。
2. **Provider 热切换单点化(ProviderRegistry)+ 5 套 engine 归一**——前者消掉 4 处手工重接线这个"静默错模型"温床;后者是唯一已造成实际数据损伤的项。
3. **前端 api/client.ts + WS 重连状态机**——23 处裸 fetch 是鉴权注入与错误契约的共同堵点;断线无重连是用户可见的第一大故障。

---

## 2. 代码逻辑检视

> 范围:未提交/近期多模态改动(`664be57` 后端附件 API、`117939b` 前端协议层、`a91bdb7` 前端附件 UI)+ `api/websocket.py`、`routes/chat.py|attachments.py|conversations.py`、`agent/graph.py` run/stream 循环、`repository/`、`scheduler/` 与 `concurrency.py`、`filestore/`、`memory/service.py`、前端附件/WS 链路、Docker 部署一致性。
> 方法:`git log --oneline -20` + `git show --stat` 锁定改动 → 通读改动文件全文 → grep 可疑模式 → 逐条回读上下文确认真伪;对 SQLite 跨线程复用做了只读运行时探针验证。
> 注:设计文档 `docs/specs/2026-09-04-multimodal-chat-design.md` 中 B3(WS 协议)/B4(Agent 多模态)/B5(块构建)标注为待做——下述 P1-1 是"前端先行、后端未跟上"造成的事实性契约断裂,而非误报设计意图。

### 2.1 确认的问题清单

**P0-1|docker-compose 未把附件目录放进持久卷,容器重建后用户上传图片全部丢失(数据丢失)**
- 位置:`docker-compose.yml:30-35`、`docker-compose.nas.yml:34-39`、`api/routes/attachments.py:137-148`、`config/models.py:103-107`
- compose 精心地把 `DATABASE_URL`、TODO 目录、微信凭据都搬进 `/app/data` 卷,唯独漏了 `THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY`。而 `_attachments_root` 对相对路径按 `Path.cwd()` 解析(`root.is_absolute() else Path.cwd() / root`)。容器内 `WORKDIR /app` → 图片落到 `/app/attachments`(非卷)。DB 在卷里,附件行元数据保留、字节丢失 → 重建容器后所有历史图片 404 永久坏链。项目自己吃过同类亏(compose 注释两次写着"⚠️ 重建即丢")。
- 修复:两个 compose 文件补 `THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY=/app/data/attachments`;并在启动期对"DB 中存在但磁盘缺失"的附件记录做一次性清扫或告警。

**P1-1|后端 WS 协议完全未消费附件:schema 无字段、空文本+图片直接报错、附件引用全链路丢失**
- 位置:`api/schemas.py:75-82`;`api/websocket.py:298-307, 330-332`;`agent/graph.py:890-903, 1104, 1169`
- `WebSocketMessage` 没有 `attachments` 字段,前端按协议 §4.1 发送 `{message, attachments:[{id,alt}]}`(useWebSocket.ts:292-294),Pydantic 默认忽略未知键 → 附件被静默丢弃;`_run_generation` 也只传文本。更糟的是纯图片发送(空文本):前端 `canSendMessage` 明确放行(useWebSocket.ts:96-98),但后端 `min_length=1` 直接 `ValidationError` → 前端显示 "Error: Invalid message format"。`_persist_message` 签名无 attachments 参数,用户消息入库 `attachments=NULL` → 历史重载后缩略图消失;`agent.run/stream` 只收字符串,模型永远看不到图。`manager.get_attachments`(manager.py:458)在后端无任何调用方。
- 修复:落地 B3/B4/B5——`WebSocketMessage` 增加 `attachments: list[AttachmentRef]` 且 `message` 允许为空(attachments 非空时放行);`_run_generation` 透传;`_persist_message("user", ...)` 落库 `{id,mime,width,height,alt}` 引用;`_build_initial_messages` 构建图像内容块。在此之前建议前端隐藏附件入口或后端返回明确错误码。

**P1-2|InputBox 回车(Enter)绕过发送门禁:上传中/失败的附件被静默丢弃,排队消息被覆盖丢失**(主 agent 已读码复核确认)
- 位置:`frontend/src/components/Chat/InputBox.tsx:228-247(handleSend)`、`254-258(handleKeyDown)`、`269-274(sendDisabled)`
- `sendDisabled` 把 `hasBlockingAttachments`、`!!pendingMessage` 的禁用只做在**按钮**上,而 `handleKeyDown`/表单提交直接调 `handleSend`,其中:
  - `handleSend` 全程**不检查** `hasBlockingAttachments`:非流式分支只带 `readyRefs`(就绪项),发送后 `onAttachmentsChange?.([])` **全部清空**,含 uploading/failed 项 → 上传中按 Enter:消息发出但不带图,上传中的条目被清出 strip(服务端孤儿文件),用户以为已带图;
  - 流式分支(232-239)在 `if (pendingMessage) return`(241)**之前** return,守卫被绕过:已有排队消息时再次 Enter → `queuePendingMessage` → `setPendingFor`(useWebSocket.ts:183-196 直接 `pendingRef.current[convId] = entry` 覆盖)→ **覆盖丢失**旧排队消息。
- 修复:`handleSend` 开头统一加 `if (hasBlockingAttachments) return` 与 `if (pendingMessage) return`(覆盖流式/非流式两条路径)。

**~~P1-3|附件预览 ObjectURL 泄漏~~(【编者复核】误报,撤回)**
- 子 agent 原判:`previewUrlsRef` 永不 `.set()`,revoke 是死代码。
- 主 agent 复核:**不成立**。`InputBox.tsx:151-158` 的 list 同步 effect 中存在 `previewUrlsRef.current.set(a.localId, a.previewUrl)`(注释明示"previewUrlsRef 的唯一写入点"),配合移除(210-218)、列表消失(162-170)、卸载(172-177)三条回收路径,revoke 机制完整有效。

**P1-4|SubagentManager 永不清理 `_agents`,累计 5 次后子代理功能永久失效**
- 位置:`subagents/manager.py:46, 94-117, 186-212`;`subagents/types.py:66-91`
- `create_agent` 以 `len(self._agents) >= self.max_agents` 拒绝(max_agents=5),但全代码库没有任何 `del/pop` 清理——COMPLETED/FAILED/CANCELLED 条目永久占位。进程生命周期内第 6 次 `create_agent` 起必然 `RuntimeError("Maximum number of agents (5) reached")`。`MonitorAgent._monitor_loop` 每个周期 `create_agent` 一次,5 个周期后把自己和整个子代理功能堵死。
- 修复:终态(及 cancel)后延迟清理,或改为统计"活跃(RUNNING)"数量;MonitorAgent 每轮用完即删。

**P1-5|前端 WebSocket 无任何重连逻辑,断线后永久"已断开"**
- 位置:`frontend/src/hooks/useWebSocket.ts:421-425, 764-782`;`App.tsx:124-128`
- effect 仅依赖 `[url]`,`onclose/onerror` 仅状态复位,无重试/退避/重建。后端重启、网络闪断、代理超时后,UI 永远显示断开、输入框 disabled,只能刷新(刷新丢本地附件草稿与排队消息)。
- 修复:onclose 带退避重连(重连后重放 `switch_conversation` 并重拉 `loadHistory`)。

**P2-1|cancel_agent 后 `_execute` 把已取消的子代理"复活"为 COMPLETED,并发出矛盾事件**
- 位置:`subagents/manager.py:161-165 vs 199-212`
- `cancel_agent` 只改状态不取消底层 LLM 任务;`_execute` 在 LLM 返回后**无条件覆写** `agent.status = SubagentStatus.COMPLETED` 并 emit `subagent.completed`。cancel 与完成竞态时,前端先收 `subagent.cancelled` 再收 `subagent.completed`。scheduler 里 `_fire_task` 有同类 reaper 守卫,这里漏了。
- 修复:`_execute` 写结果前检查 `agent.status is SubagentStatus.RUNNING`;或挂 `asyncio.Task` 真 cancel。

**P2-2|`active_conv_ref` 在获取会话锁**之前**写入 → 跨连接排队时 subagent 事件串会话**
- 位置:`api/websocket.py:76-84`
- 两个连接同时向不同会话发消息:任务 B 在锁上排队时已把 ref 改成 B,而任务 A 正在跑 → A 的 subagent 事件被以 `conversation_id=B` 推给所有连接,前端把 A 的子代理卡片挂到 B 的消息下。
- 修复:把 `active_conv_ref["value"] = cid` 移到 `async with` 内部;事件带上 agent 所属轮次的 cid。

**P2-3|上传端点先整读后校验大小 + 事件循环内同步写盘/哈希**
- 位置:`api/routes/attachments.py:182-202`
- `data = await file.read()` 把请求体全部读进内存后才检查 10MB(对比同项目 `rag.py:170-190` 的流式分块+即时 413 写法);随后 `hashlib.sha256(data)` 与 `write_bytes_atomic`(含 fsync)同步调用,阻塞事件循环(期间所有 WS 流卡顿)。
- 修复:分块读、累计超 10MB 即 413;哈希/写盘放 `asyncio.to_thread`。

**P2-4|上传"写盘成功但入库失败"留下孤儿文件(无回滚)**
- 位置:`api/routes/attachments.py:202-211`
- `write_bytes_atomic` 成功后 `create_attachment` 抛错(如 DB busy)时磁盘文件不清理,且无 DB 行 → GET/DELETE 均不可达,永久孤儿(设计明确不做 GC)。
- 修复:入库失败时 `safe_unlink`;或先写 `.tmp`、入库成功后再 `os.replace`。

**P2-5|消息排序仅按秒级精度的 `created_at`,同秒消息顺序不稳定**(与架构报告 1.2#10 交叉印证)
- 位置:`repository/repository.py:217-221`;`repository/models.py:266-270`
- `order_by(Message.created_at)` 无次级排序键;SQLite `CURRENT_TIMESTAMP` 精度为秒。短回复场景 user/assistant 常同秒落库,重载历史排序平局未定义,可能出现"回答在提问之前"。
- 修复:加自增 `seq` 列(trajectory 表已有同思路的 `seq`)或入库用毫秒/微秒时间戳。

**P2-6|停止按钮跨会话误伤:stop 不校验目标会话**
- 位置:`api/websocket.py:268-279`;`frontend/src/hooks/useWebSocket.ts:377-385`
- 前端 `stopGeneration` 携带当前**正在看的**会话,后端 stop 不比对 cid 直接 `current_task.cancel()`。用户在 A 流式期间切到 B 再点停止 → 停掉 A 的生成,`stopped` 帧回显 B 的 id。
- 修复:后端任务记录 cid,不匹配则拒绝;前端改用 `streamingConvId`。

**P3(摘要)**
- **P3-1** 同连接上一轮未结束时主循环阻塞在 `_wait_task_cleared`,期间收不到 stop(`api/websocket.py:309-314`);若 LLM 无超时挂死,该连接既不能停也不能发。
- **P3-2** 发送超时(90s)善后不分会话:`setWaitingConvIds([])` 清空所有会话等待态,超时消息无条件追加到当前视图(useWebSocket.ts:236-256)。
- **P3-3** 附件上限校验把无效文件计入配额,合法文件被整批误拒(useAttachments.ts:94-95);提示只报"最多 4 张",掩盖类型错误。
- **P3-4** 上传 fetch 无超时/无 AbortController(api/attachments.ts:22-30);loadHistory 失败静默(useWebSocket.ts:859-861)、ChatWindow config fetch 静默(ChatWindow.tsx:91-96)。
- **P3-5** fire-and-forget `asyncio.create_task` 无强引用/无异常回收 5 处(`graph.py:1124,1147,1283`、`subagents/manager.py:90,145`);建议统一 `set` + done-callback 模式(scheduler.py:130 已有)。
- **P3-6** SQLite 未启用 WAL/busy_timeout(`repository/db.py:29-34`),写写并发超 5s 默认等待抛 `database is locked`,repository 侧多处降级为"消息未落库"。已实测排除:SQLAlchemy 2.0.48 文件 SQLite 跨线程复用连接正常,线程错误不存在。

### 2.2 已排查、确认无问题的可疑点

- **附件 serve/delete 路径穿越**:`_attachment_file` 先 `resolve()` 再 `relative_to(root.resolve())`,GET 与 DELETE 都在删行/读文件前执行检查;上传文件名为服务端 `uuid4 + 白名单扩展`。安全。
- **DELETE 双删竞态**:并发删除第二个请求 404,`safe_unlink` 幂等。
- **SVG/HTML 伪装上传**:mime 白名单不含 SVG,serve 回 `image/*`,无存储型 XSS 主路径(可选加固:`nosniff`)。
- **上传中删除附件的"复活"竞态**:`patchItem` 检查目标仍存在才打补丁;仅留下服务端孤儿文件(设计已声明无 GC)。
- **imageUtils.decodeImage 的 objectURL**:降级路径在 finally 中 revoke,无泄漏。
- **useDropZone 计数器**:负值有防护,dragover preventDefault 正确,回调走 ref 防闭包过期。
- **concurrency.py 会话锁**:WeakValueDictionary 无泄漏,cid=None 短路正确。
- **compress/clear/delete 三个会话级写操作**:均正确持有 `per_conversation_lock`,与聊天路径互斥。
- **websocket 连接关闭清理**:finally 中 cancel → 回收 → discard → 退订,完整无泄漏;`CancelledError` 显式 re-raise 不被吞。
- **scheduler**:cron 校验、`_fire_task` 的 reaper/失败槽守卫自洽;`stop()` 排空 inflight;Heartbeat 有防重复。
- **ensure_schema ALTER TABLE 迁移**:逐列幂等,DEFAULT 分支处理正确。
- **memory/service.py**:全部文件 IO 走 `asyncio.to_thread`,写入原子,无事件循环阻塞。
- **AttachmentLightbox**:键盘监听配对、`safeIndex` 钳制正确;Esc 与 ChatWindow 的 Esc 不冲突。

### 2.3 逻辑维度 Top 3 必须优先修复

1. **【P0】compose 缺 `THUMBELINA_REPOSITORY__ATTACHMENTS_DIRECTORY`**——一行配置的代价,避免 Docker 部署下上传图片永久丢失。
2. **【P1】后端附件链路落地(B3/B4/B5)**——当前多模态功能整体处于"看起来能用、实际断链"状态。
3. **【P1】InputBox 回车门禁**——`handleSend` 补 `hasBlockingAttachments`/`pendingMessage` 守卫(防附件静默丢失与排队消息覆盖)。紧随其后:WS 重连与 SubagentManager 上限,修复成本低、收益明确。

---

## 3. 代码规范检视

> 范围:`src/thumbelina/`(167 个 .py 文件)、`tests/`、`frontend/src/`(54 个测试文件 / 527 个测试)。抽样精读:后端 `api/routes/chat.py`、`conversations.py`、`skills.py`、`agent/graph.py`、`agent/state.py`、`repository/repository.py`;前端 `ChatWindow.tsx`、`InputBox.tsx`、`hooks/useWebSocket.ts`、`api/llmConfig.ts`、`api/conversations.ts`。

### 3.1 静态检查工具结果摘要

| 工具 | 命令 | 结果 |
|---|---|---|
| ruff lint | `ruff check src/ tests/` | **0 违规** |
| ruff format | `ruff format --check src/ tests/` | **0 违规**(328 files) |
| mypy (strict=true) | `mypy src/` | **133 errors in 44 files**(167 files checked) |
| eslint | `npm run lint` | **1 error, 7 warnings** |
| tsc | `npx tsc -b --force` | **1 error**(TS6133) |
| vitest | `npm test` | **54 文件 / 527 测试全部通过**(12.68s) |

mypy 错误分布(按错误码):`override`×21、`no-any-return`×19、`type-arg`×17、`arg-type`×17、`no-untyped-def`×15、`no-untyped-call`×10、`import-untyped`×7、`index`×6、`attr-defined`×6、`assignment`×5、`unused-ignore`×3。典型:`api/app.py:184/196/200/203...` 约 14 条 untyped-def 簇;`routes/skills.py:42,67,84,131` 等裸 `dict`;`rag/common/db.py:38` 等 3 处过期 `type: ignore`。

eslint 典型:Error `DropOverlay.test.tsx:8 'dragOver' is assigned a value but never used`(与 tsc TS6133 同源);Warning `useWebSocket.ts:790` effect 缺 7 项依赖;Settings 目录 5 个组件同型 `useCallback` 缺 `'t'` 依赖的 5 连复制。

### 3.2 规范发现清单

1. **【P1】前端 TS 未开启 strict 模式**
   `frontend/tsconfig.app.json` 与 `tsconfig.node.json` 无 `"strict": true`,仅有 noUnusedLocals 等。implicit any 与 strictNullChecks 关闭,使"前端 0 处 `: any`"的表面成绩失真——`api/*.ts` 共 68 处 `res.json()`(返回 any)后直接访问属性,类型检查完全放行。
   **建议**:开启 `strict` + `noUncheckedIndexedAccess`,分目录渐进修复;api 层接入 `no-unsafe-*` 系列。
2. **【P1】mypy strict 配置与实际状态脱节(133 错误)**
   pyproject.toml:94 `strict = true` 但报 133 错,集中区为 `api/app.py` 与 `routes/{skills,data,conversations,config}.py`。
   **建议**:清零(约一半是补 `dict[str, Any]`/返回注解的机械修改),或 CI 先冻结基线禁止增长;3 处过期 `type: ignore` 直接删除。
3. **【P2】中英文注释/文案混用无统一规范**
   后端 167 个文件中 95 个含中文注释,同文件内 docstring 中英混排;模块 docstring 一律英文(166/167 覆盖率极好)。前端注释质量高(带"设计 §5.1"等规范引用),但 UI 文案绕过 i18n:`InputBox.tsx:77,93-94,97,103-104` 硬编码"上传中/上传失败,重试/移除 ${name}";`AttachmentLightbox.tsx:54-77`、`MessageList.tsx:179` 同样。
   **建议**:定稿注释语言策略;上述 aria-label/title 接入 i18n。
4. **【P2】前端 API 层复制粘贴严重,已有抽象未复用**
   `const API_BASE = '/api/v1'` 在 **9 个文件**重复定义;错误处理样板 `if (!res.ok) {...throw new Error(data.detail || \`HTTP ${res.status}\`)}` 复制 **25 处**;`api/llmConfig.ts:108-118` 已有泛型 `request<T>` 封装,其余 8 个文件未使用。
   **建议**:抽 `api/client.ts`(BASE + request + 统一错误解析),其余文件迁移。
5. **【P2】后端路由重复模式**
   `routes/conversations.py` 中 `"Conversation not found"` 出现 14 次;6 个 set-类端点重复"set_xxx → 404 检查 → get_conversation → 404 检查 → 回读"三段式(:274-284、:301-307、:326-332、:345-351 等)。
   **建议**:提取 `_get_conv_or_404()` 与"更新后回读"依赖项。
6. **【P2】错误静默吞掉,失败无日志**
   `routes/chat.py` 5 处 `except Exception:` 直接 return/回退且不打日志(:161-162、:179-180、:221-223、:238-239、:265-266;其中 :221-223 provider 创建失败静默回退默认模型——用户配置错误将无任何痕迹)。全后端 `except Exception` 共 195 处(裸 `except:` 0 处),多数带 `logger.warning(..., exc_info=True)`(正面样例:`chat.py:93-94`)。
   **建议**:静默回退处补 `logger.warning(..., exc_info=True)`;可引入 ruff `BLE/TRY` 规则。
7. **【P2】魔法值/硬编码**
   `routes/chat.py:207` fallback 模型名硬编码 `or "gpt-4o"`;`main.py:81` `uvicorn.run(app, host="127.0.0.1", port=8000)` 不走配置;`ChatWindow.tsx:92,206` 组件内直接 `fetch('/api/v1/config')` 绕过 api 层;`Sidebar.tsx:7` `WECHAT_CONVERSATION_NAME = '微信Clawbot'` 业务名硬编码;`ChatWindow.tsx:86` 与 `InputBox.tsx:175` 各自实现一份"2000ms 自动消失 hint"重复逻辑。
   **建议**:`gpt-4o`、端口、会话名进配置;前端 hint 抽公共 hook。
8. **【P2】巨型文件(模块规模超标)**
   后端 500+ 行 11 个:`agent/graph.py` **1287 行**(单类 32 方法多职责)、`api/app.py` 1050、`scheduler/scheduler.py` 949、`repository/repository.py` 820、`routes/config.py` 806、`routes/rag.py` 802。前端:`Todo/TodoPage.tsx` **1562 行**、`TodoPage.test.tsx` 1175、`KnowledgeBasePage.tsx` 970、`hooks/useWebSocket.ts` 905(单 hook 约 26 个 ref/useState)。
   **建议**:graph.py 按"压缩/流式/上下文解析"拆模块;TodoPage 拆子组件;useWebSocket 拆打字机/待发队列/事件订阅独立 hook。
9. **【P2】useWebSocket 测试文件拆分混乱、Mock 重复**
   同时存在 `useWebSocket.test.ts`(3 个 describe)与 `useWebSocket.test.tsx`(1 个 describe),各自实现一套 MockWebSocket。
   **建议**:合并为一个文件,共享 Mock 基建。
10. **【P3】库代码 print 残留**:`rag/embedding/provider_hf.py:85,90` 用 print 输出进度,应改 logging(CLI 的 7 处 print 合理保留;全 src/ print 共 9 处)。
11. **【P3】死代码**:`api/llmConfig.ts:153` `runSpeedTest` 全项目零引用;`api/tasks.ts` `createTask` 仅测试引用、生产未用(待确认是否预留)。
12. **【P3】suppression 分散**:前端 19 处 `eslint-disable` 无集中登记;`react-hooks/exhaustive-deps` 7 条 warning 未清。
13. **【P3】类型与 hook 归属不统一**:类型分散在 `types/` 与 `api/llmConfig.ts`;`useAttachments.ts` 放在 `components/Chat/` 而非 `hooks/`;纯函数 `canSendMessage` 放在 `useWebSocket.ts` 且测试文件名与被测模块不一致。
14. **【P3】mypy `python_version = "3.13"` 与 `requires-python = ">=3.11"` 不一致**(pyproject.toml:9 vs :93)。
15. **【P3】ruff 规则面偏窄**:`select = ["E","F","I","N","W","UP"]`,未启用 B(bugbear)、SIM、C4、RUF。

### 3.3 工程债统计

```
超长文件 Top(后端)             1287 agent/graph.py     949 scheduler/scheduler.py
                                1050 api/app.py          820 repository/repository.py
                                 806 routes/config.py    802 routes/rag.py
                                 692 memory/extractor.py 581 rag/ingestion/loader.py
                                 539 todo/service.py     539 channels/wechat_channel.py
前端 Top5:TodoPage.tsx 1562 / TodoPage.test.tsx 1175 / KnowledgeBasePage.tsx 970 / useWebSocket.ts 905 / useWebSocket.test.ts 887
```

- 技术债标记:后端真实 TODO 仅 1 处(rag/ingestion/loader.py:354);前端 0 处。属优秀水平。
- any 使用:前端显式 `: any` / `as any` 均 0;后端 `Any` 317 处(多为 `dict[str, Any]` 边界合法)。
- 重复证据:API_BASE×9、错误样板×25、"Conversation not found"×14、useCallback 缺 `'t'`×5、MockWebSocket×2。
- `# noqa`/`# type: ignore` 共 55 处(含 3 处失效);`except Exception`×195 / 裸 except×0;`logger = logging.getLogger(__name__)` 68 文件统一;前端生产代码 console.* 0 处。

### 3.4 规范维度 Top 3 优先改进

1. **补齐前端类型安全基线**:开启 tsconfig strict,抽 `api/client.ts`(消除 9+25 处复制),清理 ChatWindow 内联 fetch 与 `runSpeedTest` 死代码。
2. **mypy strict 清零并接 CI 门禁**:133 → 0(多为机械补注解),删除 3 处过期 ignore。
3. **定稿语言与文案规范**:注释语言策略;前端剩余硬编码中文 aria-label/title 接入 i18n;清理 5 个 Settings 组件的 useCallback 依赖 warning。

---

## 4. UI 设计检视

> 范围:`frontend/src/` 静态代码检视(未运行浏览器),含未提交的多模态附件 UI。说明:实际 `package.json` 为 `react ^19.2.6`(React 19,非 18)。

### 4.1 设计体系现状速写

- **主题机制**:`styles/themes.css` 定义 dark / light / warm 三套主题,全部走 `[data-theme]` 语义 CSS 变量(表面四层、文本四层、accent 双色系 + 语义色各带 `-muted`),由 `ThemeToggle.tsx` 切换并用 View Transitions API 做交叉淡入;注释记录 WCAG AA 校准痕迹。
- **尺度 token**(index.css):圆角 4 档、字号 7 档、间距 10 档、图标 4 档、动效时长/缓动、z-index 四级、全局 `:focus-visible` 焦点环。
- **样式手段分布**:CSS 约 8163 行、几乎 100% 消费 `var(--*)`;TSX 硬编码色值 **0 处**;内联 style 35 处(多为动态宽度,合理);无 Tailwind/CSS Modules——纯语义 class + 全局样式表;图标为 lucide-react(50 文件)+ 唯一自研 `WeChatIcon.tsx`(品牌补位)。
- **基础组件**:common/ 仅 ConfirmDialog、EmptyState、FloatWindow;Modal 实际在 `Settings/Modal.tsx` 且被 7 组件复用;Toast、按钮系、表单系、统一空态、三套骨架屏均已成型。
- **总体判断**:存量 UI 是**成熟度相当高的 token 化设计体系**;但当前分支的新附件 UI 停留在"结构与 JS 完成、CSS 与 i18n 任务(代码注释反复标注的 'T7')未落地"状态,且历史遗留的第二套变量命名造成多处"变量指向空无"的真实视觉缺陷。

### 4.2 发现清单

**F1|P1|新附件 UI 的全部 CSS 类没有任何样式定义** — `AttachmentLightbox.tsx:50-86`、`DropOverlay.tsx:18-22`、`InputBox.tsx:68-108,297,326,329,344`、`MessageList.tsx:163-186,221`
grep `styles/` + `index.css`:`.lightbox-*`、`.drop-overlay*`、`.attachment-*`、`.attachments-strip`、`.attach-btn`、`.pending-float-attach-badge`、`.msg-attachment*` **全部 0 命中**。代码注释自证:"inset:0,由 T7 样式实现"(InputBox.tsx:68)、"样式由 T7 统一进 styles/chat.css"(DropOverlay.tsx:11)。后果:Lightbox 无全屏遮罩/居中/固定定位(以普通文档流块插在 `.message` 内部,直接打乱消息布局,MessageList.tsx:258-265 无 portal);DropOverlay 不再是全屏蒙层而是一行裸文本;拖拽高亮、九宫格、缩略图、进度环、失败重试视觉全部缺失。
**建议**:合入前先落地 T7 样式层(报告给出 `.lightbox-backdrop` fixed 遮罩、`.drop-overlay` dashed accent 边框等最小可用方案),补 `.attachment-thumb`(64×64 圆角卡 + `--failed` 红描边 + 进度环)与 `.attachments-strip`(横向滚动九宫格)。

**F2|P1|`--danger` 变量从未定义,错误态颜色整链失效** — `styles/chat.css:771-772, 884, 986-988, 1029-1030, 1155-1166`
themes.css 三主题只定义了 `--error`,但 chat.css 中 5 组规则引用 `var(--danger)`,无 fallback → 属性计算非法回退:failed 徽章不再红色、错误块失去红色描边、浮窗关闭 hover 无红底。
**建议**:全局替换 `var(--danger)` → `var(--error)`,或 themes.css 加一行桥接 `--danger: var(--error);`。

**F3|P2|两套命名并存的残留变量,其中 4 个从未定义** — `coder.css:83,159,181`、`knowledge.css:378`、`pages.css:999,1301,1360`、`EndpointForm.tsx:167,173`
全局比对"使用 vs 定义":`--bg-input`(→ 计算为透明)、`--bg-tertiary`(→ 透明)、`--text-muted`(→ 弱化层级丢失)、`--muted-text`(靠 `#888` 硬 fallback 苟活)、`--sp-9`(仅靠 fallback 36px)。这是 `error/danger`、`text-secondary/text-muted`、`bg-elevated/bg-input` 两代命名的混用。
**建议**:一次性归并到 themes.css 正式命名;加 CI grep 差集检查。

**F4|P2|新 UI 文案硬编码中文,绕过 i18n** — `DropOverlay.tsx:20`、`InputBox.tsx:93,97,346,396`、`MessageList.tsx:173,179`、`AttachmentLightbox.tsx:50,54,67,74,82`
"松开以上传图片""重试加载""查看图片""添加图片""上传失败,重试""+ N 张图片""图片预览""关闭""上一张""下一张"全部字面量;locale 文件无 `chat.attachments` 键;aria-label 同样硬编码。
**建议**:与 T7 一并补齐 locale 键。

**F5|P2|弹窗无焦点陷阱、无焦点恢复;Lightbox 打开时不接收焦点** — `Settings/Modal.tsx:22-29`、`AttachmentLightbox.tsx:33-45`
Modal 仅 `panelRef.current?.focus()` + Esc,Tab 可穿透到背景内容,关闭后焦点不归还触发元素。Lightbox 更弱:打开时焦点留在消息流,`aria-modal="true"` 声明了模态却无对应行为;遮罩没有 onClick(与 Modal"点遮罩关闭"习惯不一致)。
**建议**:抽 `useModalA11y(ref, onClose)` hook(记录 activeElement、focus panel、Tab trap、卸载归还);Lightbox 遮罩加 `e.target === e.currentTarget` 判定关闭。

**F6|P2|`outline: 2px solid var(--focus-ring)` 是非法声明** — `styles/composer.css:638-641`
`--focus-ring` 定义为多重 box-shadow 值而非颜色,该 outline 整条被浏览器丢弃;仅因全局 `:focus-visible` 兜底才还有焦点环。
**建议**:改 `box-shadow: var(--focus-ring); outline: none;` 或增加 `--focus-color` token。

**F7|P2|三套浮层选择器 CSS 近乎逐行复制** — `composer.css:10-162 vs 164-317 vs 507-733`
`kb-float__*`、`role-float__*`、`think-float__*` 的 trigger/panel/option/heading/caret/empty 规则除类名外几乎 100% 相同(约 200 行重复);`.clear-context-btn` 与 `.compress-btn` 完全一致(ChatWindow.tsx:341 甚至双挂类名)。
**建议**:合并为通用 `.float-picker` 块 + BEM 修饰符;TSX 层共用一个 `FloatPicker` 原语——正是 common/ 应该长出来的第四个基础组件。

**F8|P2|侧栏会话项的删除/重命名按钮仅 `:hover` 显形,键盘用户不可见** — `styles/layout.css:217-220`
Tab 聚焦到按钮时 opacity 仍为 0(按钮隐形但可聚焦)。同库其他处已用 `:focus-within` 正确处理(blocks.css:216、todo.css:212,439)。
**建议**:补 `:focus-within` 分支,与 todo 模式对齐。

**F9|P2|模态实现三分支,自研两处缺焦点入口/Esc** — `TrajectoryDetailModal.tsx:58`、`Coder/WorkspacePicker.tsx:90-91`
7 个组件正确复用 `Settings/Modal`,但这两处手写 `modal-overlay` 结构:WorkspacePicker 无 Esc 关闭、无焦点进入;TrajectoryDetailModal 同样无 Esc。另:`common/ConfirmDialog.tsx:1` import `Settings/Modal`,依赖层级倒挂。
**建议**:两处改用 `Settings/Modal`;把 `Modal.tsx` 迁入 `common/`。

**P3 打磨项(摘要)**
- **F10** subagent 遮罩/面板 `z-index: 50/60` 魔法数绕开 token(chat.css:704,719),建议加 `--z-side-panel`。
- **F11** 亮主题 accent `#0D9488` 作白字底对比度约 3.7:1 低于 AA(待确认手工计算),建议拆 `--accent`/`--accent-text` 双 token(themes.css:60)。
- **F12** `pages.css:1142` 硬编码 `rgba(74,222,128,0.3)` 不随主题,建议统一 color-mix。
- **F13** `.form-select` 内联 SVG caret 描边硬编码 `%23808089`(blocks.css:317)。
- **F14** 尺度旁路:9px 小字号(chat.css:234)、`--sp-9` 未补定义、radius 7px/10px 脱离 4 档阶等 12 处 raw 值。
- **F15** 静态布局内联样式散落:ConfirmDialog 正文/按钮排布、KB 页 `display:flex;gap` 等(EndpointForm.tsx:161,167、ConfirmDialog.tsx:18-19、KnowledgeBasePage.tsx 7 处)。
- **F16** 知识库布局/文档表响应式规则误放在 composer.css:431-505。
- **F17** 顶栏 11 个一级导航,≤1023px 全部折叠成无文字图标(Header.tsx:22 + blocks.css:454-458),新用户不可发现;建议低频页收进"更多"溢出菜单。

### 4.3 值得肯定的设计亮点

1. **三主题 token 体系完整且自校准**:表面/文本/语义色分层清晰,注释记录 WCAG 修正过程;连滚动条、选区、focus-ring 都随主题联动;hljs token 全部映射回主题变量。
2. **动效纪律好**:时长/缓动全 token,86 处 transition / 26 组 keyframes;全局 `prefers-reduced-motion` 兜底;主题切换用 View Transitions 交叉淡入。
3. **空态/加载/反馈三件套成体系**:统一 EmptyState(compact 变体)+ 三套骨架屏 + Toast + ConfirmDialog;hover-only 操作在触屏设备用 `@media (hover: none)` 常显。
4. **无障碍习惯明显高于平均**:87 处 aria-label、22 处 aria-pressed、11 处 aria-expanded;交互元素基本是原生 `<button>`(div+onClick 仅 8 处且多数补了 role/键盘处理)。
5. **工程级滚动细节**(MessageList.tsx:292-360):贴底跟随 + 上滚即停、ResizeObserver 看门狗、`overflow-anchor:none`、`content-visibility:auto`、`scrollbar-gutter: stable`。

### 4.4 UI 维度 Top 3 优先改进

1. **落地 T7:补齐附件 UI 全部 CSS + i18n 键**(F1/F4)——当前分支不可发布状态;并给 `InputBox.visual.test.tsx` 的 stylesheet 断言模式扩展到新类名防回归。
2. **变量命名归并 + 防回归 lint**(F2/F3/F14)——`--danger→--error`、`--text-muted→--text-secondary`、`--bg-input→--bg-elevated` 全局替换,补 `--sp-9`,CI 差集检查脚本。
3. **弹窗 a11y 与浮层组件收敛**(F5/F7/F9)——`useModalA11y` hook + 合并三套 float-picker 为 `FloatPicker` 原语,两处手写弹窗回归 `Modal`。

---

## 5. 前端易用性检视

> 范围:全量精读 Chat/附件链路 + 抽样 Settings/Tasks/Memory/KnowledgeBase/StatusBar/Channels/Plugins/Todo + i18n/CSS/键盘事件静态分析。注:新附件 UI 的 CSS 缺失(T7)为已知问题,本章不重复报告样式本身,聚焦交互逻辑。

### 5.1 用户旅程速写与断点

**主流程**:启动 → App.tsx 挂载 Header(11 个导航项)+ 懒加载页面;进入 `/chat` 后若未选会话,自动跳转到名为「微信Clawbot」的会话(App.tsx:180-185)→ Sidebar 选会话/新建(createConversation 失败静默,App.tsx:214)→ InputBox 输入,Enter 发送 → WebSocket 流式回复(打字机逐字,可随时停止/复制/对最后一条重新生成)→ 回复期间再提交会进入"待发消息"悬浮条(自动发送/立即执行/取消)→ 新增:拖拽或 📎 添加图片(压缩→上传→就绪缩略卡,随消息发送)→ 切到 Tasks/Settings/KB 等页面(WS 连接在 App 层持有,跨页不断开,有回归测试)。

**旅程断点**:① 断线即断流,输入框整体禁用无重连按钮(发现 1);② 中文 IME 用户第一次回车确认候选词就可能把半截文字发出去(发现 2);③ 误删会话无回头路(发现 3);④ 多处失败被伪装成"空状态",用户无法区分"没有数据"和"加载失败"(发现 9)。

### 5.2 发现清单

**1.【P1】WS 断线后无自动重连,且整个输入区被禁用,用户被完全卡死**
`hooks/useWebSocket.ts:764-782` —— `onclose/onerror` 仅 `setIsConnected(false)`,全文件无 reconnect/backoff;effect 仅依赖 `[url]`。`ChatWindow.tsx:412` 将 `disabled={!isConnected}` 传入 InputBox,textarea 与按钮全部禁用。唯一反馈是状态点"已断开",无"重连"按钮、无 toast。后端重启或网络抖动后只能手动刷新整页,草稿与状态全丢。
**建议**:指数退避自动重连;断线期间保持 textarea 可编辑(仅禁发送),显示"已断开,正在重连…";连续失败提供手动"立即重连"。

**2.【P1】中文输入法组合期间按 Enter 会直接发送半截文字(无 isComposing 守卫)**
`InputBox.tsx:254-259` —— `if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }`,全项目无 `isComposing`/`compositionstart` 处理。Firefox/Safari 及部分 Chrome 场景下,确认候选词的 Enter 会命中该分支。这是一个带 zh-CN 语言包、微信/QQ 渠道的产品,IME 是主路径。
**建议**:加 `if (e.nativeEvent.isComposing || e.keyCode === 229) return`,并补组合输入不发送的测试。

**3.【P1】删除会话一键直删,无确认、无撤销**
`Sidebar.tsx:139-149` 删除按钮直接 `onDelete(conv.id)` → `App.tsx:227-236` 直接 `fetch DELETE`,中途无任何 ConfirmDialog;对照同项目"清空上下文"有确认(ChatWindow.tsx:358-366)、"删除全部数据"有两步确认(SettingsPanel.tsx:41-63)。
**建议**:复用 ConfirmDialog 二次确认;或"删除后 5 秒内可撤销"的 toast 撤销条。

**4.【P2】图片粘贴(Ctrl+V)不支持**
`InputBox.tsx` 的 textarea 无 `onPaste`,全项目无 clipboardData 处理;附件入口仅 file input 与拖放。截图后最自然的 Ctrl+V 无任何反应也无提示。
**建议**:监听 paste,取 `clipboardData.items` 中 image 项走同一条 `addFilesToAttachments` 管道(接入成本低)。

**5.【P2】拖入非图片文件:蒙层承诺"松开以上传图片",落下却静默无反馈**
`useDropZone.ts:9-13` 非图片被直接忽略不做失败态,`:54-59` drop 后若全部被过滤则不回调任何提示;而 `DropOverlay.tsx:18-21` 只要 types 含 'Files' 就显示"松开以上传图片"。用户拖 PDF 进窗口:蒙层出现→松手→什么都没发生,体验为"功能坏了"。
**建议**:全部为非图片时复用 `dropHint` 通道提示"仅支持图片";或蒙层阶段按 MIME 提前区分提示语。

**6.【P2】附件阻塞发送时的反馈过弱;"重试"按钮对永久无效文件无效**(编者注:本条原文称"键盘 Enter 提交走 handleSend 静默返回",经复核**不成立**——Enter 实际会绕过门禁发出消息并清掉未就绪附件,见 §2 P1-2,问题比原文描述更严重)
`InputBox.tsx:149,269-274` —— 阻塞发送的唯一解释是禁用按钮上的 title(403 行,需 hover);失败卡上仍渲染可点的"重试"按钮,但 `useAttachments.ts:124-131` `retryLocalAttachment` 对校验不过的文件静默 `return`——点击后毫无反应,用户只能自己猜到要删掉它。
**建议**:发送被阻塞时在附件条旁显示常驻行内提示;对校验不过的条目把"重试"换为"移除"或提示"格式不支持,请移除"。

**7.【P2】灯箱交互缺失:点遮罩不关、无缩放、无焦点管理、大图加载失败无兜底**
`AttachmentLightbox.tsx:50` 背景容器无 onClick;无缩放/手势;`aria-modal` 声明但无焦点圈定;`<img>`(61 行)无 onError——缩略图有"重试加载"而大图失败展示原生破图。
**建议**:遮罩点击关闭;至少滚轮/双击缩放;打开时 focus 到关闭按钮并 Tab 圈定;img 加 onError 降级。

**8.【P2】草稿跨会话串扰:切换会话清空附件却保留正文**
`ChatWindow.tsx:280-286` 切会话 `setAttachments([])`,而 InputBox 未以 conversationId 作 key,内部 `text` state 跨会话存活(InputBox.tsx:128)。A 会话写了长文本没发,切到 B,附件没了、文字还在,一按 Enter 发进了 B。
**建议**:统一语义——文本+附件都随会话保留,或都清空;最简单给 InputBox 加 `key={conversationId}`。

**9.【P2】错误静默/伪装成空状态的路径较多(无统一 toast 覆盖)**
均为 catch 后无用户可见反馈:历史加载失败 → 空白会话(useWebSocket.ts:801-804,859-861);会话列表失败 → 伪装"暂无对话"(App.tsx:141-145);KB 语义查询失败与"无结果"不可区分(KnowledgeBasePage.tsx:297-298);插件加载失败显示"暂无插件"(PluginsPage.tsx:40-47);任务暂停/恢复/取消失败无提示(TaskManager.tsx:124-150 四个 handler 均 catch ignore);新建会话失败静默(App.tsx:214);导出失败静默(SettingsPanel.tsx:26-35)。项目已有 Toast 组件,接入成本低。
**建议**:"列表加载失败"与"空状态"区分(错误态含重试按钮);API 错误统一走轻量 toast 总线。

**10.【P2】定时任务没有任何创建入口,cron 输入辅助无从谈起**
`api/tasks.ts:118` `createTask` 已封装但全项目无组件调用;TaskManager.tsx 只有列表/筛选/暂停/恢复/取消/详情。用户想建定时任务,页面只有 EmptyState,不知道只能通过聊天让 agent 代建(产品意图待确认)。
**建议**:空态文案说明"可通过对话创建定时任务";后续补创建表单时同步提供 cron 模板与下次执行时间预览。

**11.【P2】i18n 框架外的硬编码文案(与已知 T7 附件文案是两回事)**
`useWebSocket.ts:251` 'Request timed out...'、`:308` 'Failed to send message...'、`:497` \`Error: ${data.error}\`——聊天主界面的系统消息中文界面下也是英文;`SettingsPanel.tsx:58`、`ChannelsPage.tsx` 错误路径;任务/插件/文档状态徽标直接渲染原始英文枚举(TaskManager.tsx:181,261-263)。T7 范围的新附件硬编码中文约 18 处(InputBox 7、AttachmentLightbox 5、useAttachments 3、MessageList 2、DropOverlay 1),此处仅统计规模。
**建议**:超时/发送失败/Error 前缀走 i18n;状态枚举建立 `badge→i18n` 映射表(UploadTaskList.tsx:13-26 已是现成范式)。

**12.【P3】"回到底部"按钮存在感知盲区(40–320px 之间)**
`MessageList.tsx:292-299` —— 距底 <40px 才跟随新内容,>320px 才显示跳底按钮;两者之间既不自动跟随也看不到按钮,流式内容在视口下方静默增长。**建议**:阈值统一(如 >80px 即显示按钮)。

**13.【P3】附件数量无余量指示,上限提示仅违规瞬间出现 2 秒**
MAX=4、超限整体拒绝(useAttachments.ts:6,95);提示 2 秒自动消失(ChatWindow.tsx:84-88);附件条不显示"2/4"。**建议**:附件条常驻 `n/4` 计数;超限时"收下前 4 张 + 提示丢弃数"。

**14.【P3】快捷键覆盖可接受但发现性差**
Enter/Shift+Enter、Esc 关闭各浮层、灯箱 ←/→ 均有;但 Coder 页隐藏的 `n` 快捷键(CoderPage.tsx:62-68)无任何提示;无"快捷键说明"入口;无聚焦输入框/切换会话的全局快捷键。

**15.【P3】危险操作确认模式不统一**
三套并存——两步按钮(KB 删除、删除全部数据)、`window.confirm`(Todo 组删除,TodoPage.tsx:737,1166)、无确认(会话删除、文档删除 KnowledgeBasePage.tsx:229,829、端点删除 EndpointList.tsx:237、取消任务/subagent)。**建议**:统一收敛到 ConfirmDialog;至少给"删除知识库文档""删除端点"补确认。

**16.【P3】平板/窄屏导航辨识度 + 无全局错误边界**
<1023px 时 11 个导航项只剩图标(blocks.css:454-458);`main.tsx` 无 ErrorBoundary,任意渲染异常即白屏。移动端侧栏抽屉实现完整,核心聊天窄屏可用性尚可。

**17.【P3】进入 /chat 强制定位到微信会话(产品语义待确认)**
`App.tsx:180-185` 无 id 时自动 navigate 到 `WECHAT_CONVERSATION_NAME` 会话;新用户首屏直接进入渠道机器人会话而非自己的新对话。**建议**:若为有意设计,空态文案说明;否则改为最近活跃会话。

### 5.3 值得肯定的易用性亮点

1. **流式阅读体验打磨扎实**:打字机阶梯提速、"生成中"指示 500ms 延迟合并避免闪烁、stick-to-bottom + 上滚即停 + ResizeObserver 看门狗 + 头部替换识别会话切换。
2. **待发消息悬浮条设计周全**:流式中提交自动排队、异常结束转 held 态换图标换文案、立即执行/取消双出口、`role="status" aria-live="polite"`;WS 连接提升到 App 层跨页存活并有回归测试。
3. **附件管道(前端侧)工程质量高**:📎 与拖放共用一条管道、客户端压缩 + EXIF 剥离、object URL 三处兜底 revoke 无泄漏(§2.2 亦已复核)、逐张 failed 可重试、"被移除的条目不被复活"、乐观插入与历史回放解析容错完备。
4. **KB 上传任务列表是全项目的进度反馈范本**:阶段化文案 + 百分比进度条 + 文件/分片计数 + 取消/关闭 + 失败原因与结果摘要。
5. **i18n 键位完全成对**:en 与 zh-CN 各 554 键无缺失;语言持久化 + 浏览器语言探测;Esc 行为一致。

### 5.4 易用性维度 Top 3 优先改进

1. **WS 自动重连 + 断线可用性**(发现 1,P1):唯一会把用户彻底锁在门外的缺陷,影响所有功能。
2. **IME Enter 守卫**(发现 2,P1):一行守卫代码,换来中文主用户群的核心输入正确性。
3. **破坏性操作确认补齐 + 失败可见化**(发现 3/9/15 合并):复用现成的 ConfirmDialog 与 Toast,统一"删除必确认、失败必出声"两条底线,消除"空状态伪装"类误导。

---

## 6. 跨维度综合分析

### 6.1 四条共性主题

1. **"异常路径静默"是全项目的第一体验债**。三个维度独立指出同一模式:WS 断线无重连(逻辑/易用性)、5 处 provider 构建失败静默回退不打日志(规范)、9+ 处 catch 后无用户反馈、失败伪装成空状态(易用性)、195 处宽 except 中少数不打日志(规范)、后端附件被 Pydantic 静默丢弃(逻辑)。建议把"失败必出声(日志 + toast)、空状态与错误态必须可区分"作为两条工程底线写入 CLAUDE.md。
2. **多模态分支处于"半交付"状态**。前端协议层/UI 骨架已完成且质量不错,但后端 WS 协议(B3)、Agent 多模态(B4)、块构建(B5)未做,样式层(T7)与 i18n 未合入——功能当前处于"演示可看、实际断链、视觉裸奔"三者叠加的状态。建议要么在本分支内把 B3/B4/B5 + T7 收尾,要么先把附件入口藏到 feature flag 之后,避免带着已知断链合入。
3. **重构计划执行断层**。六个主题只有"调度器 v2"被真正做完;安全边界(主题一)与解环/装配(主题三)这两个"其他一切重构的前提"完全未启动;同时 app.py(1050)、TodoPage.tsx(1562)、useWebSocket.ts(905)在计划发布后继续变大。建议对 2026-08-29 计划做一次显式修订:确认回退 Alembic 后的轻量存储路线、把主题一压缩为"最小安全闭环"(双 scope 中间件 + fail-safe + 三个高危端点)单独立项。
4. **复制粘贴在两个技术栈同时发生**。前端:API_BASE×9、错误样板×25、三套 float-picker CSS、两套 MockWebSocket、双份 hint 定时器;后端:6 个 set-端点三段式、4 处 provider 重接线、run/stream 落库漂移。共同根因是"缺一个被普遍使用的原语"(api/client.ts、FloatPicker、_get_conv_or_404、_begin_turn)。

### 6.2 交叉印证(多维度独立确认的问题,可信度最高)

| 问题 | 独立确认维度 |
|------|-------------|
| WS 断线无重连,输入区整体禁用 | 逻辑 P1-5 / 易用性发现 1 / 架构 #17 |
| messages 无 seq,同秒消息回放顺序不稳定 | 架构 #10 / 逻辑 P2-5 |
| InputBox Enter 绕过发送门禁、排队消息覆盖 | 逻辑 P1-2(主 agent 已读码复核) |
| 附件 UI 样式缺失(T7 未落地) | UI F1 / 逻辑(方法注) / 易用性(注) |
| 错误静默/吞没模式 | 规范 3.2-6 / 易用性发现 9 / 逻辑 P3-4 |
| 后端附件链路断链(B3/B4/B5 未做) | 逻辑 P1-1 / 架构(前端契约观察) |

### 6.3 主 agent 复核产生的勘误

- **撤回**:逻辑报告原 P1"附件预览 ObjectURL 泄漏"为**误报**——`InputBox.tsx:151-158` 存在 `previewUrlsRef.current.set()` 唯一写入点,三条回收路径完整有效(易用性报告的判断正确)。
- **升级**:易用性报告发现 6 原文认为"Enter 会走 handleSend 静默返回",经复核**不成立**——Enter 实际绕过门禁发送,问题升级为 §2 P1-2。
- **更正**:易用性报告称"React 18",实际 `package.json` 为 `react ^19.2.6`。

### 6.4 优先级合并视图

按"影响 × 修复成本"排序的合并行动清单(前 10 项见 §0.4,此处不重复)。补充第二梯队:

11. **【P2】上传端点流式读取 + `asyncio.to_thread` 化哈希/写盘 + 入库失败回滚**(逻辑 P2-3/P2-4)。
12. **【P2】`active_conv_ref` 移入锁内 + stop 校验会话归属**(逻辑 P2-2/P2-6)。
13. **【P2】图片粘贴支持 + 拖入非图片反馈 + 阻塞发送行内提示**(易用性发现 4/5/6)。
14. **【P2】Provider 热切换 ProviderRegistry + 配置三真源 marker 化**(架构 #5/#8)。
15. **【P2】拆分三巨头文件**:`agent/graph.py`(1287)、`TodoPage.tsx`(1562)、`useWebSocket.ts`(905)(规范 3.2-8)。

---

*本报告由 5 个并行检视子 agent 的结论整合而成;除 §6.3 所列勘误外,各维度结论均保持原始证据与行号。行号对应当前工作区(含未提交改动),后续提交后可能漂移。*
