# 主题二「存储地基统一」详细设计与任务拆解

- 日期：2026-08-29
- 定位：本文是 `docs/plans/2026-08-29-architecture-refactoring-plan.md`（下称"总规划"）**§3 主题二（存储地基统一，对应 D1–D12）** 的可执行细化，产出目标 schema、Alembic 落地、代码层设计、测试/演练与任务拆解。总规划给"改什么/为什么"，本文给"改成什么样 DDL、按什么顺序迁移、拆成哪些可独立合入的 PR"。
- 取证口径：
  - 源码依据均带 `file:line`（工作目录 `F:\projects\thumbelina`）。
  - 运行库 `thumbelina.db` 以**只读**方式实查（`.venv/Scripts/python` + `sqlite3.connect('file:thumbelina.db?mode=ro', uri=True)`），作为 baseline migration 的事实来源。本次评审**不修改任何代码与数据**，仅落盘本设计文档。
  - 版本前提核查结果：`.venv` Python 自带 **SQLite 3.51.1**（≥3.35 ✅），FTS5 建表探针通过 ✅，`json_valid`（JSON1）可用 ✅。容器基座为 `python:3.11-slim`（Debian bookworm，系统 libsqlite3 ≈3.40.1，仍 ≥3.35），但**须在 CI 与启动断言中双环境验证**（见 §2.6、T2-31）。

### 0.1 运行库 baseline 实测事实（本文一切 DDL 的锚点）

| 表 | 行数 | 关键实测结论 |
|---|---|---|
| conversations | 5 | 无 `user_id`/`owner` 列；`mode` 仅 `chat`/`coder`；`thinking_effort` 仅 `medium`；`knowledge_base_id` 全部命中 `knowledge_bases`（0 违规）→ 跨域 FK 可挂 |
| messages | 30 | **无 `seq` 列**；DDL 已声明 `FK conversation_id→conversations ON DELETE CASCADE`（但 pragma 关）；`role` 仅 `user`/`assistant`；0 孤儿；`(conversation_id,created_at)` 无重复（当前 30 行），但 `created_at` 为 **19 位秒级 naive**（`CURRENT_TIMESTAMP`=UTC），同秒并发排序不确定（D2） |
| trajectory_events | 169 | 有 `seq`（轮次内，0 碰撞，与 messages.seq 语义不同）；DDL 已声明 FK；**32 行孤儿**（conversation 不存在）；`payload` 0 行非法 JSON → `json_valid` CHECK 可满足；`event_type` ∈ {user,context,assistant,tool_call,tool_result,llm_usage} |
| feedback | 3 | **表上无任何 FK**（D1 属实）；**1 行孤儿**（conv `58fca8a8` 不存在）；`skill_id` 全 NULL（skills 空表 → FK 可挂）；`rating` ∈ [5,5] ⊂ [1,5] CHECK 可满足；`created_at` naive（部分行疑为 `datetime.now()` 本地时间，见 D9） |
| skills / skill_compositions | 0 / 0 | `trigger_conditions/steps/skill_ids/trigger_patterns` 存裸 TEXT JSON，0 非法；`skills.created_at` 类型为 **TIMESTAMP**（与 ORM `DateTime` 漂移，D4 实证） |
| system_config | 18 键 | 含 `llm_endpoints.index` + 3 个 `llm_endpoints.<uuid>`（值 587–1139 字符，内含明文 `api_key`）；**新旧并存键**：`provider`="openai" vs `llm.provider`="openai"（同值）、`model`="mimo-v2.5" vs `llm.model`="deepseek-v4-flash"（**异值**）、`base_url` 亦异值（D11）；`runtime_manager.load_from_database`（`config/runtime_manager.py:302-308`）只读 `db_config["llm"].*` → 裸 `provider/model/base_url` 为**已死键**，可安全删 |
| knowledge_bases / rag_documents / rag_chunk_fingerprints | 3 / 3 / 1282 | RAG 第二 Base（`rag/common/orm_models.py:11`）；`rag_documents` DDL 列序漂移（`sha256/sim_hash_64` 追加在末尾，D4）；指纹表 raw-SQL 建（`rag/common/db.py:214-255`）且索引齐全 |
| simhash_index (+ _chunks/_info/_rowids/_vector_chunks00) | 虚拟表 | sqlite-vec `vec0`（`rag/common/db.py:87`）+ 4 张 shadow 表，**不受 ORM 管理** |
| checkpoints / writes | 74 / 88 | LangGraph `SqliteSaver` 私有表（`api/app.py:228-232`，aiosqlite 异步连接），**非主题二管辖**，alembic 须排除 |
| user_profiles / user_preferences | 0 / 0 | 僵尸表（源码 `user_profile*.py` 已删，仅存 `.pyc`），带 `ix_*_user_id` 索引；`ensure_schema` 只加不删（D4）→ 本主题 DROP |

> 关键判定：**FK ON 之前必须先清孤儿**（32+1 行），否则旧查询报错（总规划 §5.1）。所有 CHECK / `json_valid` / 跨域 FK 在真实数据上均已验证可满足——本文据此放行迁移。

### 0.2 关键源码结构事实（engine 拓扑，D3 取证）

`create_db_engine` 仅一处（`repository/db.py:13-29`）：内存库用 `StaticPool+check_same_thread=False`，文件库用 `create_engine(db_url, pool_pre_ping=True)`（**默认 QueuePool，跨 `asyncio.to_thread` checkout 隐患属实**），且**没有任何 connect/checkout 事件设 PRAGMA**。同一文件被以下**各自独立**的 engine 打开：

1. `ConversationRepository`（`repository.py:29`）
2. `FeedbackRepository`（`feedback_repo.py:59`）—— 独立 engine
3. `SkillRepository`（`skills/repository.py:27`）—— 独立 engine
4. `CompositionRepository`（`skills/composition_repo.py:26`）—— 独立 engine
5. `ConfigRepository`（`config_repo.py:58`，另在 `config/loader.py:265,344` 启动前也各建一次）—— 独立 engine

`TrajectoryRepository` 复用 ConversationRepository 的 engine（`trajectory_repository.py:28-29`，**这是归一后的目标样板**）；`init_rag_db(repository.conversation_repository.engine)`（`api/app.py:340`）让 RAG 复用对话 engine。关闭时 `app.py:682-699` 分别 `close()` feedback/skill/composition/config 四个 engine + `repository.close()`，但 **RAG engine 从未显式 dispose、无 try/finally**（B2）。sqlite-vec 加载事件只挂在 RAG 那一次 `init_rag_db`（`rag/common/db.py:67` 的 `checkout`），故其他 5 个 engine 的连接都不加载扩展——PRAGMA/扩展应并入**唯一** engine 工厂（§3.1）。

---

## 1. 目标 schema 设计

设计原则：
- **增量、向后兼容**：新表/新列/新索引均为增量，旧代码读到多出的列不受影响（总规划主题二"影响"段）。降级（revert 代码但保留新库）在 seq/user_id/llm_endpoints/scheduled_tasks 上安全，唯 CHECK/FK/JSON 收紧对"写入非法值的旧代码"会报错——故代码先改写入侧、迁移后置约束（见 §2 顺序与 §7 回滚）。
- **一次重建、约束齐备**：SQLite 不能 `ALTER ADD CONSTRAINT/CHECK`，也不能改列型。凡新增 FK/CHECK/JSON 型/修正列型的表，统一用**批量重建**（`alembic batch_alter_table` 或手写 copy-swap，父表先于子表），每表在其所属迁移中**只重建一次**、直接落到最终 DDL。
- **单一真相**：除 `checkpoints/writes`（LangGraph）与 `simhash_index*`（sqlite-vec shadow）外，全部纳入 `Base`/`RagBase` 统一 metadata 并由 alembic 管理；指纹表 `rag_chunk_fingerprints` 从 raw-SQL 收编为 ORM 声明（迁移内幂等）。

### 1.1 `conversations`（改：+user_id、+CHECK、+索引）

目标 DDL：
```sql
CREATE TABLE conversations (
    id                VARCHAR(36)  NOT NULL,
    user_id           VARCHAR(128) NOT NULL DEFAULT 'default',   -- 【新】主题一 owner 过滤依赖
    name              VARCHAR(200),
    pinned            BOOLEAN      NOT NULL DEFAULT 0,            -- 收紧 NOT NULL(现库 nullable)
    endpoint_id       VARCHAR(36),
    model             VARCHAR(200),
    knowledge_base_id VARCHAR(36),                                -- 跨域 FK：见 §1.10（RAG 收编后可选挂）
    role              VARCHAR(100),
    mode              VARCHAR(20)  NOT NULL DEFAULT 'chat'
                          CHECK (mode IN ('chat','coder')),       -- 【新】CHECK
    workspace         VARCHAR(500),
    thinking_enabled  BOOLEAN      NOT NULL DEFAULT 0,
    thinking_effort   VARCHAR(10)  NOT NULL DEFAULT 'medium'
                          CHECK (thinking_effort IN ('low','medium','high')),  -- 【新】CHECK
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    summary           TEXT,
    PRIMARY KEY (id)
);
CREATE INDEX ix_conversations_user_updated ON conversations(user_id, updated_at DESC);
```
差异对照：现库 `pinned/created_at` 无 NOT NULL（models.py:134 有 Python default）；新增 `user_id`、两条 CHECK、`ix_conversations_user_updated`。`pinned` 从 nullable 收紧为 NOT NULL DEFAULT 0（重建时 `COALESCE(pinned,0)`）。`user_id` 第一版全填 `'default'`（总规划主题一修改点 8）。CHECK 满足性：现库 mode∈{chat,coder}、effort∈{medium} ✅。

### 1.2 `messages`（改：+seq、+role CHECK、unique 索引、排序基准切换）

