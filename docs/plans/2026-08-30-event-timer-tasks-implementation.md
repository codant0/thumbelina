# 事件触发定时任务实施计划

> **For implementer:** Use TDD throughout. Write failing test first. Watch it fail. Then implement.

**Goal:** 将调度器从"内存演示态"升级为事件驱动的可靠调度：cron 循环任务 + 一次性定时任务、结构化事件（渠道+内容）、EventBus 回调 hooks、Heartbeat 巡检、任务持久化与重启 recover、WEB 任务页实时展示与暂停/恢复/取消。

**Architecture:** 原地演进 `scheduler/`（保 `TaskScheduler` 公共 API 兼容）：`models.py`（任务/事件模型）→ `cron.py`（croniter 薄封装）→ `events.py`（EventBus）→ `store.py`（挂现有 `Base` metadata 的两张表 + TaskStore）→ `scheduler.py` v2（到期扫描 + 事件发射 + recover/pause/resume）→ `heartbeat.py`（巡检）→ `dispatcher.py`（按渠道交付）；`app.py` 装配 hooks（事件日志 / WS 推送 / 渠道交付）；`tools/event_trigger.py` 扩展 cron/channel 参数；前端 `api/tasks.ts` + 任务页改造 + `{task_event}` WS 订阅。

**Tech Stack:** Python 3.11 + croniter + SQLAlchemy + pytest（asyncio auto）；React 19 + TypeScript + Vitest。

**设计文档:** `docs/plans/2026-08-30-event-timer-tasks-design.md`（含 D1–D10 决策记录，实现疑问以设计文档为准）

## Global Constraints

- `TaskScheduler` 公共 API 兼容：`add_task/get_task/list_tasks/cancel_task/complete_task/get_due_tasks/start(on_due_task=)/stop` 签名与语义不变；存量 `tests/test_scheduler/test_scheduler.py` 除 T5 明确列出的断言修正外必须全绿。
- `tools/event_trigger.py` 工具 `name`（`schedule_task`/`list_scheduled_tasks`）不变；新增参数全部可选，旧两参调用行为逐字兼容；工具失败返回 `Error:` 前缀字符串，成功返回 `str`，不抛异常。
- 时间口径：本地 naive `datetime.now()`，与全库一致；cron 不处理 DST。
- 优雅降级：scheduler/heartbeat/store 初始化失败只 `logger.warning`，服务器照常启动，相关路由返回空/503。
- 每任务收尾：`uv run pytest tests/<对应目录> -q`；T11 跑全量 `uv run pytest -q` + `ruff check src/ tests/` + `mypy src/` + 前端 `npm test && npm run build`。
- 提交信息中文，`feat:`/`refactor:`/`fix:`/`test:`/`docs:` 前缀。
- mypy strict：新模块全量类型注解（`store.py` 的 to_thread 包装处允许 `cast`）。

## 文件结构（最终态）

| 文件 | 职责 | 任务 |
|---|---|---|
| `src/thumbelina/scheduler/models.py` | `TaskStatus(+FAILED/PAUSED/MISSED)`、`TriggerKind`、`DeliveryChannel`、`TaskEventType`、`ScheduledTask`、`TaskEvent` | T1 |
| `src/thumbelina/scheduler/cron.py` | `CronTrigger.validate/next_after`（croniter） | T2 |
| `src/thumbelina/scheduler/events.py` | `EventBus` 订阅/退订/发射 + per-hook 异常隔离 | T3 |
| `src/thumbelina/scheduler/store.py` | `ScheduledTaskRecord`/`TaskEventRecord` ORM（`Base` metadata）+ `TaskStore` | T4 |
| `src/thumbelina/scheduler/scheduler.py` | v2：ONCE+CRON 到期扫描、事件发射、recover、pause/resume、持久化跃迁 | T5 |
| `src/thumbelina/scheduler/heartbeat.py` | 巡检循环 + `status()` 快照 | T6 |
| `src/thumbelina/scheduler/dispatcher.py` | `DeliveryDispatcher` 渠道交付 + COMPLETED/FAILED 回发 | T7 |
| `src/thumbelina/config/models.py` | `SchedulerConfig` + `AppConfig.scheduler` | T8 |
| `src/thumbelina/api/app.py` | lifespan 装配：store/bus/dispatcher/hooks/heartbeat/recover | T8 |
| `src/thumbelina/api/routes/tasks.py` | POST /tasks、pause/resume、events、scheduler/status；GET /tasks 扩展字段 | T8 |
| `src/thumbelina/tools/event_trigger.py` | `schedule_task` +cron_expression/channel；`list_scheduled_tasks` +字段 | T9 |
| `frontend/src/api/tasks.ts` | 类型化任务客户端 | T10 |
| `frontend/src/hooks/useWebSocket.ts` | `task_event` 帧派发（~5 行） | T10 |
| `frontend/src/components/Tasks/TaskManager.tsx` | 定时任务卡片改造（触发类型/cron/下次触发/渠道/暂停恢复/WS 刷新/存活点） | T10 |
| `frontend/src/components/Tasks/TaskEventFeed.tsx` | 最近事件流卡片 | T10 |
| `frontend/src/i18n/locales/en.json`、`zh-CN.json` | `taskManager.*` 新键 | T10 |
| `thumbelina.yaml.example`、`README.md`、`README_CN.md`、`CLAUDE.md` | 配置示例与文档同步 | T8/T11 |
| 删除 | 无（本计划不删文件） | — |

