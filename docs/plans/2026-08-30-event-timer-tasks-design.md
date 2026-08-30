# 事件触发定时任务（定时器 Tool + 事件驱动调度）设计

- 日期：2026-08-30
- 状态：待评审
- 关联文档：
  - `docs/plans/2026-08-29-architecture-refactoring-plan.md` 总规划 **主题五**（调度真执行、持久化、recover——本设计是其"调度事件化"方向的落地细化，且可独立合入）
  - `docs/specs/2026-08-29-tools-taxonomy-design.md` 事件触发工具分类（本设计只扩展 `tools/event_trigger.py`，不动基类体系）
  - 注：总规划主题二（存储重构）已回退、不再进行——本设计对它**零依赖**（见 D3），建表走现有 `init_db` 的 `create_all`。

---

## 1. 背景与目标

### 1.1 现状（读码取证，file:line 均为 2026-08-30 工作区）

| # | 现状 | 证据 |
|---|---|---|
| 1 | 调度器是**演示态**：任务存内存 dict，重启即蒸发；`_on_due_task` 只广播一条 `task_completed`，不执行任何交付 | `scheduler/scheduler.py:77`、`api/app.py:404-413` |
| 2 | `NotificationManager.subscribe()` 全仓零调用方，`task_completed` 广播无人接收 | `notifications.py:23` |
| 3 | 无 cron 支持：`TimeParser.parse_recurring` 只把"每天"等词映射成 `daily` 字符串，调度器根本不消费 | `scheduler/time_parser.py` |
| 4 | 无事件建模：到期即回调，无结构化事件对象，无事件日志 | `scheduler/scheduler.py:157-208` |
| 5 | 无心跳：轮询循环死亡无人拉起，错过的任务（进程休眠/停机）无处置 | `scheduler/scheduler.py:157` |
| 6 | 前端任务页 10s 轮询，无实时推送；展示字段只有 description/scheduled_time/status | `frontend/src/components/Tasks/TaskManager.tsx:50` |
| 7 | 前端已有 WS 广播订阅先例（`{git_branch}` 事件 + `subscribe()` 派发）可复用 | `hooks/useWebSocket.ts:212-214,684` |

### 1.2 目标

1. **事件触发 tool 升级**：`schedule_task` 支持 cron 表达式循环任务与一次性定时任务；支持指定交付消息渠道。
2. **异步事件驱动**：任务到期产生**结构化事件**，通过**事件回调 hooks** 分发给订阅方（WS 推送 / 渠道交付 / 事件日志），调度核心与交付解耦。
3. **可靠调度**：任务持久化、重启 recover；**Heartbeat** 定时巡检（循环存活、僵尸任务、错过补偿、日志修剪）。
4. **WEB 展示**：任务页实时展示定时任务（触发类型/cron/下次触发/渠道/内容/状态），支持暂停/恢复/取消与最近事件流。

### 1.3 明确不做（本期范围外，均留扩展点）

- **prompt 模式**（到期后把内容作为 prompt 跑 agent 并交付回复）：只预留 `mode` 字段与分发器 action 接口，不实现。总规划主题五修改点 2（agent.clone 执行链）依赖主题三/四装配，另行落地。
- 前端"新建任务"表单（API 先行：`POST /tasks`）。
- 条件触发器注册表（总规划主题五修改点 3，独立任务）。
- WS ping/pong 心跳协议（总规划主题五/主题六管辖，与本设计的调度 Heartbeat 无关）。
- 向插件系统暴露事件 hooks。

---

## 2. 关键决策记录