```sql
CREATE TABLE messages (
    id                VARCHAR(36) NOT NULL,
    conversation_id   VARCHAR(36) NOT NULL,
    seq               INTEGER     NOT NULL,                        -- 【新】回放顺序主键
    role              VARCHAR(20) NOT NULL
                          CHECK (role IN ('user','assistant','system')),  -- 【新】对齐 VALID_ROLES(repository.py:14)
    content           TEXT        NOT NULL,
    reasoning_content TEXT,
    created_at        DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE  -- 已在现库，保留
);
CREATE UNIQUE INDEX ux_messages_conv_seq ON messages(conversation_id, seq);        -- 兼作 FK 支撑 + 覆盖排序
```
差异：新增 `seq` + 唯一索引；`role` 加 CHECK（现库值 ⊂ 允许集 ✅）；旧 `created_at` 单列排序索引被复合唯一索引取代（D6 的 `SCAN+TEMP B-TREE` 消除）。`get_messages`（`repository.py:150-154`）排序键 `Message.created_at` → `Message.conversation_id, Message.seq`。seq 回填见 §2.3-M1。

### 1.3 `feedback`（改：补两条 FK + rating CHECK + 两索引）

```sql
CREATE TABLE feedback (
    id              VARCHAR(36) NOT NULL,
    conversation_id VARCHAR(36) NOT NULL,
    message_index   INTEGER     NOT NULL,
    rating          INTEGER     NOT NULL CHECK (rating BETWEEN 1 AND 5),        -- 【新】对齐 API ge/le(data.py:34)
    comment         TEXT,
    skill_id        VARCHAR(36),
    created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE, -- 【新】
    FOREIGN KEY (skill_id)        REFERENCES skills(id)         ON DELETE SET NULL -- 【新】
);
CREATE INDEX ix_feedback_conversation ON feedback(conversation_id);
CREATE INDEX ix_feedback_skill        ON feedback(skill_id);
```
差异：现库**零 FK 零 CHECK**（D1）；`message_index` 语义为"会话内位置序号"（feedback 行有 52/84 等，**非 messages.id**），故第二 FK 落在 `skill_id→skills`（现库 skill_id 全 NULL，可挂）而非 message。孤儿清理（1 行）在 FK 生效前执行（§2.3-M2）。索引覆盖 D6 反馈两查询列（`feedback_repo.py:138-188` 的 conversation_id/skill_id/created_at 查询）。

### 1.4 `trajectory_events`（改：payload JSON 化 + CHECK、补类型化索引）

```sql
CREATE TABLE trajectory_events (
    id              VARCHAR(36) NOT NULL,
    conversation_id VARCHAR(36) NOT NULL,
    turn_id         VARCHAR(36) NOT NULL,
    seq             INTEGER     NOT NULL,
    event_type      VARCHAR(20) NOT NULL,
    payload         TEXT        NOT NULL CHECK (json_valid(payload)),            -- 【新】JSON 校验(D8)
    created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
-- 保留 ix_trajectory_events_conversation_id / _turn_id
CREATE INDEX ix_trajectory_type_created ON trajectory_events(event_type, created_at);  -- 【新】D6(llm_usage 排序)
```
差异：payload 加 `json_valid` CHECK（现库 0 非法 ✅，`trajectory_repository.py:107` 的 `try/except json.loads` 兜底可退役）；新增 `(event_type,created_at)` 索引，命中 `get_cache_stats` 的 `WHERE event_type='llm_usage' ORDER BY created_at DESC`（`trajectory_repository.py:128-135`）。event_type 是否加 CHECK：**建议不加**（枚举随埋点演进，brittle），改为文档清单 + 埋点常量化。32 行孤儿先删（§2.3-M2）。

### 1.5 `skills` / 1.6 `skill_compositions`（改：JSON 化 + CHECK；skills 修列型漂移）

```sql
CREATE TABLE skills (
    id                 VARCHAR(36)  NOT NULL,
    name               VARCHAR(200) NOT NULL,
    description        TEXT         NOT NULL,
    trigger_conditions TEXT         NOT NULL CHECK (json_valid(trigger_conditions)),  -- JSON 数组
    steps              TEXT         NOT NULL CHECK (json_valid(steps)),
    version            INTEGER      NOT NULL DEFAULT 1,
    success_rate       FLOAT        NOT NULL DEFAULT 0.0,
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 修 TIMESTAMP→DATETIME 漂移(D4)
    PRIMARY KEY (id)
);

CREATE TABLE skill_compositions (
    id               VARCHAR(36)  NOT NULL,
    name             VARCHAR(200) NOT NULL,
    description      TEXT         NOT NULL,
    skill_ids        TEXT         NOT NULL CHECK (json_valid(skill_ids)),        -- JSON 数组
    trigger_patterns TEXT         NOT NULL CHECK (json_valid(trigger_patterns)),
    usage_count      INTEGER      NOT NULL DEFAULT 0,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
```
说明：`skill_ids` 是数组，无法逐元素挂 FK，保持 JSON 数组 + `json_valid`；数组内 ID 的存在性由应用层 `CompositionRepository` 校验（两表现均空，CHECK 可满足）。ORM 侧把这几列声明为 `JSON` 类型（`sqlalchemy.JSON` 在 SQLite 落 TEXT），`json_valid` CHECK 以显式 `CheckConstraint` 声明（见 §3）。`skills` 空表 → 直接重建零风险。

### 1.7 `llm_endpoints`（【新表】从 system_config KV 拆出，D11）

现库把每个端点序列化为 `system_config` 的 `llm_endpoints.<uuid>`（值内嵌 `api_key` 明文、`models[]` 数组、延迟/可达性探针结果）+ 一个 `llm_endpoints.index` 数组指针。目标：实体表，供主题三 `EndpointRegistry` 消费。

```sql
CREATE TABLE llm_endpoints (
    id              VARCHAR(36)  NOT NULL,
    name            VARCHAR(200) NOT NULL,
    provider        VARCHAR(50)  NOT NULL,                 -- 'openai'/'anthropic'/'ollama'
    base_url        VARCHAR(1000),
    models_json     TEXT         NOT NULL DEFAULT '[]'
                        CHECK (json_valid(models_json)),    -- 保留数组：元素含 name/context_window(null|str)/multimodal，形状异构
    active_model    VARCHAR(200),
    api_key         TEXT,                                   -- 见 §1.11 安全说明
    is_default      BOOLEAN      NOT NULL DEFAULT 0,
    position        INTEGER      NOT NULL DEFAULT 0,        -- 取代 llm_endpoints.index 数组顺序
    is_reachable    BOOLEAN,                                -- 可空(实测有 null)
    last_latency_ms INTEGER,
    last_total_ms   INTEGER,
    last_tested_at  DATETIME,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
CREATE INDEX ix_llm_endpoints_default ON llm_endpoints(is_default);
```
字段映射取证（见 §0.1：3 个真实端点样本）：`api_key_set` **不建列**（由 `api_key IS NOT NULL` 派生）；`models` 保留为 `models_json`（元素含 `context_window` 可为 `null` 或字符串 `"128K"`，**不能建整型列**，故不拆子表——单表 + JSON 更贴合对象形状、迁移更简单）。ETL 与 down 重建 KV 见 §2.4-M4。

### 1.8 `scheduled_tasks`（【新表骨架】主题五落点，此处仅建表）

```sql
CREATE TABLE scheduled_tasks (
    id              VARCHAR(36) NOT NULL,
    conversation_id VARCHAR(36),
    description     TEXT        NOT NULL,
    scheduled_at    DATETIME    NOT NULL,
    condition_type  VARCHAR(50),                                    -- 'once'/'file_changed'/'http_status'/...
    condition_args  TEXT        CHECK (condition_args IS NULL OR json_valid(condition_args)),
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','RUNNING','DONE','FAILED','CANCELLED')),
    last_result     TEXT,
    created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);
CREATE INDEX ix_scheduled_tasks_due ON scheduled_tasks(status, scheduled_at);
```
主题二**只负责建表与约束**；`scheduler.py` 的读写接入是主题五修改点 1–2（总规划 §3 主题五）。建索引 `(status,scheduled_at)` 供"启动 recover PENDING 未过期"查询。

### 1.9 FTS5 external-content 全文索引（D6 搜索脱离全表扫描）

现库零触发器（§DDL 实测 triggers 为空），`_search_messages_sync` 用 `LIKE '%…%'` 全表扫（`repository.py:571-582`）。目标 external-content FTS5（内容回指 `messages.content`，不重复存储）：

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='rowid'
);