任务依赖：T1 → {T2, T3, T4} → T5 → {T6, T7} → T8 → T9/T10（可并行）→ T11。

---

### Task 1: 模型层——枚举增量 + ScheduledTask v2 + TaskEvent

**Files:**
- Create: `src/thumbelina/scheduler/models.py`
- Modify: `src/thumbelina/scheduler/scheduler.py`（`TaskStatus`/`ScheduledTask` 改为从 `models.py` re-export，本文件旧 import 路径 `from thumbelina.scheduler.scheduler import ScheduledTask` 保持可用）
- Test: `tests/test_scheduler/test_models.py`

**Interfaces:**
- Produces: `TaskStatus`（存量 4 值 + `FAILED/PAUSED/MISSED`）、`TriggerKind`、`DeliveryChannel`、`TaskEventType`（§3 表）、`ScheduledTask`（§4 全字段；`description`/`scheduled_time` 之外的键全部带默认）、`TaskEvent`
- 兼容断言：`ScheduledTask(description="x", scheduled_time=dt)` 产出 `trigger=ONCE, channel=WEB, status=PENDING, mode="notify"`；`scheduler.py` 的 re-export 使 `from thumbelina.scheduler.scheduler import TaskStatus, ScheduledTask` 与 `from thumbelina.scheduler.scheduler import ScheduledTask`（`api/app.py:57`、`tools/event_trigger.py:16` 现状）均不破。

**Steps:**
1. 写失败测试 `test_models.py`：枚举值全集与值域（小写 value）、TaskEvent 必填键、v1 两参构造兼容、`TaskStatus` 增量值不影响存量断言。
2. `uv run pytest tests/test_scheduler/test_models.py -q` 确认失败（ModuleNotFoundError）。
3. 实现 `models.py`；`scheduler.py` 改为 `from thumbelina.scheduler.models import ScheduledTask, TaskStatus` + `__all__` re-export。
4. `uv run pytest tests/test_scheduler tests/test_tools/test_event_trigger.py tests/test_api -q` 全绿（确认无 import 破坏）。
5. 提交 `feat(scheduler): 任务/事件模型层(枚举增量+ScheduledTask v2+TaskEvent)`。

---

### Task 2: CronTrigger（croniter 薄封装）

**Files:**
- Create: `src/thumbelina/scheduler/cron.py`
- Modify: `pyproject.toml`（dependencies 增 `"croniter>=2.0"`）
- Test: `tests/test_scheduler/test_cron.py`

**Interfaces:**
- Produces:
  - `class CronTrigger: def __init__(self, expr: str)`（无效表达式抛 `ValueError`，message 含原式）；`def next_after(self, dt: datetime) -> datetime`（严格晚于 dt 的下一次，本地 naive）；`def describe(self) -> str`
  - `def validate_cron(expr: str) -> str | None`（合法返回 None，非法返回错误信息）
- 语义：支持 5 字段（`* , - /`）与 `@daily/@hourly/@weekly/@monthly/@yearly/@midnight`；不支持秒字段（含 6 字段输入 → ValueError）。