| # | 决策 | 理由 | 备选与否决 |
|---|---|---|---|
| D1 | **原地演进 `scheduler/`**，TaskScheduler v2 保持公共 API 兼容（`add_task/get_task/list_tasks/cancel_task/start(on_due_task=)/stop`） | agent 工具、路由、41 个现有测试、`agent.clone()` 共享实例都挂在现 API 上；兼容层让本设计可小步合入 | 新建 `tasks/` 子系统并行：双调度器并存必然混乱，否决 |
| D2 | cron 解析用 **`croniter>=2.0`**（纯 Python、MIT、零依赖） | 5 字段 cron + `@daily` 描述符 + 边界语义久经考验；手写解析器 ~150 行且 DST/月末边界易错 | 手写：维护成本不值；APScheduler：全家桶过重 |
| D3 | 持久化走**现有 `Base` metadata**（`repository/db.py:init_db` 的 `create_all` 自动建表），ORM 模型声明在 `scheduler/store.py`，engine 复用 `repository.engine` | 零迁移基建依赖（存储重构已回退，不引入 Alembic）；同一 metadata 保证全局唯一建表入口；所有权留在 scheduler/，与 `repository/` 仅共享引擎与 metadata，无反向耦合 | 引入 Alembic 独立迁移：当前无迁移基建且无多库诉求，YAGNI；独立 engine：一库多 engine 是既有债务，不再新增 |
| D4 | **进程内 EventBus**（async pub/sub + hook 注册表），不引入外部消息队列 | 单进程 FastAPI 应用，事件量极小；YAGNI | redis/asyncio.Queue 广播：无跨进程需求 |
| D5 | 到期执行保持**内联 await** 模型（调度器 await `on_due_task`），分发器作为该回调注册 | 与现有语义、现有测试一致；任务量小无并发饥饿风险；cron 任务完成后立即回 PENDING 并算 `next_run` | fire-and-forget create_task：异常难归位、压测无必要 |
| D6 | 错过策略：一次性任务超过宽限未触发 → 标 `MISSED` 并发事件，**默认不补跑**（`missed_policy=mark`，可选 `run`） | 补跑一批过期任务可能产生意外副作用/成本（总规划主题五已有同样顾虑） | 默认补跑：休眠后醒来突然执行 N 个旧任务，不可预期 |
| D7 | 交付渠道建模为 `channel ∈ {web, wechat, qq}`；`web` = WS 事件推送，`wechat/qq` = `Channel.send_message` 到该渠道最近用户 | 复用渠道现有 `last_user_id` 语义（与 `notify_user_by_channel` 工具一致） | 引入收件人字段：v1 无多用户概念，YAGNI |
| D8 | WS 实时刷新复用 **`{task_event: {...}}` 帧格式**，走 `useWebSocket.subscribe()` 现有派发模式 | 与 `git_branch` 帧同构，前端零新增机制 | 复用 `NotificationManager`：其 subscriber 表零接线且将被主题五重构 |
| D9 | 事件日志持久化到 `task_events` 表（容量上限，Heartbeat 修剪） | 事件是一等公民（用户明确要求建模结构化事件）；重启后任务页"最近触发记录"仍可追溯 | 仅内存 ring buffer：重启即丢，展示价值打折 |
| D10 | 状态枚举增量扩展：`PENDING/RUNNING/COMPLETED/CANCELLED` + 新增 `FAILED/PAUSED/MISSED` | 现有 4 值与全部存量断言保持不变；失败与取消语义分离（原实现把失败标成 CANCELLED 是 bug，本设计修正） | 复用 CANCELLED 表达失败：语义混淆 |

---

## 3. 事件模型（结构化事件）

事件是调度子系统的**一等公民**：任务状态每次跃迁都产生一条 `TaskEvent`，全部下游行为（WS 推送、渠道交付、事件日志）都是事件的订阅者，调度核心不感知任何下游。

```python
class TaskEventType(StrEnum):
    CREATED = "task.created"      # 任务被注册（agent tool / API）
    DUE = "task.due"              # 触发器到期，开始交付
    COMPLETED = "task.completed"  # 交付成功（cron 任务指本轮交付成功）
    FAILED = "task.failed"        # 交付失败（含渠道发送异常）
    MISSED = "task.missed"        # Heartbeat 判定错过（超宽限未触发）
    CANCELLED = "task.cancelled"  # 用户取消 / 暂停恢复外的终止

class TriggerKind(StrEnum):
    ONCE = "once"
    CRON = "cron"

class DeliveryChannel(StrEnum):
    WEB = "web"          # 前端 WebSocket 推送
    WECHAT = "wechat"    # 微信渠道 send_message
    QQ = "qq"            # QQ 渠道 send_message

@dataclass
class TaskEvent:
    id: str                       # uuid4
    type: TaskEventType
    task_id: str
    fired_at: datetime            # 事件产生时刻（本地 naive，与全库一致）
    trigger: TriggerKind
    channel: DeliveryChannel      # 消息渠道
    content: str                  # 交付内容（任务内容快照）
    payload: dict[str, Any]       # 扩展：error / scheduled_for / cron / result 摘要
```