CREATE TRIGGER messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;
```
要点：
- `messages` 为普通 rowid 表（TEXT 主键仍有隐式 rowid，§0.1 DDL 无 `WITHOUT ROWID`）→ `content_rowid='rowid'` 合法。
- 建表后须一次性回填现有 30 行：`INSERT INTO messages_fts(messages_fts) VALUES('rebuild');`（external-content 的 rebuild 命令）。
- 中文检索：SQLite FTS5 默认 `unicode61` 分词器对 CJK **按字切分不理想**；`SearchEngine.keyword_search`（`search.py:34-53`）主路径改 `MATCH`，**LIKE 保留为降级路径**（当 MATCH 语法异常或短查询时回退），与总规划主题二修改点 6 一致。分词器可选 `tokenize='unicode61'`（起步）或后续引入 trigram（`tokenize="trigram"`，需 SQLite≥3.34，本库 3.51 支持）——本文默认 unicode61 + LIKE 降级，trigram 作为 T2 可选项标注。
- 触发器与虚拟表在迁移内以 `op.execute` 原生 SQL 建（alembic 不托管 virtual table 的 autogenerate），并在 `env.py` 的 include_object 中**排除 `messages_fts*`/`simhash_index*`** 以防误删。

### 1.10 跨域 FK 说明（conversations.knowledge_base_id → knowledge_bases）

D7 主张统一 Base 后声明跨域 FK。实测 0 违规（§0.1）可挂：
```sql
-- 待 RAG 收编进同一 metadata（§2.2）后，conversations 重建时追加：
FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE SET NULL
```
`skills↔feedback`（1.3 已含 skill_id FK）、`scheduled_tasks↔conversations`（1.8 已含）。**本主题内** RAG 表收编为 baseline 的一部分但跨域 FK 挂接排在最后迁移（M4），因其依赖 `RagBase`/`Base` metadata 合并落地（§3.6）。

### 1.11 索引清单汇总（D6）

| 索引 | 表 | 列 | 目的 | 迁移 |
|---|---|---|---|---|
| ux_messages_conv_seq (UNIQUE) | messages | conversation_id, seq | 回放排序 + FK 支撑 + 消 TEMP B-TREE | M3 |
| ix_conversations_user_updated | conversations | user_id, updated_at DESC | owner 列表分页 | M3 |
| ix_feedback_conversation | feedback | conversation_id | 按会话查反馈 + FK 支撑 | M3 |
| ix_feedback_skill | feedback | skill_id | 按技能查反馈 + FK 支撑 | M3 |
| ix_trajectory_type_created | trajectory_events | event_type, created_at | cache_stats 排序 | M3 |
| ix_trajectory_events_conversation_id / _turn_id | trajectory_events | (已存在) | 保留 | — |
| ix_llm_endpoints_default | llm_endpoints | is_default | 默认端点查找 | M4 |
| ix_scheduled_tasks_due | scheduled_tasks | status, scheduled_at | recover 未过期任务 | M4 |
| idx_chunk_fingerprint_hash / _kb / _doc | rag_chunk_fingerprints | (已存在) | 去重查找 | 保留 |
| messages_fts (virtual) | messages | content | 全文检索 | M5 |

### 1.12 system_config 清理后保留键清单（D11）

**删除**：`llm_endpoints.index` 与全部 `llm_endpoints.<uuid>`（迁至 §1.7 表，M4）；裸 `provider`/`model`/`base_url`（category=llm 的遗留旧键，`load_from_database` 不读、与 `llm.*` 异值即失效，§0.1 取证，M4）。
**保留**（继续作 KV，热配字段）：`llm.provider`、`llm.model`、`llm.base_url`、`llm.streaming_enabled`（+ 未来 `llm.request_timeout`、`auth.required_roles`、`rate_limit.*`、`tools.web_search.api_key`〔显式允许入库的例外，`config_repo.py:31-35`〕、`channels.wechat.*`、`memory.database_url`）。
**待决**：`level`（logging）——B8 指 `config.logging` 段从未被读取；是否删除归主题三配置真源改造，本主题 M4 **保留不动**，仅在保留清单标注"待主题三裁决"。

> 注意：`api_key` 明文入库是 S6 的实例。端点 `api_key` 保留列但**导出/日志必须脱敏**（`x_secret` marker 由主题三供数，过渡期手写清单）。存储设计层面不引入字段级加密（个人单机定位，总规划主题二修改点 14），仅确保 `export` 路径脱敏，与主题一修改点 6 合流。

## 2. Alembic 落地方案

### 2.1 与现有 engine 工厂的对接（不新增第二套配置）

现状无任何迁移工具（`git ls-files | grep alembic` 为空，`pyproject.toml` 未声明 alembic）。落地：

1. 【新增依赖】`pyproject.toml`：`alembic>=1.13`（运行时依赖，非 dev——启动脚本要执行 `upgrade head`）。
2. 【新增目录】`src/thumbelina/migrations/`（随包发布，容器内可 `import`）：`env.py`、`script.py.mako`、`versions/`。**不放在仓库根**，避免 wheel 缺失（Dockerfile 只 `COPY src/`）。
3. `alembic.ini`：`script_location = src/thumbelina/migrations`；`sqlalchemy.url` **留空**，运行时由 `env.py` 从注入的 engine 取。
4. `env.py` 关键点：
   - `import thumbelina.repository.models` 与 `thumbelina.rag.common.orm_models`，`target_metadata` = 合并后的统一 metadata（§3.6，收编 `rag_chunk_fingerprints`）。
   - **单 URL 解析**：`env.py::run_migrations_offline/online` 的 db_url 读环境变量 `THUMBELINA_REPOSITORY__DATABASE_URL`，与 app 同源，杜绝"迁移库≠运行库"。
   - `render_as_batch=True` + `batch_alter_table` 的 `recreate='always'`——SQLite 加/改 FK、CHECK、列型的**唯一正道**（自动 copy-swap 并保索引/触发器）。
   - `include_object` **排除** `checkpoints`、`writes`（LangGraph 拥有）、`simhash_index` 及其 shadow 表、`messages_fts`（FTS5 由专用迁移语句管理），防止 autogenerate 误 DROP。
   - 每个 online migration 前执行 `PRAGMA foreign_keys=OFF`（**须在事务外**，SQLite 事务内改该 pragma 无效），down/migration 完成后 `PRAGMA foreign_key_check`（§2.5）。

### 2.2 baseline 生成策略：手写为主、autogenerate 为辅（取舍）

**决策：baseline 用"autogenerate 草案 + 人工裁剪"，而非直接落库。** 理由（均实证）：

- 现库 schema 本身就是 `create_all` + `ensure_schema`（`models.py:22-101`）+ RAG 手写重建（`rag/common/db.py:97-211`）三者叠加的**漂移结果**：`skills.created_at` 是 `TIMESTAMP` 而 ORM 写 `DateTime`；`conversations` 列序与 ORM 定义完全不同（§DDL 实测）；`messages.reasoning_content` 追加在 `created_at` 之后。**直接拿 autogenerate 当 baseline 会把漂移固化为"正确基线"**。
- baseline 的目标是"如实描述**现网已有**的库"，让 M1–M5 成为对现网的**真实 diff**。因此 baseline 内容 = 现库 DDL 的镜像（含 rag_documents 的列序、TIMESTAMP 等"丑"），而非目标 schema。

操作步骤（写入 T2-03 验收）：
1. 用 §2.4 快照流程拿到现库**只读副本** `migrate_drill.db`。
2. `alembic revision`（手写 M0）：在 upgrade 内以 `op.execute` 原样执行 §0.1 实测的 `sqlite_master` DDL（9+2 表 + 指纹表 + 其索引），`simhash_index`/`messages_fts` 不在 baseline（virtual table 在专属迁移建）。
3. `alembic stamp head`（对**新初始化**的测试库用 `upgrade head`；对**现网库**用 `stamp M0` 认领基线，不重复建表）。
4. 生成目标态：`alembic revision --autogenerate -m "M1 columns"`，人工核对 diff（autogenerate 对 SQLite 的列/表删除判断不稳，**必须手改**）。

> 收编决策：`rag_chunk_fingerprints` 从 `db.py:214` 的 raw-SQL 提升为 `orm_models.py` 中的 `Mapped` 模型（形状照 §0.1 DDL），使其进入 metadata；`simhash_index`（vec0）**永不纳入 autogenerate**，在 M0 用 `op.execute` + `IF NOT EXISTS` 方言分支幂等创建，`_load_sqlite_vec` checkout 事件迁至统一 engine 工厂（§3.1）。

### 2.3 迁移编号与内容总览（M0–M5，每个可独立 PR、可 up/down）

| 迁移 | 主题 | up 内容 | down 内容 | 破坏性/可逆性 |
|---|---|---|---|---|
| **M0_baseline** | 收编现状 | 建 9+2 表（现库镜像 DDL）+ 指纹表 + `simhash_index` 方言分支（幂等）；对现网 `stamp` | 全 DROP（仅测试库用） | 中性（现网 stamp 不动数据） |
| **M1_additive** | 加列 + 数据规范化 | `messages.seq`（可空→回填→唯一索引见 M3）；`conversations.user_id` DEFAULT 'default'；**naive→UTC 规范化**（§2.7） | DROP `seq`、`user_id`；时间规范化**不回滚**（幂等安全） | 可逆（列增量，旧代码忽略） |
| **M2_cleanup** | 孤儿清理 + 僵尸表 | 记录清单日志→删 32 条 trajectory 孤儿 + 1 条 feedback 孤儿；`DROP TABLE user_profiles,user_preferences`（连带其 `ix_*` 索引） | 重建两张空僵尸表；**被删孤儿行不可恢复** | **不可逆**（靠 §2.4 快照） |
| **M3_constraints** | FK/CHECK/索引收紧 | `batch_alter_table` 重建 conversations/messages/feedback/trajectory/skills/compositions → 落地 §1 全部 FK/CHECK/NOT NULL 收紧 + `ux_messages_conv_seq` 等索引（§1.11）。**父表(conversations,skills)先于子表(feedback)** | batch 重建回 M1 态（去 CHECK/FK/索引）；seq 回填值保留 | 收紧不可被"写非法值的旧代码"回退 → 代码先行（§7） |
| **M4_endpoints** | KV 拆分 + RAG 收编 FK | 建 `llm_endpoints`；ETL：解析 3 个 `llm_endpoints.<uuid>` JSON → 行，`position` 取自 `llm_endpoints.index`；DELETE 已迁移 KV + 裸 `provider/model/base_url`；建 `scheduled_tasks` 骨架；`conversations.knowledge_base_id` 跨域 FK 挂接（重建 conversations，§1.10） | 从 `llm_endpoints` 行反序列化回 `system_config` KV（可逆）；DROP 两新表 | ETL 可逆（down 重建 KV） |
| **M5_fts** | 全文检索 | `op.execute` 建 `messages_fts` FTS5 external-content + 3 触发器 + `('rebuild')` 回填 30 行 | DROP 触发器 + `messages_fts` | 可逆 |

执行顺序按依赖不可乱：M1 加 seq 后 M3 建唯一索引（回填须先于唯一约束）；M2 清孤儿须**先于**任何 FK 收紧（M3）；M4 的跨域 FK 依赖 §3.6 metadata 合并已在代码层就位。

### 2.4 上线前快照与副本演练（总规划 §5.3 强制）

命名规约（写入 §7 回滚）：
```
snapshot-<UTC:YYYYMMDDTHHMMSS>Z--pre-M<N>
  ├── thumbelina.snapshot.db        # SQLite Backup API 一致快照(停写后)
  ├── thumbelina.snapshot.db.hash   # sha256
  └── manifest.json                 # {VERSION, alembic_revision, files:{name:{sha256,size}}, ts, git_sha}