**Steps:**
1. 失败测试：`*/5 * * * *` 从 09:02 算得 09:05；`0 9 * * *` 跨日；月末 `0 0 31 * *` 与 2 月边界；`@daily` 等价 `0 0 * * *`；6 字段/`* * *`/空串/乱串 → ValueError；`validate_cron` 两分支；`next_after(now)` 严格大于 now（同秒不吃进）。
2. 确认失败 → 安装依赖（`uv add croniter` 或手动 pyproject + `uv sync`）→ 实现（`next_after` 内部用 `croniter(expr, dt)`；`get_next(datetime)`）。
3. `uv run pytest tests/test_scheduler/test_cron.py -q` 全绿。
4. 提交 `feat(scheduler): CronTrigger(croniter)支持5字段与@描述符`。

---

### Task 3: EventBus（事件回调 hooks）

**Files:**
- Create: `src/thumbelina/scheduler/events.py`
- Test: `tests/test_scheduler/test_events.py`

**Interfaces:**
- Produces: `Hook = Callable[[TaskEvent], Awaitable[None]]`；`class EventBus: subscribe(event_type, hook) -> Callable[[], None]`（返回退订闭包）、`unsubscribe(event_type, hook)`、`async emit(event) -> int`（返回成功派发的 hook 数）
- 契约：emit 按**注册顺序** await 派发匹配 `event_type` 的 hooks；单 hook 异常被捕获记 `logger.warning`，不影响后续 hook（异常隔离）；同一 (event_type, hook) 重复订阅幂等（不重复派发）；无订阅者 emit 返回 0 不报错。

**Steps:**
1. 失败测试：类型过滤、注册顺序、异常隔离（第一个 hook 抛错、第二个仍收到）、退订后不再收到、重复订阅幂等、空总线 emit 返回 0。
2. 确认失败 → 实现（`dict[TaskEventType, list[Hook]]` + 内部去重）。
3. 全绿 + `uv run pytest tests/test_scheduler -q`。
4. 提交 `feat(scheduler): EventBus 异步事件总线(hook 注册/异常隔离/退订)`。

---

### Task 4: 存储层——两张表 + TaskStore

**Files:**
- Create: `src/thumbelina/scheduler/store.py`
- Test: `tests/test_scheduler/test_store.py`

**Interfaces:**
- Consumes: `thumbelina.repository.models.Base`（同一 metadata）、`repository/db.py:create_db_engine/init_db`
- Produces:
  - `ScheduledTaskRecord` / `TaskEventRecord`（DDL 对齐设计文档 §7.1；表名 `scheduled_tasks`/`task_events`）
  - `class TaskStore:` 构造 `TaskStore(engine: Engine)`；方法（全部 async，内部 `asyncio.to_thread`）：`upsert_task(task: ScheduledTask)`、`get_task(task_id) -> ScheduledTask | None`、`list_tasks() -> list[ScheduledTask]`、`delete_task(task_id)`、`list_due(now, grace) -> list[ScheduledTask]`（PENDING 且 (once ∧ scheduled_at<=now) ∨ (cron ∧ next_run_at<=now)）、`append_event(event: TaskEvent)`、`list_events(limit) -> list[TaskEvent]`、`prune_events(keep: int) -> int`、`counts() -> dict[str, int]`
  - record ↔ dataclass 双向映射（`_to_record`/`_to_model` 私有方法）
- 注意：`engine` 为共享主库 engine（`repository.engine`），**不 close、不 dispose**；表由 `init_db` 的 `create_all` 建（测试里直接 `Base.metadata.create_all(engine)`）。

**Steps:**
1. 失败测试（tmp 目录 sqlite 文件库）：round-trip 全字段、`list_due` 只含到期 PENDING（排除 PAUSED/RUNNING/未来）、`list_events` 倒序 + limit、`prune_events` 保留最新 N 条并返回删除数、`counts` 按状态计数、payload 非 JSON 写入被 CHECK 拒绝。
2. 确认失败 → 实现（ORM 模型 `CheckConstraint` + `Index` 声明式落齐；时间列 `DateTime`）。
3. `uv run pytest tests/test_scheduler -q` 全绿；`uv run python -c "from thumbelina.repository.db import create_db_engine, init_db; from thumbelina.scheduler.store import TaskStore"` 冒烟（create_all 含新表）。
4. 提交 `feat(scheduler): scheduled_tasks/task_events 持久化与 TaskStore`。

---