**payload 约定**（各事件类型）：

| type | payload 键 |
|---|---|
| task.created | `source`（agent/web/api）、`trigger` 细节 |
| task.due | `scheduled_for`（计划触发时刻） |
| task.completed | `result`（交付回执摘要）、`duration_ms` |
| task.failed | `error`、`scheduled_for` |
| task.missed | `scheduled_for`、`policy`（mark/run） |
| task.cancelled | `by`（web/api） |

**事件流转**（hooks 均注册于 `app.py` 装配期）：

```
TaskEvent ──emit──▶ EventBus（仅观察者，全部只读不交付）
                    ├─ hook: EventLogHook  → 写 task_events 表（D9）
                    └─ hook: WebPushHook   → broadcast_chat_message({task_event:…})
                                             + NotificationManager.broadcast(task_completed 兼容帧)

交付不走总线订阅：DeliveryDispatcher 作为 scheduler.start(on_due_task=…) 的
唯一回调内联执行（D5）→ 按 channel 交付内容 → 经 bus emit COMPLETED/FAILED 供观察者。
（单一交付路径，避免"总线订阅 + 回调"双重触发。）
```

hook 隔离规则：单 hook 异常只记日志，不影响其他 hook 与调度主循环（见 §11）。

---

## 4. 任务模型

```python
class TaskStatus(StrEnum):
    PENDING = "pending"        # 等待触发（存量值）
    RUNNING = "running"        # 交付中（存量值）
    COMPLETED = "completed"    # 已完成（一次性终态 / cron 单轮成功）（存量值）
    CANCELLED = "cancelled"    # 已取消（存量值）
    FAILED = "failed"          # 交付失败（新增；一次性任务失败即终态）
    PAUSED = "paused"          # 已暂停（仅 cron；不触发、可恢复）（新增）
    MISSED = "missed"          # 错过（一次性 + 超宽限，终态）（新增）

@dataclass
class ScheduledTask:
    id: str
    description: str
    trigger: TriggerKind = TriggerKind.ONCE
    cron_expr: str | None = None        # trigger=CRON 时必填（5 字段）
    scheduled_time: datetime | None     # ONCE：触发时刻；CRON：创建基准（可空）
    next_run: datetime | None           # CRON：下次触发时刻（唯一调度依据）
    last_run: datetime | None
    status: TaskStatus = TaskStatus.PENDING
    channel: DeliveryChannel = DeliveryChannel.WEB
    content: str = ""                   # 交付内容（消息正文）
    mode: str = "notify"                # notify（本期唯一实现）/ prompt（预留）
    condition: str | None = None        # 兼容存量条件任务（语义不变）
    result: str | None = None
    error: str | None = None
    source: str = "agent"               # agent / web / api
    conversation_id: str | None = None  # 预留（会话关联；外键暂不落）
    created_at / updated_at: datetime
```

**兼容性**：`ScheduledTask(description=…, scheduled_time=…)` 两参构造（`tools/event_trigger.py:47` 现状）产出与 v1 行为等价的 ONCE/web 任务；`condition` 字段与 `check_condition` 回调语义原样保留。

**状态机**：

```
                    ┌───────── pause() ─────────▶ PAUSED ── resume() ─┐
                    │                            (仅 cron)            │
                    │                                                   ▼
  CREATED ──▶ PENDING ──到期──▶ RUNNING ──交付成功──▶ COMPLETED(once 终态)
                 │                 │        └─交付失败─▶ FAILED(once 终态)
                 │                 └────────── cron: 回 PENDING,算 next_run
                 ├──Heartbeat 超宽限──▶ MISSED(once 终态)
                 └──cancel()──▶ CANCELLED(终态)
```