```
- 快照**必须**用 `sqlite3` Backup API（`src.backup(dst)`）而非 `cp`——现库 `journal_mode=wal`（§0.1 实测），直接拷 `.db` 不含未合并 WAL 帧会损坏。
- 演练：把快照副本 + 当前 `alembic_version` 交给 `alembic upgrade head`，全绿后再 `downgrade base`→`upgrade head` 双向验证，最后 `PRAGMA integrity_check` + `foreign_key_check`。

### 2.5 `PRAGMA foreign_key_check` 作为迁移门

每个**收紧类**迁移（M3、M4）在事务提交前执行：
```python
violations = list(conn.execute(text("PRAGMA foreign_key_check")))
if violations:
    raise MigrationError(f"FK violations before commit: {violations}")
```
`batch_alter_table` 在 copy-swap 时会临时 `PRAGMA foreign_keys=OFF`，故 swap 完成、恢复 pragma 之前是唯一的"裸窗口"——`foreign_key_check` 正好卡在此处兜底。测试断言清单见 §4.3。

### 2.6 应用启动校验 revision（不符拒起，fail-fast）

总规划主题二修改点 1：**`upgrade head` 由启动脚本/Docker CMD 显式执行，app 启动仅校验、不符拒起**。落地：
- `create_db_engine` 保持"只连接不建表"（§3.1）；`init_db` 从"create_all+ensure_schema"改为"**校验** alembic revision == `head`"：读 `alembic_version` 表，比对 `script.get_current_heads()` vs `get_heads()`，不等则 `raise SystemExit`（附"请运行 `alembic upgrade head`"提示）。**不再 create_all**。
- Docker：新增 `docker/entrypoint.sh`（或 compose `command:` 覆盖）先 `alembic -c <pkg>/alembic.ini upgrade head` 再起 uvicorn（`Dockerfile:69` CMD 保留 uvicorn，改由 entrypoint 包裹）。compose 现无 `command:`（§compose 实测）→ 加一行即可。
- 双环境版本断言：启动时 `check_sqlite_version()` 要求 `>=3.35`（否则 FTS5/`json_valid`/trigram 前提不成立），容器 bookworm≈3.40.1 ✅、.venv 3.51.1 ✅，但 CI 用矩阵跑 `python:3.11-slim` 与本机 3.13 两端（T2-31）。

### 2.7 naive→UTC 规范化迁移细节（D9）

现库时间列存 `CURRENT_TIMESTAMP` 的 19 位 naive UTC 字符串（§0.1 实测 len=19、无 `+`），而写入侧 `feedback_repo.py:44` 用 `datetime.now()`（本地 naive）→ 同库混两种时区。规范化：
- 数据规范化（M1）：对 messages/conversations/feedback/trajectory 等所有 `created_at/updated_at`，把 `YYYY-MM-DD HH:MM:SS` 规整为带微秒的 ISO 或统一保持空格分隔但**语义声明为 UTC**。采用**保守方案**：不改字符串格式（避免大范围 UPDATE 抖动），仅统一"库内时间一律视为 UTC"这一约定 + 写入侧改 aware（§3.3）。feedback 那 3 行若曾为本地时间，误差恒定为本机偏移——个人单机可接受，日志记录不逐一纠偏（避免二次错）。
- 真正改动在写入侧：所有 `datetime.now()`→`datetime.now(timezone.utc)`；`server_default=func.now()` 保持（SQLite `CURRENT_TIMESTAMP` 本即 UTC）。防重跑：M1 的时间步用 alembic 事务天然幂等（stamp 过的库不再执行）。

## 3. 代码层设计

### 3.1 统一 `create_db_engine` / `SessionLocal` 工厂（D3 归一 + PRAGMA + sqlite-vec）

单一工厂承载所有连接期设置，取代当前"文件库默认 QueuePool、无 PRAGMA、sqlite-vec 只在 RAG 一处 checkout"的分裂态（§0.2）。

```python
# repository/db.py  —— 唯一 engine 工厂
def create_db_engine(
    db_url: str,
    *,
    sqlite_vec: bool = True,          # RAG 需要 vec0；纯对话栈可关
    busy_timeout_ms: int = 5000,
) -> Engine:
    if _is_memory(db_url):
        engine = create_engine("sqlite:///:memory:",
                               connect_args={"check_same_thread": False},
                               poolclass=StaticPool, future=True)
    else:
        # 文件库：单写者场景用 QueuePool + WAL；busy_timeout 抑制 to_thread 并发 checkout 撞锁
        engine = create_engine(db_url, pool_pre_ping=True, future=True)

    @event.listens_for(engine, "connect")          # 每个新 DBAPI 连接：PRAGMA(必须 connect；foreign_keys 是连接级)
    def _set_pragma(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")       # D1 根治：全库生效
        cur.execute("PRAGMA journal_mode=WAL")      # 与现状一致 + 读写并发
        cur.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cur.execute("PRAGMA synchronous=NORMAL")    # WAL 推荐
        cur.close()

    if sqlite_vec:
        @event.listens_for(engine, "checkout")      # 复用池中连接也要加载扩展(沿用 rag/common/db.py:67 的洞见)
        def _load_vec(dbapi_conn, _rec, _proxy):
            _try_load_sqlite_vec(dbapi_conn)        # 从 rag/common/db.py 迁入
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
```
- `_try_load_sqlite_vec` 从 `rag/common/db.py:23-47` 整体搬入 `db.py`，RAG 侧 `init_rag_db` 不再自挂 checkout（改由 engine 工厂保证）。
- **`foreign_keys=ON` 用 `connect` 而非 `checkout`**：该 pragma 是连接属性，新连接必须设；与 sqlite-vec（要覆盖复用连接故用 `checkout`）分工不同——这是 `rag/common/db.py:65-67` 注释经验的正确延用。
- `init_db` 职责收缩为 §2.6 的"revision 校验 + `check_sqlite_version>=3.35`"，不再 `create_all`/`ensure_schema`。

### 3.2 各仓储构造函数 before / after（删 4 套自建 engine）

统一改为"注入共享 engine/SessionLocal"，样板即现成的 `TrajectoryRepository.__init__`（`trajectory_repository.py:27-29`，接收上游 repository 复用 engine）。主题三 container 落地前，先用 app.py 把 `ConversationRepository.engine` 作单点分发。

| 仓储 | before（自建 engine 行号） | after |
|---|---|---|
| `ConversationRepository` | `repository.py:26-30` 自建 | `__init__(self, engine: Engine, session_factory)`；由 `RepositoryManager` 用 `create_db_engine` 建一次并持有 |
| `TrajectoryRepository` | `trajectory_repository.py:27-29`（**已是目标样板**） | 不变 |
| `FeedbackRepository` | `feedback_repo.py:56-60` 自建 | `__init__(self, engine, session_factory)`；删除自建；`close()` 不再 dispose（engine 非其所有） |
| `SkillRepository` | `skills/repository.py:24-28` 自建 | 同上，注入 |
| `CompositionRepository` | `skills/composition_repo.py:23-27` 自建 | 同上，注入 |
| `ConfigRepository` | `config_repo.py:55-59` 自建；且 `loader.py:265,344` 启动前另建 | `__init__(self, engine, session_factory)`；`loader.py` 两处改：启动前用一次性 engine（用完 dispose），运行期用注入 engine |

`RepositoryManager`（`manager.py:27-39`）成为"engine 持有者 + 分发者"：
```python
class RepositoryManager:
    def __init__(self, db_url, *, vector_store=None, sqlite_vec=True):
        self.engine = create_db_engine(db_url, sqlite_vec=sqlite_vec)
        self.session_factory = make_session_factory(self.engine)
        self.conversation_repository = ConversationRepository(self.engine, self.session_factory)
        self.trajectory_repository = TrajectoryRepository(self.conversation_repository)
        self._search_engine = SearchEngine(self.conversation_repository, vector_store)
        self._owned_engines = [self.engine]
    def make_feedback_repo(self): return FeedbackRepository(self.engine, self.session_factory)  # 供 app/deps 取
    def make_skill_repo(self):    return SkillRepository(self.engine, self.session_factory)
    def make_composition_repo(self): return CompositionRepository(self.engine, self.session_factory)
    def close(self):
        for e in self._owned_engines: e.dispose()   # 统一 dispose，覆盖此前"RAG engine 从不 dispose"
```
`api/app.py:221/256/280/297/298/511` 的六处独立构造改为向 `repository.make_*()` 索取；`app.py:682-699` 的多段 `close()` 收敛为一次 `repository.close()`（配合主题三 `AsyncExitStack`）。**注意**：LangGraph checkpointer 走独立 aiosqlite 连接（`app.py:228-232`），不并入本同步 engine，其 `checkpoints/writes` 表由 alembic 排除（§2.1）。

### 3.3 `asyncio.to_thread` 归一 + 写入侧 UTC（D9 / 样板漂移）

现状每个仓储方法手写"`_xxx_sync` + `async def xxx: return await asyncio.to_thread(self._xxx_sync,...)`"（`repository.py` 全类、`feedback_repo.py`、`skills/*.py`），三份风格漂移。**归一方式**：一个薄装饰器，不引入 async SQLAlchemy（保持 to_thread 模型，最小改动）：

```python
# repository/_async.py
def to_repo_thread(fn):
    @functools.wraps(fn)
    async def wrapper(self, *a, **k):
        return await asyncio.to_thread(fn, self, *a, **k)
    return wrapper
```
同步实现保留为私有 `def _save_sync`（供事务内直接同步调用），公共 `async def save` 用 `@to_repo_thread` 标注。收益：消除 `skills/repository.py:47-73`（内嵌闭包式）与 `feedback_repo.py:78-115`（命名 `_sync` 式）两套写法差异。**100KB 校验下沉**：`MAX_CONTENT_LENGTH`（`manager.py:13,99`）移入 `ConversationRepository.add_message` 统一，避免只有 `RepositoryManager` 一处守（D8）。

写入侧时间：全量 `datetime.now()`→`datetime.now(timezone.utc)`；模型层加 `default=lambda: datetime.now(timezone.utc)` 覆盖 Python 侧写入（`Feedback.created_at` 现用 `field(default_factory=datetime.now)`，`feedback_repo.py:44`）。与 §2.7 迁移语义一致（库内视为 UTC）。

### 3.4 `repository/lifecycle.py::DataLifecycleService`（D10 清理不彻底，编排删除）

新增单一编排点，替代散落在 `routes/data.py:86-122` 的"只删 conversations + memory"逻辑，补齐 trajectory/feedback/checkpoint/向量/skills/system_config（D10）。接口与事务边界：

```python
class DataLifecycleService:
    def __init__(self, *, engine, session_factory, repository: RepositoryManager,
                 memory_service=None, vector_store=None, checkpointer=None,
                 feedback_repo=None):
        ...
    # —— 会话级删除：FK 生效后库级联兜底，服务层显式清理库外资产 ——
    async def purge_conversation(self, conversation_id: str) -> PurgeReport:
        async with per_conversation_lock(conversation_id):        # 与 data.py:109 现有锁一致
            with self._session_factory() as s, s.begin():         # 单事务：DB 侧删除
                s.execute(delete(Conversation).where(id==cid))     # 级联删 messages/trajectory(FK CASCADE)
                s.execute(delete(Feedback).where(conversation_id==cid))  # feedback 无 relationship,显式删
            await self._clear_checkpoint(cid)                      # LangGraph 线程(库内表,独立栈)
            await self._drop_vector_docs(cid)                      # chroma 集合(库外!)
        return report

    async def purge_all(self) -> PurgeReport:
        # 顺序:逐个 purge_conversation → skills/compositions → system_config 业务键 → chroma 全清 → MEMORY/ 目录清
        # 每类资产独立事务+try/except,产出 PurgeReport{deleted:{表:count}, errors:[...]}
        ...
```
边界原则：**同一 DB 内的多表删除放一个 `session.begin()` 事务**（FK 级联此时已生效，§2.1）；**库外资产（chroma 向量、MEMORY/ 文件、LangGraph checkpoint 表）在 DB 事务提交后各自 best-effort 清理并在 `PurgeReport` 记录**（跨存储无分布式事务，与总规划"SQLite+WAL 与文件域无统一快照点"一致，D5）。`/data/all`（S5）路由改为调用 `purge_all`，删除确认串（主题一 S5）与角色校验（`require_roles`）叠加。

### 3.5 `backup/manager.py` 重写（由死代码转为真实现，D5）

现 `backup/manager.py` 全模块 `src` 零引用（死代码），且 `create_backup`（`manager.py:48-83`）用 `open().write` 非原子、只备份传入 JSON、不含 skills/feedback/system_config/RAG/向量/chroma/MEMORY。重写为 `/data/export` 与恢复脚本的真实后端：

```python
@dataclass
class BackupManifest:
    version: str            # VERSION / importlib.metadata
    alembic_revision: str   # 备份时的 head revision —— 恢复前校验兼容
    created_at: str         # ISO UTC
    git_sha: str | None
    files: dict[str, FileEntry]     # name -> {sha256, size, kind: 'sqlite'|'tar'|'file'}
    row_counts: dict[str, int]      # 每表行数,供 §4 恢复后一致性断言

class BackupService:
    def __init__(self, *, engine, data_dir: Path, backup_dir: Path,
                 memory_dir: Path, todo_dir: Path, chroma_dir: Path): ...

    async def create_snapshot(self, name: str) -> BackupManifest:
        # 1) SQLite 一致快照：sqlite3 Backup API → 单文件(强制 checkpoint WAL)
        # 2) 文件域：MEMORY/ + TODO/ + data/chroma/ → tar(原子: .tmp + os.replace, 复用 filestore.write_text_atomic 范式)
        # 3) 逐文件 sha256 + 行数统计 → manifest.json(原子写)
        ...
    async def restore(self, manifest: BackupManifest) -> RestoreReport:
        # a) 校验 alembic_revision == 当前 head(不符拒恢复或提示先 downgrade)
        # b) 逐文件 sha256 比对 → 原子落盘到 staging → os.replace
        # c) 恢复后 PRAGMA integrity_check + foreign_key_check + 行数==manifest.row_counts
        ...
```
manifest 结构、sha256、原子写（复用 `filestore/atomic.py` 的 tmp+fsync+`os.replace` 范式）与"恢复校验行数和 manifest 一致"是硬要求（§4.4 回归）。`FileLocks` 不跨进程（§0 filestore 注释）→ 备份/恢复期"单写者"约束写进文档与 compose（总规划主题二修改点 14）。

### 3.6 `ensure_schema` 降级为只读漂移告警（D4）

`models.py:22-101` 的 `ensure_schema`（自研 ADD COLUMN）**停止执行任何 ALTER**，改造为纯只读比对：模型 metadata vs 库实际，检出差异则 `logger.warning("schema drift: ... 请运行 alembic upgrade head")`，不改库。调用点从 `init_db`（`db.py:35`）移除。RAG 的 `_migrate_sha256_simhash_to_blob`（`rag/common/db.py:97-211`）整段删除——列型重建逻辑迁入 M0/M4 的 alembic 迁移。

metadata 统一（D7）：保留两个 `DeclarativeBase`（`Base` / `RagBase`），但让二者 `metadata` 通过 `RagBase.metadata.tables.update(Base.metadata.tables)` 式合并**仅在 alembic env 层**呈现单一真相；跨域 FK（§1.10）在迁移内以原生 SQL 声明（SQLAlchemy 跨 Base 的 `ForeignKey("knowledge_bases.id")` 字符串解析在 batch 重建时可用，因两表同库同名解析）。指纹表收编见 §2.2。

### 3.7 变更文件清单（代码层）

新增：`src/thumbelina/migrations/`（env/versions）、`repository/_async.py`、`repository/lifecycle.py`、`docker/entrypoint.sh`。
修改：`repository/db.py`、`repository/models.py`（去 ensure_schema 行为、加 seq/user_id/CHECK/JSON 声明）、`repository/repository.py`、`repository/manager.py`、`repository/feedback_repo.py`、`repository/trajectory_repository.py`、`skills/repository.py`、`skills/composition_repo.py`、`config/config_repo.py`、`config/loader.py`、`rag/common/db.py`（删自建迁移/事件、删 checkout 挂点）、`rag/common/orm_models.py`（收编指纹表）、`api/app.py`（构造/close/启动校验）、`api/routes/data.py`（接 lifecycle）、`backup/manager.py`（重写）、`pyproject.toml`（+alembic）、`Dockerfile`/`docker-compose.yml`（upgrade 挂点）。
删除（卫生，总规划主题二修改点 13）：`test_rag.db`、`thumbelina.db.bak` 脱离跟踪；核查 `.gitignore` 覆盖 `*.db-wal`/`*.db-shm`/`*.tar`（3.2GB tar，§5.7）。

## 4. 测试与迁移演练

### 4.1 测试面冲击评估（取证）

- 真实建库的测试：`tests/test_repository/test_repository.py:10-13` 用 `ConversationRepository("sqlite:///:memory:")` 直接构造；`test_manager.py`/`test_feedback.py`/`test_skills/test_repository.py`/`test_trajectory/test_repository.py`/`test_backup/test_backup.py` 同构。**构造函数签名一改（engine 注入，§3.2），这批 fixture 全爆**——这是本主题最大测试改造面（与总规划"影响·代码面：fixture 需共享 engine + 迁移执行路径"一致）。
- `tests/test_api/conftest.py:157-175` 的 `client` fixture **全 mock**（`RepositoryManager` 被 `patch` 替换），不触真实库 → 受构造函数改动影响小，主要随主题一改鉴权。
- `tests/test_rag/conftest.py` mock torch 等重依赖；RAG 表收编进 metadata 后其建表路径需覆盖。

### 4.2 conftest fixture 改造模式

新增共享 fixture 工厂（放 `tests/conftest.py`，目前仓库根无该文件）：

```python
import pytest
from alembic import command
from alembic.config import Config
from thumbelina.repository.db import create_db_engine, make_session_factory

def _upgrade_head(engine):
    cfg = Config("alembic.ini")            # 或用 importlib.resources 定位包内 ini
    cfg.attributes["configure_logger"] = False
    engine.echo = False
    from alembic.migration import MigrationContext   # 关键：把 alembic 绑到既有 engine 连接
    # env.py 支持传入 connection → 对 :memory: StaticPool 单连接执行 upgrade
    command.upgrade(cfg, "head")

@pytest.fixture
def engine():
    eng = create_db_engine("sqlite:///:memory:")     # StaticPool：所有 session 复用同一连接
    _upgrade_head(eng)                                # ★ 用真实迁移建表，不再 create_all
    yield eng
    eng.dispose()

@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)

@pytest.fixture
def repo(engine, session_factory):
    return ConversationRepository(engine, session_factory)   # 新签名
```
要点：
- **测试库必须经 `alembic upgrade head` 建立**，与生产同一条 DDL 路径——否则测不到 FK/CHECK/FTS 触发器（内存库 `create_all` 会绕过迁移，是回归盲区）。`env.py` 须支持"外部传入 connection"模式（`context.configure(connection=...)`）以适配 StaticPool 单连接内存库。
- 跨 `asyncio.to_thread` 访问内存库依赖 `StaticPool+check_same_thread=False`（§3.1 保留现内存分支设置）→ 级联/FK 断言才可信。
- 提供 `seeded_repo` fixture（建 1 会话 + 2 消息 + 1 trajectory + 1 feedback）供删除/排序断言复用。

### 4.3 回归断言清单（可执行、进 CI）

| # | 断言 | 命令/形式 | 关联 |
|---|---|---|---|
| R1 | 级联删除生效 | 删 conversation → `SELECT COUNT(*) FROM messages/trajectory_events/feedback WHERE conversation_id=?` 均为 0 | D1/FK |
| R2 | seq 排序确定 | 同一秒 `add_message` ×2 → `seq` 严格递增；`get_messages` 返回顺序 == `ORDER BY seq` 而非 created_at | D2 |
| R3 | EXPLAIN 无 SCAN/TEMP | 对 §1.11 主干查询跑 `EXPLAIN QUERY PLAN`，断言计划串含 `USING INDEX`/`USING COVERING INDEX` 且**不含** `SCAN` 与 `TEMP B-TREE` | D6 |
| R4 | FTS MATCH 命中 | `INSERT` 消息 → `messages_fts MATCH 'kw'` 命中；`DELETE` 后经触发器移除（external-content 同步） | 主题二·修改点6 |
| R5 | FK 强制 | 插非法 conversation_id 消息 → 抛 `IntegrityError`；迁移后 `PRAGMA foreign_key_check` 返回空 | D1 |
| R6 | CHECK 强制 | 非法 `role`/`rating∉[1,5]`/`mode∉{chat,coder}`/非 JSON `payload` 写入 → 抛 `IntegrityError` | D8/D9 |
| R7 | 唯一约束 | 同 `(conversation_id,seq)` 二次插 → `IntegrityError` | D2 |
| R8 | 备份→恢复→行数一致 | `create_snapshot` 记 `row_counts` → 造脏数据 → `restore` → 每表 `COUNT(*)`==manifest，且 `integrity_check='ok'` | D5 |
| R9 | llm_endpoints ETL | M4 后 `llm_endpoints` 行数==迁移前 `llm_endpoints.index` 长度(=3)，`api_key`/`models_json` 逐字段等值；`system_config` 无 `llm_endpoints.*` 与裸 `provider/model/base_url` | D11 |
| R10 | 孤儿清零 | 迁移前 `SELECT COUNT(*)` 孤儿（trajectory 32/feedback 1）→ M2 后为 0 | D1 |
| R11 | revision 拒起 | 把库 `stamp` 到旧 revision 后 `create_app` 启动 → 抛 `SystemExit`（§2.6） | D4 |

### 4.4 迁移演练脚本（db 副本，上线前必跑）

`scripts/drill_migration.py`（新增，只读运行库→写副本）：
1. `sqlite3` Backup API 从 `thumbelina.db`（`mode=ro`）导出 `migrate_drill.db`（含 WAL 合并）。
2. 记录 baseline 指纹：每表 `COUNT(*)` + `PRAGMA table_info` + `alembic stamp head`（把副本认作现网基线）。
3. `alembic upgrade head` 逐步（`-v`）跑 M1→M5，每步后 `PRAGMA integrity_check`、M3/M4 后 `PRAGMA foreign_key_check`。
4. 断言 R2/R9/R10 数据面结果；`alembic downgrade base` 再 `upgrade head` 验证双向。
5. 产出 `drill-report.json`（各步耗时、行数变化、异常）——作为 §2.4 快照同级留档。

CI 增加 job：对**两个 Python**（3.11-slim 容器解释器、本机 3.13）各跑一次 `upgrade head` + R1–R11（覆盖 SQLite 版本差异，§2.6/T2-31）。

### 4.5 现有测试的迁移期兼容策略

构造函数改造与 fixture 改造须**同 PR**（否则 CI 全红）。过渡顺序：
- PR-A（骨架）：`create_db_engine` 加 PRAGMA/vec、新增 `make_session_factory`、`env.py`/baseline 落地、`RepositoryManager` 提供 `make_*()` 工厂但**旧构造签名暂兼容**（保留 `db_url:` 可选参数，内部转发到注入路径）→ 现有测试不改仍绿。
- PR-B（切签名 + 改 fixture）：一次性把 6 个仓储构造函数换成注入式 + 全量改 fixture 走 `_upgrade_head`。此 PR 触及测试面最大，单独成 PR 便于 review/revert。
- PR-C+：各迁移 M1–M5、lifecycle、backup 重写、FTS。

## 5. 与总规划的偏差

本章列**细化过程中基于源码/实查证据对总规划主题二的修正、补充与更优解**。均为"更精确的执行口径"，不推翻总规划方向；标注【修正】/【补充】/【更优】/【澄清】。

| # | 类型 | 总规划原文（主题二） | 本文口径 | 依据 |
|---|---|---|---|---|
| Δ1 | 【补充·关键】 | 修改点 1"收编 9+2 表" | **`checkpoints`/`writes`（LangGraph SqliteSaver 私有，`app.py:228-232`）与 `simhash_index*`（sqlite-vec shadow）必须排除在 alembic 管理之外**（`include_object`），否则 autogenerate 会试图托管/误删第三方表 | §0.1 实测表清单；这两类表非本应用 DDL 所建 |
| Δ2 | 【修正】 | 修改点 4"feedback 两列补 FK" | 第二 FK 列**不是** message（`message_index` 是会话内**位置序号** INTEGER，实测值 52/84，非 `messages.id`）；两条 FK = `conversation_id→conversations` + `skill_id→skills` | §1.3；§0.1 feedback 行 |
| Δ3 | 【更优】 | 修改点 1"从现库 `sqlite_master` DDL 生成 baseline" | baseline **手写成"现网漂移态的镜像"**（含 `skills.created_at=TIMESTAMP`、`rag_documents` 列序漂移），**不用**对目标 schema 的 autogenerate——否则把 D4 实证的漂移固化成基线，M1–M5 便不再是真实 diff | §2.2；§0.1 DDL |
| Δ4 | 【澄清·缩范围】 | 修改点 7"迁移将存量 naive 行按'视为 UTC'规范化" | 实测时间串已是 19 位 UTC（`CURRENT_TIMESTAMP`），**不做全库 UPDATE 改写**（无意义抖动 + 二次错风险）；仅①写入侧改 aware ②文档声明"库内即 UTC"③feedback 少量本地时间行留痕不纠 | §2.7；§0.1（len=19、无 `+`） |
| Δ5 | 【更优】 | D7"两套 DeclarativeBase→跨域 FK 不可声明" | **保留两个 Base**（`Base`/`RagBase`），仅在 alembic env 层合并 metadata + 跨域 FK 用迁移内原生 SQL 挂；**不**物理合并 Base 类（会波及全部 `RagBase` 建模与 RAG 迁移，风险 >> 收益） | §3.6；§1.10 |
| Δ6 | 【补充】 | 修改点 11"清理 provider 与 llm.provider 并存" | 除删端点 KV 外，实测**异值死键** `model`="mimo-v2.5" ≠ `llm.model`="deepseek-v4-flash"、`base_url` 亦异值；`load_from_database`（`runtime_manager.py:302-308`）只读 `llm.*` → 裸 `provider/model/base_url` 为无消费方的遗留键，M4 一并删 | §0.1 取证；§1.12 |
| Δ7 | 【补充·安全】 | S6/修改点 11 只提"端点拆表" | 现库端点 `api_key` **明文入库**且绕过了 `_is_sensitive`（`config_repo.py:42` 按 key 末段判断，`llm_endpoints.<uuid>` 末段是 uuid 而非 `api_key` → 整个含密钥 JSON 落库）。`llm_endpoints.api_key` 列继承此事实，**导出/日志脱敏为硬要求**（与主题一修改点 6、主题三 `x_secret` 合流）；本文不加字段级加密 | §0.1 端点 JSON；§1.11 注 |
| Δ8 | 【补充】 | 修改点 6 FTS5"关键词路径改 MATCH" | 默认 `unicode61` 分词对 **CJK 效果差**；主路径 MATCH、**LIKE 保留为降级**（`search.py:34`），trigram 分词（需 SQLite≥3.34，本库支持）列为可选增强而非默认，避免中文召回回退 | §1.9 |
| Δ9 | 【补充·版本】 | 修改点 6"需实证 .venv 与容器 Python 自带 SQLite ≥3.35" | 实测 `.venv=3.51.1` ✅；**容器基座 `python:3.11-slim`（Debian bookworm ≈3.40.1）**，且仓库 `pyproject` 运行时 `requires-python>=3.11` 而 `mypy` 目标 3.13（版本漂移 B8 的一部分）→ 必须 CI 双解释器矩阵跑迁移 + 启动 `check_sqlite_version>=3.35` 断言 | §2.6；§4.4 |
| Δ10 | 【设计选择】 | 修改点 11 端点表未规定 models 形状 | `models` **保留为 `models_json` 单列 JSON 数组**（元素 `context_window` 实测可为 `null` 或字符串 `"128K"`，异构），**不拆 `llm_endpoint_models` 子表**（对象天然按端点整体读写，拆表增复杂度无查询收益） | §1.7；§0.1 端点样本 |

**总规划中经复核确认无误、本文照办的结论**：D1 FK 未生效且已产孤儿（实测 32+1 与总规划完全一致）、D2 无 seq 秒级排序隐患、D3 约 5 套 engine、D4 双套土法迁移 + 僵尸表、D5 备份死代码 + 非原子 + 域不全、D6 主干查询 SCAN/LIKE 全表、D8 JSON 裸 TEXT、D9 时区混用、D11 KV 杂耍——**全部实查复现**。

## 6. 任务拆解（核心交付）

粒度约束：单任务 ≤1.5 人日、可独立 PR。风险标记：🔴不可逆数据迁移（依赖 §7 快照）｜🟠测试面大冲击｜🟡依赖他主题（主题三 container / 总规划 Phase）｜🟢低风险/可回退。

### 6.1 Phase 0 小步（先决止血，手工/脚本，不等 alembic）

| ID | 内容 | 涉及文件 | 依赖 | 验收标准（可执行） | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-01 | 运行库只读体检基线脚本：导出全表 DDL/`PRAGMA`/行数/孤儿数/JSON 非法数到 `drill-baseline.json`，作为 M0/回滚对照 | 新增 `scripts/storage_baseline_audit.py` | 无 | 脚本对 `mode=ro` 库运行，输出含 trajectory 孤儿=32、feedback 孤儿=1、`payload` 非法=0、SQLite≥3.35 | 0.5 | 🟢 |
| T2-02 | seq 手工回填脚本（仅 messages，幂等）：`UPDATE ... SET seq=(row_number() OVER(PARTITION BY conversation_id ORDER BY created_at,id))`，dry-run 预览 + `--apply` | 新增 `scripts/backfill_messages_seq.py` | T2-01 | dry-run 报告每会话 seq 连续唯一；apply 后 `SELECT COUNT(*) FROM (GROUP BY conversation_id,seq HAVING c>1)`=0 | 0.5 | 🟢 |
| T2-03 | 孤儿清理**前置**脚本（**只列不删**）：32+1 行清单导出 + 人工确认位 | 新增 `scripts/inventory_orphans.py` | T2-01 | 输出 orphan id 清单 == 实查计数；不产生任何写操作 | 0.5 | 🟢 |
| T2-04 | SQLite/FTS5 版本断言 + 迁移 CI 矩阵骨架 | `repository/db.py`(加 `check_sqlite_version`)、新增 `.github/workflows/storage.yml`(占位) | 无 | 本机/3.11-slim 容器内 `python -c "import sqlite3;assert tuple(map(int,sqlite3.sqlite_version.split('.')))>=(3,35,0))"` 通过 | 0.5 | 🟢 |

> Phase 0 只做"观测 + 无害回填 + 版本门"，**不开 FK、不删数据**——开 FK/删孤儿留 T2-13/T2-14 在迁移轨内做，避免总规划 §5.1 的"先开 FK 后旧查询炸"。

### 6.2 骨架（scaffolding）

| ID | 内容 | 涉及文件 | 依赖 | 验收标准 | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-05 | Alembic 落地：加依赖、包内 `migrations/`、`alembic.ini`、`env.py`（`render_as_batch`、`include_object` 排除 `checkpoints/writes/simhash_index*/messages_fts*`、支持**外部 connection** 供内存测试） | `pyproject.toml`、新增 `src/thumbelina/migrations/{env.py,script.py.mako,alembic.ini}` | T2-04 | `alembic heads` 列出 M0；`env.py` 能以传入 connection 建/校验内存库 | 1.0 | 🟢 |
| T2-06 | M0 baseline revision（手写现网漂移态镜像 DDL + 指纹表 + simhash `IF NOT EXISTS` 方言分支） | 新增 `migrations/versions/M0_baseline.py` | T2-05 | 对空库 `upgrade M0` 产表集 == §0.1 实测表集；对现网 `stamp M0` 不改数据 | 1.0 | 🟢 |
| T2-07 | 统一 `create_db_engine`（connect 事件设 `foreign_keys/WAL/busy_timeout/synchronous` + checkout 加载 sqlite-vec）与 `make_session_factory` | `repository/db.py`、`rag/common/db.py`(移除自挂事件) | T2-05 | `PRAGMA foreign_keys` 经工厂连接返回 1；内存/文件库均适用；vec 加载不抛（缺包仅告警） | 1.0 | 🟢 |
| T2-08 | `init_db` 改"revision 校验 + 版本断言"，不再 `create_all`/`ensure_schema`；`ensure_schema` 降级只读告警 | `repository/db.py`、`repository/models.py` | T2-06,T2-07 | 库处旧 revision 时启动 `SystemExit`（R11）；`ensure_schema` 无 ALTER 执行、仅 warn | 0.5 | 🟡（需 app 启动路径同步） |

### 6.3 代码层（依赖注入 + async 归一）

| ID | 内容 | 涉及文件 | 依赖 | 验收标准 | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-09 | `RepositoryManager` 作 engine 持有/分发者，新增 `make_feedback_repo/make_skill_repo/make_composition_repo`；**旧 `db_url:` 构造保持向后兼容**（内部转发） | `repository/manager.py` | T2-07 | 现有 `test_manager.py` 不改仍绿；`close()` 单次 dispose 全 engine | 1.0 | 🟢 |
| T2-10 | 6 仓储构造函数切注入签名（去各自 `create_db_engine`）+ 改 `api/app.py:221/256/280/297/298/511`、`cli/chat.py:179/194/205/222/223`、`config/loader.py:265/344` 调用点 | `repository/{repository,feedback_repo}.py`、`skills/{repository,composition_repo}.py`、`config/config_repo.py`、`api/app.py`、`cli/chat.py`、`config/loader.py` | T2-09 | 运行时同库活跃 engine 数从 ~5 降到 1（+checkpointer 独立）；`app.py` close 段（`682-699`）收敛 | 1.0 | 🟠 |
| T2-11 | `to_repo_thread` 装饰器归一 async 样板；`MAX_CONTENT_LENGTH` 100KB 校验从 `manager.py` 下沉 `ConversationRepository.add_message` | 新增 `repository/_async.py`；`repository/{repository,manager,feedback_repo}.py`、`skills/*.py` | T2-10 | 三仓储 async 包装写法一致；超长 content 在 repo 层即抛 | 1.0 | 🟠 |
| T2-12 | 写入侧 UTC：全量 `datetime.now()`→`datetime.now(timezone.utc)` + 模型 Python 默认值 | `repository/models.py`、`feedback_repo.py`、各写点 | T2-11 | 新写行 `created_at` 带 tz 语义一致；`test_feedback.py` 时间断言更新 | 0.5 | 🟢 |

### 6.4 迁移（M1–M5，含 ORM 对齐）

| ID | 内容 | 涉及文件 | 依赖 | 验收标准 | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-13 | M1：`messages.seq`(可空) + `conversations.user_id DEFAULT 'default'` + UTC 语义规范化；seq 回填（row_number） | 新增 `versions/M1_additive.py` | T2-06,T2-08 | `upgrade M1`：seq 全非空且按会话连续；user_id 全 'default'；`downgrade` 删两列 | 1.0 | 🟢 |
| T2-14 | M2：删 32 trajectory + 1 feedback 孤儿（先 `logger` 清单）；DROP `user_profiles/user_preferences` | 新增 `versions/M2_cleanup.py` | T2-13 | `upgrade` 后孤儿计数=0（R10）、两表不在 `sqlite_master`；`downgrade` 重建空表 | 0.5 | 🔴 |
| T2-15 | M3：`batch_alter_table` 重建 conversations/messages/feedback/trajectory/skills/compositions → 全 FK/CHECK/NOT NULL 收紧 + §1.11 索引（父表先子表后）+ 提交前 `foreign_key_check` 门 | 新增 `versions/M3_constraints.py` | T2-14（孤儿须先清） | R1/R5/R6/R7 全绿；`PRAGMA foreign_key_check` 空；EXPLAIN R3 | 1.5 | 🔴🟠 |
| T2-16 | M4：建 `llm_endpoints` + ETL 3 端点（position 取 index）+ 删端点 KV 与裸 `provider/model/base_url` + 建 `scheduled_tasks` 骨架 + `conversations.knowledge_base_id` 跨域 FK | 新增 `versions/M4_endpoints.py` | T2-15 | R9 端点数/字段等值；system_config 无端点键与死键；kb 无违规（实测 0）；down 反序列化回 KV | 1.5 | 🔴 |
| T2-17 | M5：`messages_fts` FTS5 external-content + 3 触发器 + `('rebuild')` 回填 | 新增 `versions/M5_fts.py` | T2-15 | R4：插/删消息后 MATCH 命中/移除同步；触发器存在 | 1.0 | 🟢 |
| T2-18 | ORM 模型对齐目标 schema：`Message.seq`、`Conversation.user_id`、各 `CheckConstraint`、`JSON` 列、`LlmEndpoint` 模型、`RagChunkFingerprint` 收编进 metadata | `repository/models.py`、`rag/common/orm_models.py` | T2-13..T2-17 | `create_all` 于空库产 DDL 与 M5 后 `head` 一致（metadata↔库对齐测试） | 1.0 | 🟢 |

### 6.5 读写接入新结构

| ID | 内容 | 涉及文件 | 依赖 | 验收标准 | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-19 | `get_messages` 排序键改 `(conversation_id,seq)`；`add_message` 事务内 `seq=max+1`（同会话原子） | `repository/repository.py:141-140,86-110` | T2-13,T2-18 | R2：同秒两消息 seq 递增且回放稳定 | 0.5 | 🟢 |
| T2-20 | `SearchEngine` 关键词主路径改 `messages_fts MATCH`，异常/短查询降级 LIKE | `repository/search.py`、`repository.py:571-612` | T2-17 | R4 命中；中文查询 LIKE 兜底仍返回；EXPLAIN 走 FTS | 1.0 | 🟢 |
| T2-21 | `llm_endpoints` 仓储（读写表、`get_active_endpoint`），替代 `EndpointManager` 现读 KV | 新增 `repository/endpoint_repo.py`（或并入 config）；`llm/endpoint_manager.py` 暂适配 | T2-16,T2-18 | 从表读出 3 端点、`is_default`/`active_model` 正确；端点写回走表 | 1.0 | 🟡（EndpointRegistry 完整化归主题三） |
| T2-22 | `DataLifecycleService.purge_conversation/purge_all`（DB 事务 + 库外 best-effort + PurgeReport）；`/data/all`、`/data/{id}` DELETE 接入 | 新增 `repository/lifecycle.py`；`api/routes/data.py:86-122` | T2-10,T2-15 | R1 级联；`/data/all` 报告含 skills/feedback/system_config/chroma/MEMORY 清理计数 | 1.5 | 🟠 |
| T2-23 | `backup/manager.py` 重写为 `BackupService`（Backup API 快照 + 文件域 tar + manifest{sha256,revision,row_counts} + 校验恢复 + 原子写），接 `/data/export` 与恢复脚本 | `backup/manager.py`、`api/routes/data.py:65-83` | T2-07,T2-22 | R8：备份→造脏→恢复→各表行数==manifest 且 `integrity_check=ok` | 1.5 | 🟠 |

### 6.6 测试与演练

| ID | 内容 | 涉及文件 | 依赖 | 验收标准 | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-24 | `tests/conftest.py`：`engine`/`session_factory` fixture 经 `alembic upgrade head`（env 外部 connection 模式）建库 + `seeded_repo` | 新增 `tests/conftest.py` | T2-05,T2-13..T2-18 | fixture 建的库含 FK/CHECK/FTS（探测触发器存在） | 1.0 | 🟠 |
| T2-25 | 迁移 repository/backup/skills/trajectory 全部真库测试到新注入签名 + 迁移建库 | `tests/test_repository/*`、`test_skills/*`、`test_trajectory/*`、`test_backup/*` | T2-10,T2-24 | 该批 pytest 全绿；无 `ConversationRepository(":memory:")` 旧式直构残留 | 1.5 | 🟠 |
| T2-26 | 回归断言 R1–R7（级联/seq/EXPLAIN 无 SCAN/FK/CHECK/唯一） | 新增 `tests/test_migrations/test_constraints.py` | T2-15,T2-24 | R1–R7 单测通过并进 CI | 1.0 | 🟢 |
| T2-27 | 回归断言 R8–R11（备份往返 / ETL / 孤儿清零 / revision 拒起） | 新增 `tests/test_migrations/test_backup_and_revision.py`、`test_endpoints_etl.py` | T2-16,T2-23,T2-08 | R8–R11 通过 | 1.0 | 🟠 |
| T2-28 | `scripts/drill_migration.py`：Backup API 副本→`stamp head`→`upgrade`→`integrity/fk_check`→`downgrade base`→`upgrade`→`drill-report.json` | 新增 `scripts/drill_migration.py` | T2-13..T2-18 | 对真实运行库副本全绿，双向可跑 | 1.0 | 🔴（接触真库数据，只读源+副本） |

### 6.7 收尾（部署挂点与仓库卫生）

| ID | 内容 | 涉及文件 | 依赖 | 验收标准 | 人日 | 风险 |
|---|---|---|---|---|---|---|
| T2-29 | 启动挂 `alembic upgrade head`：新增 `docker/entrypoint.sh` 包裹 CMD；compose `command:` 覆盖；部署文档补"升级先迁移" | `Dockerfile:69`、`docker-compose.yml`、`docs/docker-deployment.md` | T2-08 | 容器起法：先 upgrade head 再起 uvicorn；未迁移卷能被自动升级 | 0.5 | 🟡（部署面） |
| T2-30 | 仓库卫生：`test_rag.db`/`thumbelina.db.bak` 脱跟踪；`.gitignore` 覆盖 `*.db-wal`/`*.db-shm`/`*.tar`；3.2GB tar 跟踪状态核查 | `.gitignore`、`git rm --cached` | 无 | `git status` 干净且不再跟踪 db.bak/test_rag.db；大文件确认 | 0.5 | 🟢 |
| T2-31 | CI 矩阵：`python:3.11-slim` + 本机 3.13 双解释器跑 `upgrade head` + R1–R11 + 版本断言 + drill | `.github/workflows/storage.yml` | T2-04,T2-26,T2-28 | 两端 job 全绿（覆盖 Δ9 版本漂移） | 1.0 | 🟢 |
| T2-32 | 启动期 schema-drift 只读告警接线（metadata vs 库差异 → degraded 清单，不阻断）+ 主题三 degraded 日志口径对齐 | `api/app.py`(startup)、`repository/models.py` | T2-08,主题三 B2 | drift 时 warn 且不改库；与主题三 degraded 清单同格式 | 0.5 | 🟡 |

### 6.8 汇总与排期

- **任务总数：32（T2-01…T2-32）**。**总工时：约 29.0 人日**（Phase 0：2.0｜骨架：3.5｜代码：3.5｜迁移：6.5｜接入：5.5｜测试演练：5.5｜收尾：2.5）。与总规划 Phase 2"6–10 日主体 + Phase 0 若干"量级吻合（本主题含测试重写与备份重写，取上限偏上）。
- **建议 PR 顺序**（骨架→迁移→代码→测试→收尾，每 PR 独立可 revert）：
  1. PR-0（Phase 0）：T2-01→02→03→04（纯脚本/断言，零 schema 风险，最先合）。
  2. PR-1 骨架：T2-05→06→07→08（迁移通道打通，`init_db` 尚以"create_all 兜底"过渡，向后兼容）。
  3. PR-2 注入：T2-09→10→11→12（🟠 与 PR-3 fixture 改造需协调；建议 T2-24 同批或紧随，保 CI 绿）。
  4. PR-3 迁移 M1–M2：T2-13→14（🔴 T2-14 前必做 §7 快照）。
  5. PR-4 迁移 M3：T2-15（🔴🟠，配 R1–R7 的 T2-26 同批）。
  6. PR-5 迁移 M4–M5 + ORM：T2-16→17→18。
  7. PR-6 接入：T2-19→20→21→22→23。
  8. PR-7 测试/演练：T2-24→25→26→27→28。
  9. PR-8 收尾：T2-29→30→31→32。
- **关键前置依赖**：T2-15/T2-16/T2-14 三处 🔴 迁移**上线前必须先跑 T2-28 演练 + §7 快照**；T2-10 完成后方可开 `PRAGMA foreign_keys=ON`（避免旧多 engine 半开态）；T2-21/T2-32 的完整收口依赖**主题三 container / degraded 清单**，但主题二内已提供表与只读告警，不阻塞本主题交付。
- **跨主题**：`conversations.user_id`（T2-13）供主题一 owner 过滤；`scheduled_tasks`（T2-16）供主题五；`llm_endpoints`（T2-16）供主题三 `EndpointRegistry`；engine 注入点（T2-09/10）是主题三 `container` 的落点——本主题产出结构、后续主题消费。

## 7. 回滚预案

总规划主题二"影响·回滚：**难**——代码可 revert，但数据迁移（seq 回填、孤儿删除）不可逆，依赖迁移前快照"。本章给每个不可逆点的恢复路径与快照命名规约。

### 7.1 迁移前快照命名规约（唯一权威）

每次动真库数据前（M2/M3/M4 及其上线），先产快照，命名：
```
snapshots/pre-M<N>-<UTC YYYYMMDDTHHMMSS>Z/
   ├── thumbelina.db            # sqlite3 Backup API 一致快照（WAL 已 checkpoint，勿用 cp）
   ├── thumbelina.db.sha256     # 校验和
   ├── filedomain.tar           # MEMORY/ + TODO/ + data/chroma/（文件域，与库同快照点：先停写）
   ├── filedomain.tar.sha256
   └── manifest.json            # {version, git_sha, alembic_revision(pre), sqlite_version, row_counts{表:行数}, files{...}, ts}
```
`<N>` ∈ {2,3,4}。**停写**是前提（单写者约束，§3.5）：停 uvicorn/渠道后台任务→checkpoint WAL→Backup API→恢复服务。manifest 的 `row_counts` 与 `alembic_revision(pre)` 是恢复后对账与"回到哪个 revision"的依据。

### 7.2 逐迁移恢复路径

| 迁移 | 可逆性 | alembic `downgrade` 能做 | 真数据被破坏时的恢复（唯一正道） |
|---|---|---|---|
| M1 加 seq/user_id + UTC 规范化 | 结构可逆 | `downgrade M0`：DROP `seq`/`user_id`（列增量，旧代码本就忽略，revert 代码即回退） | 无需快照；即便不 downgrade，多余列无害 |
| M2 孤儿删除(32+1) + DROP 僵尸表 | **数据不可逆** | `downgrade` 仅重建空 `user_profiles/user_preferences`，**无法复生被删孤儿行** | 恢复 `snapshots/pre-M2-…`：Backup API 反向 `dst.backup` 覆盖 + 解 tar。僵尸表本为 0 行、零代码引用（§0.1）→ DROP 无需数据恢复，孤儿"恢复"实为"确认删除正确"的对账用途 |
| M3 FK/CHECK 收紧（表重建） | 结构可逆，**收紧后新写入可能失败** | `downgrade M2`：batch 重建回宽松态；FK/CHECK/索引移除 | 若收紧放行后仍漏进脏数据（理论不该，`foreign_key_check` 门挡），或旧代码写非法值致业务炸：**先 revert 代码**（停止非法写），必要时从 `pre-M3` 快照回滚库；正常路径 downgrade 即可 |
| M4 llm_endpoints ETL + 删 KV + 建 scheduled_tasks + 跨域 FK | ETL 可逆（有损风险） | `downgrade M3`：DROP 两新表 + 从 `llm_endpoints` 行反序列化回 `system_config` KV | **风险**：down 反序列化可能丢端点 JSON 的原字段顺序/多余字段（本文映射未覆盖的键）。故 **M4 前快照强制**；恢复以 `pre-M4` 快照为准，而非依赖 downgrade 重建 KV 的完备性 |
| M5 FTS | 可逆 | `downgrade M4`：DROP 触发器 + `messages_fts` | 无需快照；FTS 是派生索引，可 `('rebuild')` 重建 |

### 7.3 代码回滚 vs 数据回滚的时序

1. **纯代码问题**（如注入签名 bug、lifecycle 漏清）：`git revert` 对应 PR 即可——新库多出的列/表对旧代码向后兼容（总规划"影响·破坏性：中…向后兼容"），无需动数据。
2. **约束收紧导致旧写路径失败**（FK/CHECK 挡了历史脏写）：属"数据正确性收紧"的预期效果 → 不改回约束，而是修写入侧（本主题 T2-12/T2-19）；确需紧急放行才 `alembic downgrade` + 同步 revert 依赖新结构的代码。
3. **迁移本身跑坏**（M2/M3/M4 中途异常）：alembic 单迁移在事务内、失败自动回滚（SQLite DDL 事务性）；若已 `stamp` 错乱或半程提交，**一律从对应 `pre-M<N>` 快照整体还原库 + 文件域**，再 `alembic stamp <正确revision>` 复位。
4. **降级部署（旧镜像 + 新库）**：旧代码不认 `llm_endpoints` 表但会去 KV 读端点 → 端点读空。回滚代码时必须连带**回滚 M4 之前的库**（或临时用 M4.down 重建 KV 且校验无损）——这是最难回滚点，故 M4 快照不可省。

### 7.4 恢复后强制校验

任何一次恢复/回滚后，上线前跑：
```
PRAGMA integrity_check;                 -- 必须 'ok'
PRAGMA foreign_key_check;               -- 必须空
SELECT count(*) FROM <每表>;            -- 对账 manifest.row_counts
alembic current;                        -- == manifest.alembic_revision(pre) 或目标 revision
messages_fts MATCH '__probe__';         -- FTS 可用（若已过 M5）
python scripts/storage_baseline_audit.py # 与 pre 快照指纹 diff（R8/R10 同源断言）
```

---

（完）本文档为总规划主题二的可执行细化：§1 目标 schema、§2 Alembic 落地、§3 代码层、§4 测试与演练、§5 偏差、§6 任务拆解（32 任务 / ~29 人日）、§7 回滚预案。所有设计点均以 `file:line` 或运行库只读实查为依据；迁移可行性（FK/CHECK/JSON/跨域）已在真实数据上验证。