### Task 5: TaskScheduler v2（到期扫描 + 事件 + recover + pause/resume）

**Files:**
- Modify: `src/thumbelina/scheduler/scheduler.py`（核心重写）
- Test: `tests/test_scheduler/test_scheduler.py`（存量用例全保留 + 新增 cron/pause/recover 用例）

**Interfaces:**
- Consumes: `models`（T1）、`EventBus`（T3，可选注入）、`TaskStore`（T4，可选注入）、`CronTrigger`（T2）、`TimeParser`（不动）
- Produces（在兼容 API 之上新增）:
  - `TaskScheduler(store=None, bus=None, check_condition=None, config=None)`（全可空：无 store 时纯内存 = v1 行为；无 bus 时事件静默丢弃）
  - `async recover(now=None) -> None`（设计文档 §7.2 五条规则；无 store 时 no-op）
  - `async pause_task(task_id) -> bool` / `async resume_task(task_id) -> bool`（仅 CRON；resume 重算 next_run）
  - `async add_task_from(expr: …)` 不新增——`add_task` 直接接收 v2 `ScheduledTask`（cron 任务的 `next_run` 由 add_task 时计算兜底，未填则 `CronTrigger(expr).next_after(now)`）
- 行为变更点（**唯一**存量断言修正）：回调抛异常时任务置 `FAILED`（原为 `CANCELLED`）+ emit `task.failed`；同步更新 `test_poll_handles_callback_error` 断言。
- 跃迁持久化：状态每次变更 `store.upsert_task`（store 注入时）；事件发射：`CREATED`（add_task/cancel/pause/resume 亦发）、`DUE`（status→RUNNING 后、回调前）、回调结果对应 `COMPLETED/FAILED`；cron 任务回调成功后 `status=PENDING`、`next_run=CronTrigger.next_after(now)`（回调失败保持 PENDING，`error` 落库）。
- 条件任务：`condition` + `check_condition` 分支保持原语义（条件不满足 → 不置 RUNNING、不发 DUE）。

**Steps:**
1. 先跑 `uv run pytest tests/test_scheduler/test_scheduler.py -q` 记录存量绿基线。
2. 写失败测试（追加）：cron 任务到期触发后回 PENDING 且 next_run 前推；cron 回调失败仍 PENDING 且 error 落库；pause 后不触发 / resume 后恢复；recover 设计文档 §7.2 全部规则（过期 once→MISSED+事件、宽限内 once→立即触发、once/cron 残留 RUNNING→FAILED、cron next_run 前推+汇总 missed 事件）；store 注入时状态跃迁落库；bus 注入时事件类型序列断言（如 once 全生命周期 = created→due→completed）；无 store/无 bus 构造可用。
3. 确认失败 → 重写 `scheduler.py`（保持动态休眠逻辑与 `_POLL_INTERVAL` 优化；`stop()` 语义不变）。
4. `uv run pytest tests/test_scheduler -q` 全绿（含存量；修正 `test_poll_handles_callback_error` 的 CANCELLED→FAILED 断言，注释注明设计文档 D10）。
5. 提交 `feat(scheduler): v2 事件驱动调度(cron 循环/一次定时/recover/pause)`。

---

### Task 6: Heartbeat（定时巡检）

**Files:**
- Create: `src/thumbelina/scheduler/heartbeat.py`
- Test: `tests/test_scheduler/test_heartbeat.py`

**Interfaces:**
- Consumes: `TaskScheduler`（读/修任务、`_poll_task` 存活、拉起循环）、`EventBus`、`SchedulerConfig`（T8 前用同形 stub/简单 dataclass 注入）
- Produces: `class Heartbeat: __init__(scheduler, bus, config)`、`async start()` / `async stop()`、`def status() -> dict`（`{running, last_heartbeat_at, task_counts, checks}`）
- 巡检项与处置 = 设计文档 §7.4 表（逐项可单测；巡检实现抽 `_run_checks(now) -> list[str]` 纯异步方法，循环只是定时调用它）。