**调度判据**（扫描循环）：`ONCE`：`status=PENDING ∧ scheduled_time <= now`；`CRON`：`status=PENDING ∧ next_run <= now`。`PAUSED` 一律跳过。

---

## 5. 架构与数据流

### 5.1 模块布局（最终态）

| 文件 | 职责 |
|---|---|
| `scheduler/models.py` 【新】 | `TaskStatus/TriggerKind/DeliveryChannel/TaskEventType`、`ScheduledTask`、`TaskEvent`（§3/§4 全部类型） |
| `scheduler/cron.py` 【新】 | `CronTrigger`：`validate(expr)`、`next_after(dt) -> datetime`（croniter 薄封装，本地 naive 时间） |
| `scheduler/events.py` 【新】 | `EventBus`：`subscribe(event_type, hook)/unsubscribe/emit(event)`；per-hook 异常隔离 |
| `scheduler/store.py` 【新】 | `TaskStore`：`ScheduledTaskRecord`/`TaskEventRecord` ORM（声明在 `Base` metadata）+ CRUD/到期查询/事件追加与修剪；同步 SQLAlchemy 经 `asyncio.to_thread` 包装（对齐 `ConversationRepository` 模式） |
| `scheduler/scheduler.py` 【重写核心，保 API】 | 到期扫描（ONCE+CRON）、发 DUE 事件、内联执行 `on_due_task`、cron 回写 `next_run`、状态跃迁持久化、`pause_task/resume_task`、`start` 时 recover |
| `scheduler/heartbeat.py` 【新】 | `Heartbeat` 周期巡检：扫描循环存活（死亡→拉起+事件）、僵尸 RUNNING 清理、cron `next_run` 修复、错过判定（§7.3）、事件日志修剪；`status()` 快照供 API |
| `scheduler/dispatcher.py` 【新】 | `DeliveryDispatcher`：作为 `on_due_task` 唯一交付入口，按 `channel` 交付 `content`（web→注入的 WS 广播回调；wechat/qq→`Channel.send_message` 最近用户），交付后经 bus emit `COMPLETED/FAILED`（不订阅总线，防双触发） |
| `scheduler/time_parser.py` 【不动】 | 自然语言解析保持现状 |
| `tools/event_trigger.py` 【扩展】 | `schedule_task` 增可选 `cron_expression`/`channel` 参数；`list_scheduled_tasks` 输出增字段 |
| `api/routes/tasks.py` 【扩展】 | 新端点（§8） |

### 5.2 触发时序（事件驱动主链路）

```
cron 到期 / once 到期
   │ TaskScheduler._poll_loop（动态休眠：max(1s, min(60s, 最近到期-Now))）
   ▼
status→RUNNING（持久化） ─▶ emit(TaskEvent.DUE) ─▶ EventBus 观察者：
   │                                            ├─ EventLogHook 写表
   │                                            └─ WebPushHook 推送
   ▼
await on_due_task(= dispatcher.on_due_task 适配入口，把 ScheduledTask 包为交付上下文)
   ├─ 交付成功：dispatcher emit COMPLETED；cron→status=PENDING+next_run=croniter.next(now)（持久化）
   │            once→status=COMPLETED（持久化）
   └─ 交付失败：dispatcher emit FAILED；once→FAILED 终态；cron→保持 PENDING 等下轮（error 记录）
```

### 5.3 app.py 装配（lifespan 内，替换现 397-415 段）

```python
store = TaskStore(repository.engine)                      # D3：共享 engine
bus = EventBus()
scheduler = TaskScheduler(store=store, bus=bus,
                          check_condition=…, config=config.scheduler)
scheduler.recover()                                       # 启动恢复（§7.2）
heartbeat = Heartbeat(scheduler, bus, config.scheduler)
# 交付唯一路径：Dispatcher 作为 on_due_task 回调（不经总线订阅，防双触发）
dispatcher = DeliveryDispatcher(channels=…, web_push=…, bus=bus)
await scheduler.start(on_due_task=dispatcher.on_due_task)  # 兼容签名不变
await heartbeat.start()
# 观察者 hooks 装配（顺序即 §3 事件流转；不含 Dispatcher）：
for ev_type in TaskEventType:
    bus.subscribe(ev_type, event_log_hook)
    bus.subscribe(ev_type, web_push_hook)
```

渠道交付需要 `wechat_channel`/`qq_channel` 引用：从 `app.state` 取，装配为 `DeliveryDispatcher(channels={"wechat": ch, "qq": ch}, web_push=broadcast_chat_message)`。渠道未启用时该渠道任务在交付期产出 `FAILED`（error="channel not available"），服务不降级。

优雅降级保持现状：scheduler/heartbeat 初始化失败 → `logger.warning` + 路由 503/空列表，服务器照常启动。

---

## 6. cron 规范

- 表达式：标准 5 字段 `分 时 日 月 周`（`* , - /` 均支持）+ `@daily/@hourly/@weekly/@monthly/@yearly/@midnight` 描述符；**不含秒**。
- 时区：**本地 naive 时间**，与全库 `datetime.now()` 口径一致；不做 DST 折叠处理（文档明示）。
- `next_run` 计算：触发完成后以 `croniter(expr, now).get_next(datetime)` 求下一次；Heartbeat 发现 `next_run` 落后于 now（如机器休眠）时同样前推，并按 `missed_policy` 对跳过的场次发 `task.missed`（只发一条汇总事件，不逐场补发）。
- 校验：创建时 `CronTrigger.validate()` 失败即拒绝（工具返回 `Error: Invalid cron expression: …`；API 返回 422）。

---

## 7. 持久化与恢复

### 7.1 表结构（新建；由现有 `init_db` 的 `Base.metadata.create_all` 自动创建，无迁移脚本）

```sql
CREATE TABLE scheduled_tasks (
    id              VARCHAR(36) PRIMARY KEY,
    description     TEXT        NOT NULL,
    trigger_kind    VARCHAR(10) NOT NULL DEFAULT 'once',          -- once|cron
    cron_expr       VARCHAR(100),                                  -- cron 必填
    scheduled_at    DATETIME,                                      -- once 触发时刻
    next_run_at     DATETIME,                                      -- cron 下次触发
    last_run_at     DATETIME,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','running','completed',
                                          'cancelled','failed','paused','missed')),
    channel         VARCHAR(20) NOT NULL DEFAULT 'web',
    content         TEXT        NOT NULL DEFAULT '',
    mode            VARCHAR(10) NOT NULL DEFAULT 'notify',
    condition       VARCHAR(200),
    result          TEXT,
    error           TEXT,
    source          VARCHAR(20) NOT NULL DEFAULT 'agent',
    conversation_id VARCHAR(36),
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_scheduled_tasks_due   ON scheduled_tasks(status, scheduled_at);
CREATE INDEX ix_scheduled_tasks_next  ON scheduled_tasks(status, next_run_at);

CREATE TABLE task_events (
    id          VARCHAR(36) PRIMARY KEY,
    task_id     VARCHAR(36) NOT NULL,
    event_type  VARCHAR(20) NOT NULL,      -- task.created|due|completed|failed|missed|cancelled
    channel     VARCHAR(20),
    content     TEXT,
    payload     TEXT CHECK (payload IS NULL OR json_valid(payload)),
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_task_events_task ON task_events(task_id, created_at DESC);
```

> 状态值统一小写，与 `TaskStatus.value`（StrEnum 小写成员）逐字一致；存量消息/会话表不受影响。

### 7.2 启动 recover（`scheduler.recover()`，`start()` 前调用）