**Steps:**
1. 失败测试（`interval=0.05` 短轮询 + 假时钟/可控 now 注入）：僵尸 RUNNING→FAILED+事件；cron next_run 落后→前推+汇总 missed 事件；once 过期超 grace→按 policy mark 置 MISSED（run 策略置 PENDING 立即到期）；`task_events` 超 retention→修剪；`_poll_task` 被人为 cancel→下一个周期被拉起且 `scheduler.running` 恢复 True；`status()` 快照字段。
2. 确认失败 → 实现（独立 `asyncio.Task`，`stop()` 语义对齐 scheduler；巡检异常只记日志不终止循环）。
3. `uv run pytest tests/test_scheduler -q` 全绿。
4. 提交 `feat(scheduler): Heartbeat 巡检(存活拉起/僵尸清理/错过处置/日志修剪)`。

---

### Task 7: DeliveryDispatcher（渠道交付）

**Files:**
- Create: `src/thumbelina/scheduler/dispatcher.py`
- Test: `tests/test_scheduler/test_dispatcher.py`

**Interfaces:**
- Consumes: `EventBus`、`TaskEvent`、`Channel`（`channels/base.py` ABC）
- Produces: `class DeliveryDispatcher:` 构造 `DeliveryDispatcher(channels: dict[str, Channel], web_push: Callable[[dict], Awaitable[None]] | None = None, bus: EventBus | None = None)`；**唯一交付入口** `async on_due_task(task: ScheduledTask) -> None`（直接作为 `scheduler.start(on_due_task=…)` 的回调；**不订阅总线**——`task.due` 仅供观察者 hooks，Dispatcher 内部只经 bus emit `COMPLETED/FAILED`，避免"订阅+回调"双触发）
- 交付语义（按 `task.channel`）：
  - `web`：`web_push({"task_event": …COMPLETED 帧正文…})`；`web_push` 为 None 时视为成功（前端未接只跳过）
  - `wechat`/`qq`：`channel.send_message(channel.last_user_id or "", task.content)`；渠道不在 `channels` 表 → FAILED（error="channel not available"）；`last_user_id` 为空 → FAILED（error="no recent user on channel"）
  - `mode != "notify"` → FAILED（error="mode not supported yet"）（prompt 模式预留位）
- 回发：交付成功 emit `task.completed`（payload.result=回执摘要）、失败 emit `task.failed`（payload.error）；异常全部捕获转为 FAILED，不向调度器抛（保 D5 内联 await 稳定）。

**Steps:**
1. 失败测试：Fake Channel（记录 send 参数/可控返回与异常）×（web 成功、渠道缺失、无 last_user_id、send 抛异常、未知 mode、bus 回发事件类型与 payload 断言）；`on_due_task` 重复调用同一 task 产生两次独立交付（断言无去重副作用，路径唯一性由 T8 装配保证——只注册回调不注册订阅）。
2. 确认失败 → 实现。
3. `uv run pytest tests/test_scheduler -q` 全绿。
4. 提交 `feat(scheduler): DeliveryDispatcher 按渠道交付内容并回发完成/失败事件`。

---

### Task 8: 配置 + app 装配 + API 路由

**Files:**
- Modify: `src/thumbelina/config/models.py`（`SchedulerConfig` + `AppConfig.scheduler`）
- Modify: `src/thumbelina/api/app.py`（lifespan 397-415 段重写 + shutdown 段补 heartbeat.stop）
- Modify: `src/thumbelina/api/routes/tasks.py`（新端点 + GET /tasks 扩展字段）
- Modify: `thumbelina.yaml.example`（scheduler 段注释示例）
- Test: `tests/test_api/test_tasks.py`（新建；沿用共享 conftest 的 TestClient，scheduler 相关用例往 `app.state` 注入真实/可控实例）

**Interfaces:**
- `SchedulerConfig` 字段 = 设计文档 §10；`AppConfig.scheduler` 默认工厂。
- app 装配顺序 = 设计文档 §5.3：`TaskStore(repository.engine)` → `EventBus` → 观察者 hooks（event_log → web_push）→ `DeliveryDispatcher(channels, web_push, bus)` → `TaskScheduler(store, bus, config=config.scheduler)` → `recover()` → `start(on_due_task=dispatcher.on_due_task)` → `heartbeat.start()`（Dispatcher **只挂回调、不挂总线订阅**）；`finally`/shutdown：`heartbeat.stop()` + `scheduler.stop()`（现有 stop 调用保留）。异常守卫维持"降级不挂"（scheduler 相关对象置 None，路由判空）。
- 路由：`POST /tasks`（422 校验：cron 非法/once 缺 scheduled_time/channel 非法）、`POST /tasks/{id}/pause|resume`（409 状态不合法、404 不存在）、`GET /tasks/events?limit=`、`GET /tasks/scheduler/status`（scheduler 不可用 → 503）；`GET /tasks` 响应增 `trigger/cron/next_run/last_run/channel/content/mode/source/error`（原 4 键逐字保留）。
- `NotificationManager` 兼容帧：web_push hook 内同时 `notification_manager.broadcast({"type":"task_completed", …})`（存量行为保留，顺带修复"零订阅者"现状说明——前端如订阅即收）。

**Steps:**
1. 失败测试：`SchedulerConfig` 默认值与 yaml 覆盖（env/YAML 现有机制）；`POST /tasks` 创建 once/cron 成功与三类 422；`GET /tasks` 新字段存在且旧字段不变；pause/resume 状态机（409/404）；`/tasks/events` 返回倒序事件；`/scheduler/status` 200 与 503 两分支；cron 非法表达式 422。
2. 确认失败 → 实现 config → 路由 → app 装配（装配处只做接线，不写业务逻辑）。
3. `uv run pytest tests/test_api tests/test_scheduler -q` 全绿；`uv run python -c "from thumbelina.main import create_app"` 冒烟（若无此入口则 `thumbelina-serve --help` 级别冒烟即可）。
4. 更新 `thumbelina.yaml.example` scheduler 段。
5. 提交 `feat(api): 任务 API 扩展(创建/暂停恢复/事件流/调度状态)+事件管线装配`。

---

### Task 9: Agent 工具扩展（schedule_task +cron/channel）

**Files:**
- Modify: `src/thumbelina/tools/event_trigger.py`
- Test: `tests/test_tools/test_event_trigger.py`（追加用例）

**Interfaces:**
- `_ScheduleTaskArgs` 增：`cron_expression: str = ""`、`channel: str = ""`（空串=默认 web；大小写不敏感）。`cron_expression` 与 `time_expression` 互斥：同时给出返回 `Error: provide either time_expression or cron_expression, not both.`。
- `schedule_task`：cron 分支经 `validate_cron` 校验（非法 → `Error: Invalid cron expression: <expr>`），成功返回文案增 `Cron: <expr>. Channel: <ch>.`；once 分支返回文案不变。渠道名非法 → `Error: Unknown channel '<name>'. Available: web, wechat, qq.`
- `list_scheduled_tasks`：每行增 `, Trigger: cron(*/30 * * * *), Next: <iso>` 或 `, Trigger: once` 与 `, Channel: <ch>`；无任务文案 `"No scheduled tasks found."` 不变。
- `ScheduledTask` 构造传 `source="agent"`、`content=description`（notify 模式交付内容即描述）、`channel`。

**Steps:**
1. 失败测试（追加）：cron 创建成功（断言假 scheduler 收到的 task.trigger/cron_expr/channel/next_run 非空）；互斥报错；非法 cron；非法 channel；list 输出含 Trigger/Channel 字段；**存量用例不改断言**（旧两参调用返回文案逐字兼容）。
2. 确认失败 → 实现修改。
3. `uv run pytest tests/test_tools -q` 全绿。
4. 提交 `feat(tools): schedule_task 支持 cron 表达式与交付渠道`。

---

### Task 10: 前端——任务页实时展示

**Files:**
- Create: `frontend/src/api/tasks.ts`、`frontend/src/components/Tasks/TaskEventFeed.tsx`
- Modify: `frontend/src/hooks/useWebSocket.ts`（`task_event` 派发）、`frontend/src/components/Tasks/TaskManager.tsx`、`frontend/src/i18n/locales/en.json`、`zh-CN.json`
- Test: `frontend/src/api/tasks.test.ts`（新）、`frontend/src/components/Tasks/TaskManager.test.tsx`（扩展）、`TaskEventFeed.test.tsx`（新）