1. `ONCE ∧ PENDING ∧ scheduled_at <= now - grace` → 按策略处置（§7.3）。
2. `ONCE ∧ PENDING ∧ scheduled_at ∈ (now-grace, now]` → 视为"停机期间到期"，立即按正常到期流程触发（宽限内的迟到不算错过）。
3. `ONCE ∧ RUNNING`（停机残留）→ `FAILED`（error="interrupted by restart"）。
4. `CRON ∧ PENDING ∧ next_run <= now` → 前推 `next_run` 至未来最近场次；跳过场次按策略发汇总 `task.missed`。
5. `CRON ∧ RUNNING` → 同 3。

### 7.3 错过策略（`scheduler.missed_policy`）

- `mark`（默认）：`ONCE` → `MISSED` 终态 + `task.missed` 事件；cron 跳过场次只发事件。
- `run`：宽限内的迟到任务立即触发（第 2 条规则扩展到任意过期量）；仍不重放 cron 已跳过的多个场次（最多触发一次）。

### 7.4 Heartbeat 巡检项（每 `heartbeat_interval_seconds`（默认 30s））

| 巡检项 | 处置 |
|---|---|
| 扫描循环 `_poll_task` 存活 | 死亡/取消 → 重新拉起 + `logger.error` + 系统事件日志 |
| `RUNNING` 超过 `stale_running_minutes`（默认 10） | 置 `FAILED`（error="stale running"）+ `task.failed` 事件 |
| cron `next_run` 落后 now | 前推 + 按 §7.3 发 `task.missed` 汇总 |
| `task_events` 超过 `event_retention`（默认 500 行） | 按 created_at 修剪到上限 |
| 维护 `last_heartbeat_at`（内存） | 供 `GET /tasks/scheduler/status` 展示存活 |

注（最终评审裁定，内联交付模型 D5）：错过判定（once 过期超宽限 → MISSED，及 cron `next_run` 落后的 §7.3 处置）仅作用于**扫描循环死亡**（`running` 且 `_poll_task` done/None）或启动 `recover()` 场景——循环存活（含被交付阻塞）时队列积压 ≠ 错过，heartbeat 不标 MISSED，防静默丢弃排队任务；僵尸 `RUNNING` 的 `FAILED` 定论（stale running 复收）**优先于回调晚到的完成**——交付回调返回后 `_fire_task` 不覆写状态、不补发 `COMPLETED`/`PENDING`。

---

## 8. API 与 WebSocket 协议

### 8.1 REST（`api/routes/tasks.py`，前缀 `/api/v1`）

| 方法/路径 | 说明 |
|---|---|
| `GET /tasks` | 现有端点扩展字段：`trigger/cron/next_run/last_run/channel/content/mode/source/error`（原有 4 键逐字保留） |
| `POST /tasks` | 新建：`{description, trigger:"once"/"cron", scheduled_time?/cron?, channel?, content?}`；校验失败 422 |
| `POST /tasks/{id}/cancel` | 现有，语义不变（PAUSED 也可取消） |
| `POST /tasks/{id}/pause` | 仅 CRON 且 PENDING；否则 409 |
| `POST /tasks/{id}/resume` | 仅 CRON 且 PAUSED；恢复时重算 `next_run` |
| `GET /tasks/events?limit=50` | 最近事件流（倒序，默认 50 上限 200） |
| `GET /tasks/scheduler/status` | `{running, last_heartbeat_at, task_counts{…}}` |

### 8.2 WebSocket 帧（`/ws/chat` 复用，`{task_event: …}` 与 `{git_branch: …}` 同构）

```json
{"task_event": {"id": "…", "type": "task.completed", "task_id": "…",
                "fired_at": "2026-08-30T09:00:00", "trigger": "cron",
                "channel": "web", "content": "早安简报已生成",
                "payload": {"result": "…"}}}
```

`NotificationManager.broadcast` 的 `task_completed` 帧继续发送（兼容存量消费方），由 WebPushHook 一并完成。

---

## 9. 前端（任务页）