**Interfaces:**
- `tasks.ts`：`ScheduledTaskVO/TaskEventVO/SchedulerStatusVO` 类型 + `listTasks/createTask/cancelTask/pauseTask/resumeTask/listEvents/schedulerStatus`（统一走本模块，替换 TaskManager 现有全部裸 fetch——`fetchData` 2 处 + cancel 2 处，新增 pause/resume 也从这里走，主题六 D9 的 Tasks 项就地清零）。
- `useWebSocket`：`ServerPush` 增 `task_event?: TaskEventPayload`；在现有 `if (data.git_branch)` 派发点旁并列 `if (data.task_event)` 派发（notify 语义与异常隔离同 git_branch）。
- `TaskManager`：定时任务卡片行字段 = 触发徽章（`once` 灰 / `cron` 蓝含表达式）、下次触发时间（cron 用 `next_run` 本地化）、渠道徽章、内容摘要（截断 80 字符）、状态徽章（新增 failed=红 / paused=黄 / missed=橙）；操作按钮 = cron：暂停/恢复 + 取消，once：取消（仅 PENDING/RUNNING/PAUSED 显示）；`task_event` 帧到达即 `void fetchData()`（节流 500ms）；页头存活指示点（`schedulerStatus().running`，绿/灰，30s 慢轮询）。
- `TaskEventFeed`：最近 50 条事件（`GET /tasks/events`），行 = 时间 | 类型徽章 | 渠道 | 内容 | payload.error（有则红字）；`task_event` 帧到达头部插入（上限 50）。
- i18n 键：`taskManager.triggerOnce/triggerCron/pause/resume/eventsTitle/schedulerAlive/schedulerDown/fieldChannel/fieldNextRun/…`（en + zh-CN 成对）。

**Steps:**
1. 失败测试：`tasks.test.ts`（msw/fetch mock 断言方法与路径）；`TaskManager.test.tsx` 扩展（cron 行渲染表达式与下次触发、暂停按钮调 pauseTask、WS `task_event` 触发刷新——用测试内捕获 subscribe 回调注入帧）；`TaskEventFeed.test.tsx`（渲染事件行、error 红字、上限 50）。
2. 确认失败 → 实现（组件改造保持 `data-testid` 存量键不删：`task-list/task-item/task-status/cancel-task` 等，测试与潜在 e2e 依赖不受损）。
3. `cd frontend && npm test && npm run build` 全绿。
4. 提交 `feat(tasks): 任务页实时展示(cron/渠道/暂停恢复/事件流/存活指示)`。

---

### Task 11: 收尾——全量回归 + 文档同步

**Files:**
- Modify: `README.md`、`README_CN.md`（调度器段落：事件驱动/cron/heartbeat/任务页能力）、`CLAUDE.md`（Architecture 的 scheduler 段与 Request Flow 的 /tasks 行）

**Steps:**
1. `uv run pytest -q` 全量绿；`ruff check src/ tests/`；`ruff format --check src/thumbelina/scheduler`；`mypy src/`。
2. `cd frontend && npm run lint && npm test && npm run build`。
3. 手工冒烟（本地 `python start_dev.py`）：agent 对话 `schedule_task` 一次性 + `*/1 * * * *` cron 各一条 → 任务页实时出现 → 到期触发事件流滚动 → 暂停/恢复/取消 → 重启后端验证 recover（宽限外标 MISSED、cron 前推）。
4. 文档同步提交：`docs: 同步事件驱动定时任务文档(README/CLAUDE)`。
5. （可选）`git tag` 前确认 `deploy/` 无需变更（无新环境变量/端口）。

---

## Self-Review（计划对照设计文档）

- D1 兼容 API：T5 明确保留清单 + 存量用例门禁；唯一断言修正（CANCELLED→FAILED）在 T5 显式列出并回链 D10。✔
- D2 croniter：T2 覆盖语义与拒绝用例。✔ D3 存储：T4 挂 `Base` metadata + T8 共享 engine。✔ D4/D5 事件与内联：T3/T5/T7。✔
- D6 错过策略：T5 recover + T6 巡检各覆盖一次（mark/run 双分支）。✔ D7 渠道：T7 三渠道语义 + 缺渠道/缺用户分支。✔
- D8 WS 帧：T8 web_push hook + T10 派发点与帧格式。✔ D9 事件日志：T4 append/prune + T8 events 端点 + T10 Feed。✔ D10 状态机：T1 枚举 + T5 跃迁 + T10 配色。✔
- 降级红线（设计 §11）：T4 store 容错、T5 无 store/bus 构造、T8 装配守卫、T6 巡检不雪崩——各任务 Step 内有对应测试点。✔
- 范围外项（设计 §1.3）：无任务实现 prompt 模式/前端表单/WS ping/条件注册表；T7 仅留 mode 预留位。✔