- `api/tasks.ts`【新】：类型化客户端（`ScheduledTaskVO/TaskEventVO/SchedulerStatus` + list/create/cancel/pause/resume/events/status），任务页改造后不再裸 `fetch`（顺带覆盖主题六 D9 的 Tasks 4 处）。
- `hooks/useWebSocket.ts`：`ServerPush` 类型加 `task_event`，在现有 `git_branch` 派发点旁并列一处 `data.task_event` 派发（约 5 行）。
- `TaskManager.tsx` 改造：
  - 「定时任务」卡片字段升级：触发类型徽章（一次性/cron + 表达式）、下次触发时间（cron）、渠道徽章、内容摘要、状态徽章（新增 failed/paused/missed 配色）；
  - 操作：一次性 → 取消；cron → 暂停/恢复 + 取消；
  - WS `task_event` 到达即刷新（保留 10s 轮询兜底）；
  - 调度器存活指示点（绿/灰，来自 `scheduler/status`）。
- `TaskEventFeed.tsx`【新】：「最近触发记录」卡片（时间/类型/渠道/内容/错误），数据源 `GET /tasks/events` + WS 增量。
- i18n：`taskManager.*` 新键补齐 `en.json`/`zh-CN.json`。

---

## 10. 配置（`config/models.py` + `thumbelina.yaml.example`）

```python
class SchedulerConfig(BaseModel):
    enabled: bool = True
    heartbeat_interval_seconds: int = 30
    missed_policy: Literal["mark", "run"] = "mark"
    missed_grace_minutes: int = 5
    stale_running_minutes: int = 10
    event_retention: int = 500
    default_channel: Literal["web", "wechat", "qq"] = "web"
```

`AppConfig` 增 `scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)`；全部有默认值，YAML 缺省该段零行为差异；数据库 KV 覆盖沿用 `RuntimeConfigManager` 现有机制，无需扩展。

---

## 11. 错误处理

| 场景 | 行为 |
|---|---|
| hook 抛异常 | EventBus 逐 hook `try/except` + `logger.warning`，不影响其余 hook 与主循环 |
| 渠道发送异常/渠道未启用 | Dispatcher emit `task.failed`（error 带原因）；cron 保持 PENDING 等下轮，once 终态 FAILED |
| 扫描循环崩溃 | Heartbeat 拉起 + 事件日志；连续失败只记日志不雪崩重启（间隔退避由巡检周期天然保证） |
| croniter 解析失败 | 创建入口拒绝（工具 `Error:` 文案 / API 422），运行期不可能出现非法表达式 |
| 存储不可用 | TaskStore 抛错 → 调度器回退内存 dict 运行并 `logger.warning`（降级为 v1 行为，服务器不挂） |
| 调度器初始化失败 | 维持现状守卫：路由返回空/503，服务器照常启动 |

---

## 12. 测试策略

- 后端 pytest（`asyncio_mode=auto`，mirror `tests/test_scheduler/`）：models 构造兼容/状态枚举增量；cron 校验与 next_after（含月末/`*/n`/描述符）；EventBus 派发顺序与异常隔离；store CRUD + recover 查询 + 事件修剪（tmp sqlite）；scheduler v2 到期扫描（once/cron/pause/missed 策略）+ **存量 41 个用例除"失败标 CANCELLED"一处断言外全绿**；heartbeat 各巡检项（短间隔注入）；dispatcher 假渠道交付；API 新端点（共享 conftest）。
- 工具层：`tests/test_tools/test_event_trigger.py` 增 cron/channel 用例；名称回归不变。
- 前端 Vitest：`TaskManager.test.tsx` 升级（徽章/操作/WS 刷新）、`TaskEventFeed` 新测。
- 门禁：`uv run pytest -q` 全绿、`ruff check`、`mypy src/`（strict）、`cd frontend && npm test && npm run build`。

---

## 13. 交付边界

- 单独可合入，不依赖任何重构主题（存储重构已回退，本设计对其零依赖）；两张表由现有 `init_db` 的 `create_all` 自动创建，无迁移脚本，revert 代码后保留表无害。
- 主题五修改点 2（agent 执行链）后续落地时：`mode="prompt"` 走 Dispatcher 的 action 扩展点，事件管线与任务页零改动。
