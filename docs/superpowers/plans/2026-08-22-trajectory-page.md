# WEB“轨迹”页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增“轨迹”页，按对话轮次时间倒序审计展示用户消息、助手响应、工具调用请求/结果与上下文注入内容，并支持从聊天页一键跳转并过滤当前会话。

**Architecture:** 后端新增独立事件流表 `trajectory_events`（与 `messages` 解耦）；`TrajectoryRecorder` 挂接 agent 主链路（run/stream/工具节点）静默落盘；新路由 `/api/v1/trajectory/{conversation_id}` 按轮次分页倒序返回；前端新增导航标签 + `TrajectoryPage`（会话下拉过滤、轮次卡片、折叠事件、加载更多）+ 聊天页数据条“查看轨迹”按钮。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 / LangGraph / pytest（asyncio_mode=auto）；React 18 + TypeScript + Vite / Vitest / Testing Library / lucide-react。

**Spec:** `docs/superpowers/specs/2026-08-22-trajectory-page-design.md`

## Global Constraints

- payload 单条经 `json.dumps(..., ensure_ascii=False, default=str)` 序列化后 UTF-8 字节数 ≤ 65536；超限改为 `{"truncated": true, "preview": <前2000字符>}` 并标记 truncated。
- 轨迹写入任何失败只记 `logger.warning`，绝不抛出、绝不中断对话主流程。
- 轮次定义：一条用户消息开启一个轮次（`turn_id`），到该次助手最终响应结束；轮次内 `seq` 从 0 递增。
- API：`page >= 1`、`1 <= page_size <= 100`；conversation_id 不存在 → 404；参数越界 → 422。
- 轨迹页空状态文案固定为“请选择要查看的会话”。
- i18n 任何新增 key 必须同时更新 `frontend/src/i18n/locales/zh-CN.json` 与 `en.json`。
- 工作区存在用户未提交改动（如 `frontend/src/App.pageSwitch.test.tsx`、`start.sh` 删除等）；每次 `git add` 只添加本任务涉及文件，不 `git add -A`，不触碰用户未提交文件。
- 提交信息风格沿用仓库历史：中文、`feat:` / `docs:` 前缀（如 `feat: 新增轨迹事件存储`）。
- 前后端测试命令：后端 `python -m pytest <tests路径> -v`（repo 根目录）；前端 `cd frontend && npm test`。
- 后端 lint：`ruff check src tests` 与 `ruff format --check`（CI 强制，见 commit 18f6ec7）。

---

### Task 1: TrajectoryEvent 数据模型与建表

**Files:**
- Create: `tests/test_trajectory/test_model.py`（新目录）
- Modify: `src/thumbelina/repository/models.py`

**Interfaces:**
- Produces: SQLAlchemy model `TrajectoryEvent`（`declarative_base` = 现有 `Base`），字段见 §3.1。`init_db()` 内 `Base.metadata.create_all` 会自动建新表，无需迁移脚本。

- [ ] **Step 1: 写失败测试**

```python
"""TrajectoryEvent 模型建表与字段测试(设计文档 §3.1)。"""
from __future__ import annotations

from sqlalchemy import inspect as sa_inspect

from thumbelina.repository.db import create_db_engine, init_db


def test_trajectory_events_table_created(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path}/trajectory.db")
    session_factory = init_db(engine)

    inspector = sa_inspect(engine)
    assert "trajectory_events" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("trajectory_events")}
    assert cols == {
        "id",
        "conversation_id",
        "turn_id",
        "seq",
        "event_type",
        "payload",
        "created_at",
    }

    from thumbelina.repository.models import TrajectoryEvent

    with session_factory() as session:
        event = TrajectoryEvent(
            conversation_id="conv-1",
            turn_id="turn-1",
            seq=0,
            event_type="user",
            payload='{"content": "hello"}',
        )
        session.add(event)
        session.commit()
        row = session.get(TrajectoryEvent, event.id)
        assert row.turn_id == "turn-1"
        assert row.seq == 0
        assert row.event_type == "user"

    engine.dispose()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_trajectory/test_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'TrajectoryEvent' from 'thumbelina.repository.models'`）

- [ ] **Step 3: 实现模型**

在 `src/thumbelina/repository/models.py` 的 `Message` 类之后追加：

```python
class TrajectoryEvent(Base):
    """单条轨迹审计事件(设计文档 §3.1)。

    轮次概念:一条用户消息开启一个轮次(turn_id),到该次助手最终
    响应结束;同一轮次内 seq 从 0 递增保证回放顺序。
    """

    __tablename__ = "trajectory_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    turn_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
    )
    seq: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    event_type: Mapped[str] = mapped_column(
        String(20),
    )
    payload: Mapped[str] = mapped_column(
        Text,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_trajectory/test_model.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tests/test_trajectory/test_model.py src/thumbelina/repository/models.py
git commit -m "feat: 新增轨迹事件数据模型 trajectory_events"
```

---

### Task 2: TrajectoryRepository 与 RepositoryManager 接入

**Files:**
- Create: `src/thumbelina/repository/trajectory_repository.py`
- Modify: `src/thumbelina/repository/manager.py`
- Create: `tests/test_trajectory/test_repository.py`

**Interfaces:**
- Consumes: `TrajectoryEvent`（Task 1）；`ConversationRepository.engine/.SessionLocal`。
- Produces:
  - `TrajectoryRepository(conversation_repository)`，方法（均 async，内部 `asyncio.to_thread`）：
    - `add_events(conversation_id: str, events: list[dict[str, Any]]) -> None`，事件 dict 键：`turn_id`/`seq`/`event_type`/`payload`(JSON 字符串)/可选 `created_at`。
    - `has_events(conversation_id: str) -> bool`
    - `list_turns(conversation_id, page, page_size) -> tuple[int, list[tuple[str, datetime]]]`（total + 按轮次最早时间倒序的 (turn_id, started_at)）
    - `get_events(turn_ids: list[str]) -> list[dict[str, Any]]`（按 turn_id、seq 升序；`payload` 已解析为对象）
  - `RepositoryManager` 新方法：`add_trajectory_events(conversation_id, events)`、`has_trajectory(conversation_id) -> bool`、`get_trajectory_page(conversation_id, page, page_size) -> dict`（`{"total_turns": int, "turns": [{"turn_id", "started_at"(iso), "legacy": False, "events": [...]}]}`）。

- [ ] **Step 1: 写失败测试**

<details><summary>完整测试代码</summary>

```python
"""TrajectoryRepository 与 RepositoryManager 轨迹方法测试(设计文档 §3)。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from thumbelina.repository.manager import RepositoryManager


@pytest.fixture
def manager(tmp_path) -> RepositoryManager:
    m = RepositoryManager(f"sqlite:///{tmp_path}/trajectory.db")
    yield m
    m.close()


async def _seed(manager: RepositoryManager, conv_id: str) -> None:
    """三个轮次 t1(最早)/t2/t3(最新),每轮 user+assistant 两个事件。"""
    base = datetime(2026, 8, 20, 10, 0, 0)
    for i, turn in enumerate(["t1", "t2", "t3"]):
        events = [
            {
                "turn_id": turn,
                "seq": 0,
                "event_type": "user",
                "payload": json.dumps({"content": f"msg-{i}"}),
                "created_at": base + timedelta(minutes=i),
            },
            {
                "turn_id": turn,
                "seq": 1,
                "event_type": "assistant",
                "payload": json.dumps({"content": f"reply-{i}"}),
                "created_at": base + timedelta(minutes=i, seconds=5),
            },
        ]
        await manager.add_trajectory_events(conv_id, events)


async def test_has_trajectory(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    assert await manager.has_trajectory(conv_id) is False
    await manager.add_trajectory_events(
        conv_id,
        [{"turn_id": "t1", "seq": 0, "event_type": "user", "payload": "{}"}],
    )
    assert await manager.has_trajectory(conv_id) is True


async def test_page_newest_first_with_pagination(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    await _seed(manager, conv_id)

    page1 = await manager.get_trajectory_page(conv_id, page=1, page_size=2)
    assert page1["total_turns"] == 3
    assert [t["turn_id"] for t in page1["turns"]] == ["t3", "t2"]
    assert page1["turns"][0]["legacy"] is False
    assert [e["event_type"] for e in page1["turns"][0]["events"]] == ["user", "assistant"]
    assert page1["turns"][0]["events"][0]["payload"] == {"content": "msg-2"}

    page2 = await manager.get_trajectory_page(conv_id, page=2, page_size=2)
    assert [t["turn_id"] for t in page2["turns"]] == ["t1"]


async def test_events_ordered_by_seq(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    await manager.add_trajectory_events(
        conv_id,
        [
            {"turn_id": "t1", "seq": 1, "event_type": "assistant", "payload": "{}"},
            {"turn_id": "t1", "seq": 0, "event_type": "user", "payload": "{}"},
        ],
    )
    page = await manager.get_trajectory_page(conv_id, page=1, page_size=10)
    assert [e["event_type"] for e in page["turns"][0]["events"]] == ["user", "assistant"]
```

</details>

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_trajectory/test_repository.py -v`
Expected: FAIL（`AttributeError: 'RepositoryManager' object has no attribute 'add_trajectory_events'`）

<details><summary>Step 1 完整测试代码</summary>

```python
"""TrajectoryRepository 与 RepositoryManager 轨迹方法测试(设计文档 §3)。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from thumbelina.repository.manager import RepositoryManager


@pytest.fixture
def manager(tmp_path) -> RepositoryManager:
    m = RepositoryManager(f"sqlite:///{tmp_path}/trajectory.db")
    yield m
    m.close()


async def _seed(manager: RepositoryManager, conv_id: str) -> None:
    """三个轮次 t1(最早)/t2/t3(最新),每轮 user+assistant 两个事件。"""
    base = datetime(2026, 8, 20, 10, 0, 0)
    for i, turn in enumerate(["t1", "t2", "t3"]):
        events = [
            {
                "turn_id": turn,
                "seq": 0,
                "event_type": "user",
                "payload": json.dumps({"content": f"msg-{i}"}),
                "created_at": base + timedelta(minutes=i),
            },
            {
                "turn_id": turn,
                "seq": 1,
                "event_type": "assistant",
                "payload": json.dumps({"content": f"reply-{i}"}),
                "created_at": base + timedelta(minutes=i, seconds=5),
            },
        ]
        await manager.add_trajectory_events(conv_id, events)


async def test_has_trajectory(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    assert await manager.has_trajectory(conv_id) is False
    await manager.add_trajectory_events(
        conv_id,
        [{"turn_id": "t1", "seq": 0, "event_type": "user", "payload": "{}"}],
    )
    assert await manager.has_trajectory(conv_id) is True


async def test_page_newest_first_with_pagination(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    await _seed(manager, conv_id)

    page1 = await manager.get_trajectory_page(conv_id, page=1, page_size=2)
    assert page1["total_turns"] == 3
    assert [t["turn_id"] for t in page1["turns"]] == ["t3", "t2"]
    assert page1["turns"][0]["legacy"] is False
    assert [e["event_type"] for e in page1["turns"][0]["events"]] == ["user", "assistant"]
    assert page1["turns"][0]["events"][0]["payload"] == {"content": "msg-2"}

    page2 = await manager.get_trajectory_page(conv_id, page=2, page_size=2)
    assert [t["turn_id"] for t in page2["turns"]] == ["t1"]


async def test_events_ordered_by_seq(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    await manager.add_trajectory_events(
        conv_id,
        [
            {"turn_id": "t1", "seq": 1, "event_type": "assistant", "payload": "{}"},
            {"turn_id": "t1", "seq": 0, "event_type": "user", "payload": "{}"},
        ],
    )
    page = await manager.get_trajectory_page(conv_id, page=1, page_size=10)
    assert [e["event_type"] for e in page["turns"][0]["events"]] == ["user", "assistant"]
```

</details>

- [ ] **Step 3: 实现仓储**

创建 `src/thumbelina/repository/trajectory_repository.py`：

```python
"""Trajectory audit-event repository(设计文档 §3)。

与 :class:`ConversationRepository` 共享同一 engine/SessionLocal,
避免 SQLite 内存库出现两份独立连接池。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from thumbelina.repository.models import TrajectoryEvent
from thumbelina.repository.repository import ConversationRepository

logger = logging.getLogger(__name__)


class TrajectoryRepository:
    """轨迹事件存取：写事件、判断是否存在、按轮次分页倒序读。"""

    def __init__(self, conversation_repository: ConversationRepository) -> None:
        self.engine = conversation_repository.engine
        self.SessionLocal = conversation_repository.SessionLocal

    def _get_session(self) -> Session:
        return self.SessionLocal()

    def _add_events_sync(self, conversation_id: str, events: list[dict[str, Any]]) -> None:
        with self._get_session() as session:
            for e in events:
                kwargs: dict[str, Any] = {
                    "conversation_id": conversation_id,
                    "turn_id": e["turn_id"],
                    "seq": e["seq"],
                    "event_type": e["event_type"],
                    "payload": e["payload"],
                }
                if e.get("created_at") is not None:
                    kwargs["created_at"] = e["created_at"]
                session.add(TrajectoryEvent(**kwargs))
            session.commit()

    async def add_events(self, conversation_id: str, events: list[dict[str, Any]]) -> None:
        return await asyncio.to_thread(self._add_events_sync, conversation_id, events)

    def _has_events_sync(self, conversation_id: str) -> bool:
        with self._get_session() as session:
            row = session.execute(
                select(TrajectoryEvent.id)
                .where(TrajectoryEvent.conversation_id == conversation_id)
                .limit(1)
            ).first()
            return row is not None

    async def has_events(self, conversation_id: str) -> bool:
        return await asyncio.to_thread(self._has_events_sync, conversation_id)

    def _list_turns_sync(
        self, conversation_id: str, page: int, page_size: int
    ) -> tuple[int, list[tuple[str, datetime]]]:
        with self._get_session() as session:
            subq = (
                select(
                    TrajectoryEvent.turn_id,
                    func.min(TrajectoryEvent.created_at).label("started_at"),
                )
                .where(TrajectoryEvent.conversation_id == conversation_id)
                .group_by(TrajectoryEvent.turn_id)
                .subquery()
            )
            total = session.execute(select(func.count()).select_from(subq)).scalar_one()
            rows = session.execute(
                select(subq.c.turn_id, subq.c.started_at)
                .order_by(subq.c.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return total, [(r.turn_id, r.started_at) for r in rows]

    async def list_turns(
        self, conversation_id: str, page: int, page_size: int
    ) -> tuple[int, list[tuple[str, datetime]]]:
        return await asyncio.to_thread(self._list_turns_sync, conversation_id, page, page_size)

    def _get_events_sync(self, turn_ids: list[str]) -> list[dict[str, Any]]:
        if not turn_ids:
            return []
        with self._get_session() as session:
            rows = session.execute(
                select(TrajectoryEvent)
                .where(TrajectoryEvent.turn_id.in_(turn_ids))
                .order_by(TrajectoryEvent.turn_id, TrajectoryEvent.seq)
            ).scalars().all()
        result: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload: Any = json.loads(r.payload)
            except (ValueError, TypeError):
                payload = {"raw": r.payload}
            result.append(
                {
                    "turn_id": r.turn_id,
                    "seq": r.seq,
                    "event_type": r.event_type,
                    "payload": payload,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return result

    async def get_events(self, turn_ids: list[str]) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_events_sync, turn_ids)
```

- [ ] **Step 4: 接入 RepositoryManager**

修改 `src/thumbelina/repository/manager.py`：

顶部导入：

```python
from thumbelina.repository.trajectory_repository import TrajectoryRepository
```

`__init__` 中 `self._search_engine = ...` 之后追加：

```python
        self.trajectory_repository = TrajectoryRepository(self.conversation_repository)
```

在 `search` 方法之前追加（`Any` 已导入，无需新增导入）：

```python
    async def add_trajectory_events(
        self, conversation_id: str, events: list[dict[str, Any]]
    ) -> None:
        """写入一批轨迹事件(设计文档 §3.4)。"""
        await self.trajectory_repository.add_events(conversation_id, events)

    async def has_trajectory(self, conversation_id: str) -> bool:
        """该会话是否已有轨迹事件(无则走 legacy 合成,设计文档 §4.2)。"""
        return await self.trajectory_repository.has_events(conversation_id)

    async def get_trajectory_page(
        self, conversation_id: str, page: int, page_size: int
    ) -> dict[str, Any]:
        """按轮次分页返回轨迹(最新轮次在前),payload 已解析为对象。"""
        total, turns_meta = await self.trajectory_repository.list_turns(
            conversation_id, page, page_size
        )
        events = (
            await self.trajectory_repository.get_events([t for t, _ in turns_meta])
            if turns_meta
            else []
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            grouped.setdefault(ev["turn_id"], []).append(ev)
        turns = [
            {
                "turn_id": tid,
                "started_at": started_at.isoformat(),
                "legacy": False,
                "events": grouped.get(tid, []),
            }
            for tid, started_at in turns_meta
        ]
        return {"total_turns": total, "turns": turns}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_trajectory/test_repository.py -v`
Expected: 3 个测试全部 PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_trajectory/test_repository.py src/thumbelina/repository/trajectory_repository.py src/thumbelina/repository/manager.py
git commit -m "feat: 新增轨迹事件仓储并接入 RepositoryManager"
```

---

### Task 3: TrajectoryRecorder 与 agent 链路接入

**Files:**
- Create: `src/thumbelina/agent/trajectory.py`
- Modify: `src/thumbelina/agent/graph.py`
- Create: `tests/test_trajectory/test_recorder.py`

**Interfaces:**
- Consumes: `RepositoryManager.add_trajectory_events`（Task 2）。
- Produces: `TrajectoryRecorder(repository_manager)`，方法：
  - `begin_turn(conversation_id: str | None) -> None`（同步；None 时后续记录全部跳过）
  - `record_user(content: str) -> None`（async）
  - `record_context(items: list[dict[str, str]]) -> None`（async；items 形如 `[{"kind": "role_prompt|memory|rag|skill", "content": str}]`）
  - `record_tool_call(tool: str, args: object, call_id: str) -> None`（async）
  - `record_tool_result(call_id: str, content: str, is_error: bool) -> None`（async）
  - `record_assistant(content: str, reasoning: str | None = None) -> None`（async）
  - `enabled`（property：manager 存在且持有 `add_trajectory_events` 时 True）
  - 所有记录方法内部 try/except，失败仅 `logger.warning`。

- [ ] **Step 1: 写失败测试**

```python
"""TrajectoryRecorder 单元测试(设计文档 §3.4/§3.5)。"""
from __future__ import annotations

import json

from thumbelina.agent.trajectory import MAX_PAYLOAD_BYTES, TrajectoryRecorder


class FakeManager:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def add_trajectory_events(self, conversation_id: str, events: list[dict]) -> None:
        self.events.extend(events)


async def test_turn_events_sequenced():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_user("你好")
    await recorder.record_context([{"kind": "memory", "content": "记忆摘要"}])
    await recorder.record_tool_call("search", {"q": "x"}, "call-1")
    await recorder.record_tool_result("call-1", "结果", is_error=False)
    await recorder.record_assistant("好的", reasoning="思考")

    assert [e["event_type"] for e in manager.events] == [
        "user",
        "context",
        "tool_call",
        "tool_result",
        "assistant",
    ]
    assert [e["seq"] for e in manager.events] == [0, 1, 2, 3, 4]
    assert all(e["turn_id"] == manager.events[0]["turn_id"] for e in manager.events)
    assert json.loads(manager.events[2]["payload"])["tool"] == "search"


async def test_disabled_without_manager_method():
    class EmptyManager:
        pass

    recorder = TrajectoryRecorder(EmptyManager())
    recorder.begin_turn("conv-1")
    await recorder.record_user("你好")
    assert recorder.enabled is False


async def test_records_nothing_without_begin_turn():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    await recorder.record_user("你好")
    assert manager.events == []


async def test_truncates_oversized_payload():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_user("x" * (MAX_PAYLOAD_BYTES * 2))
    payload = json.loads(manager.events[0]["payload"])
    assert payload.get("truncated") is True
    assert "preview" in payload


async def test_serialize_failure_falls_back():
    class BadObject:
        def __str__(self) -> str:  # type: ignore[override]
            raise RuntimeError("boom")

    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_tool_call("boom", {"arg": BadObject()}, "call-1")
    payload = json.loads(manager.events[0]["payload"])
    assert payload == {"error": "serialize_failed"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_trajectory/test_recorder.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'thumbelina.agent.trajectory'`）

- [ ] **Step 3: 实现记录器**

创建 `src/thumbelina/agent/trajectory.py`：

```python
"""轨迹记录器(设计文档 §3.4/§3.5)。

把每个对话轮次的用户消息、上下文注入、工具调用/结果、助手响应
静默写入 trajectory_events。任何失败仅记 warning,绝不干扰对话主流程。
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 65536


class TrajectoryRecorder:
    """按轮次累积并异步落盘轨迹事件。

    ``begin_turn`` 开启新轮次;此后每次 ``record_*`` 立即写一条事件
    (seq 递增保证轮次内顺序)。会话 id 为 None 或 manager 不提供
    ``add_trajectory_events`` 时整体降级为空操作。
    """

    def __init__(self, repository_manager) -> None:
        self._manager = repository_manager
        self._conversation_id: str | None = None
        self._turn_id: str | None = None
        self._seq = 0

    @property
    def enabled(self) -> bool:
        return self._manager is not None and hasattr(self._manager, "add_trajectory_events")

    def begin_turn(self, conversation_id: str | None) -> None:
        self._conversation_id = conversation_id
        self._turn_id = str(uuid4()) if conversation_id else None
        self._seq = 0

    async def record_user(self, content: str) -> None:
        await self._record("user", {"content": content})

    async def record_context(self, items: list[dict[str, str]]) -> None:
        await self._record("context", {"items": items})

    async def record_tool_call(self, tool: str, args: object, call_id: str) -> None:
        await self._record("tool_call", {"tool": tool, "args": args, "call_id": call_id})

    async def record_tool_result(self, call_id: str, content: str, is_error: bool) -> None:
        await self._record(
            "tool_result", {"call_id": call_id, "content": content, "is_error": is_error}
        )

    async def record_assistant(self, content: str, reasoning: str | None = None) -> None:
        await self._record("assistant", {"content": content, "reasoning": reasoning})

    async def _record(self, event_type: str, payload: dict) -> None:
        if not self.enabled or self._turn_id is None or not self._conversation_id:
            return
        try:
            serialized = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            serialized = json.dumps({"error": "serialize_failed"})
        if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            serialized = json.dumps(
                {"truncated": True, "preview": serialized[:2000]}, ensure_ascii=False
            )
        event = {
            "turn_id": self._turn_id,
            "seq": self._seq,
            "event_type": event_type,
            "payload": serialized,
        }
        self._seq += 1
        try:
            await self._manager.add_trajectory_events(self._conversation_id, [event])
        except Exception:
            logger.warning("Failed to record trajectory event", exc_info=True)
```

- [ ] **Step 4: 接入 agent 链路**

修改 `src/thumbelina/agent/graph.py`：

顶部导入：

```python
from thumbelina.agent.trajectory import TrajectoryRecorder
```

在 `__init__` 中 `self.repository_manager` 赋值之后追加：

```python
        self.trajectory_recorder = TrajectoryRecorder(self.repository_manager)
```

`run()`（约 L1180）中 user 持久化处：

```python
        await self._ensure_conversation()
        self.trajectory_recorder.begin_turn(self.current_conversation_id)
        await self._persist_message("user", user_input)
        await self.trajectory_recorder.record_user(user_input)
```

同位置同步修改 `stream()`（约 L1217）为相同三行。

`run()` 末尾（约 L1195）：

```python
        await self._persist_message("assistant", response)
        await self.trajectory_recorder.record_assistant(response)
```

`stream()` 末尾（约 L1285-1288）：

```python
        if full_response:
            await self._persist_message(
                "assistant", full_response, reasoning_content=full_reasoning or None
            )
            await self.trajectory_recorder.record_assistant(full_response, full_reasoning or None)
```

`_build_initial_messages()`（L907-955）注入收集：在函数内声明 `traj_items: list[dict[str, str]] = []`，在各注入点同步 append：

- role_prompt 处：`traj_items.append({"kind": "role_prompt", "content": self.role_prompt})`
- memory_context 处：`traj_items.append({"kind": "memory", "content": memory_context})`
- rag_context 处：`traj_items.append({"kind": "rag", "content": rag_context})`
- skill_context 处：`traj_items.append({"kind": "skill", "content": skill_context})`

在 `messages.append(HumanMessage(content=user_input))` 之后、`return messages` 之前追加：

```python
        await self.trajectory_recorder.record_context(traj_items)
        return messages
```

`_tool_node_node()`（L864-866）替换为：

```python
    async def _tool_node_node(self, state: AgentState) -> dict[str, list[Any]]:
        """Node wrapper for executing tools."""
        calls: list[dict] = []
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage):
            calls = list(last_message.tool_calls or [])
        for tool_call in calls:
            await self.trajectory_recorder.record_tool_call(
                tool_call.get("name", ""), tool_call.get("args", {}), tool_call.get("id", "")
            )
        result = await tool_node(state, self.tools)
        tool_messages = result.get("messages", [])
        for tool_call, tool_message in zip(calls, tool_messages):
            content = str(getattr(tool_message, "content", ""))
            await self.trajectory_recorder.record_tool_result(
                tool_call.get("id", ""), content, is_error=content.startswith("Error")
            )
        return result
```

（`AIMessage` 已在 graph.py 顶部导入，`Any` 亦已导入。）

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_trajectory/test_recorder.py -v`
Expected: 5 个测试全部 PASS

再运行回归：`python -m pytest tests/test_agent tests/test_api -q`
Expected: 无回归失败（agent 相关既有测试使用 Mock repository_manager，`hasattr` 判定使其静默跳过）

- [ ] **Step 6: 提交**

```bash
git add src/thumbelina/agent/trajectory.py src/thumbelina/agent/graph.py tests/test_trajectory/test_recorder.py
git commit -m "feat: 实现轨迹记录器并接入 agent 主链路"
```

---

### Task 4: 轨迹查询 API 路由

**Files:**
- Create: `src/thumbelina/api/routes/trajectory.py`
- Modify: `src/thumbelina/api/app.py`
- Create: `tests/test_api/test_trajectory.py`

**Interfaces:**
- Consumes: `RepositoryManager.get_conversation/.has_trajectory/.get_trajectory_page/.get_messages`（Task 2）。
- Produces: `GET /api/v1/trajectory/{conversation_id}?page=&page_size=`，响应：
  `{"conversation_id", "conversation_name", "legacy", "total_turns", "page", "page_size", "turns": [{"turn_id", "started_at", "legacy", "events": [{"seq", "event_type", "payload", "created_at"}]}]}`。

- [ ] **Step 1: 写失败测试**

<details><summary>完整测试代码</summary>

```python
"""轨迹 API 测试(设计文档 §4)。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thumbelina.api.routes.trajectory import router
from thumbelina.repository.manager import RepositoryManager


@pytest.fixture
def trajectory_client(tmp_path: Path):
    manager = RepositoryManager(f"sqlite:///{tmp_path}/trajectory.db")
    app = FastAPI()
    app.state.repository_manager = manager
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client, manager
    manager.close()


async def _seed_events(manager: RepositoryManager, conv_id: str) -> None:
    base = datetime(2026, 8, 20, 10, 0, 0)
    for i, turn in enumerate(["t1", "t2", "t3"]):
        await manager.add_trajectory_events(
            conv_id,
            [
                {
                    "turn_id": turn,
                    "seq": 0,
                    "event_type": "user",
                    "payload": json.dumps({"content": f"msg-{i}"}),
                    "created_at": base + timedelta(minutes=i),
                },
                {
                    "turn_id": turn,
                    "seq": 1,
                    "event_type": "assistant",
                    "payload": json.dumps({"content": f"reply-{i}"}),
                    "created_at": base + timedelta(minutes=i, seconds=5),
                },
            ],
        )


async def test_404_unknown_conversation(trajectory_client):
    client, _ = trajectory_client
    res = client.get("/api/v1/trajectory/unknown-id")
    assert res.status_code == 404


async def test_trajectory_pagination_newest_first(trajectory_client):
    client, manager = trajectory_client
    conv_id = await manager.create_conversation(name="会话A")
    await _seed_events(manager, conv_id)

    res = client.get(f"/api/v1/trajectory/{conv_id}?page=1&page_size=2")
    assert res.status_code == 200
    data = res.json()
    assert data["legacy"] is False
    assert data["conversation_name"] == "会话A"
    assert data["total_turns"] == 3
    assert [t["turn_id"] for t in data["turns"]] == ["t3", "t2"]
    assert data["turns"][0]["events"][0]["payload"] == {"content": "msg-2"}

    res2 = client.get(f"/api/v1/trajectory/{conv_id}?page=2&page_size=2")
    assert [t["turn_id"] for t in res2.json()["turns"]] == ["t1"]


async def test_legacy_synthesis(trajectory_client):
    client, manager = trajectory_client
    conv_id = await manager.create_conversation(name="旧会话")
    await manager.add_message(conv_id, "user", "你好")
    await manager.add_message(conv_id, "assistant", "在的")

    res = client.get(f"/api/v1/trajectory/{conv_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["legacy"] is True
    assert data["total_turns"] == 1
    turn = data["turns"][0]
    assert [e["event_type"] for e in turn["events"]] == ["user", "assistant"]
    assert turn["events"][0]["payload"] == {"content": "你好"}


async def test_validation_errors(trajectory_client):
    client, _ = trajectory_client
    res = client.get("/api/v1/trajectory/x?page=0")
    assert res.status_code == 422
    res = client.get("/api/v1/trajectory/x?page_size=101")
    assert res.status_code == 422
```

</details>


- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api/test_trajectory.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'thumbelina.api.routes.trajectory'`）

- [ ] **Step 3: 实现路由**

创建 `src/thumbelina/api/routes/trajectory.py`：

```python
"""轨迹(审计)API 路由(设计文档 §4)。

- 有轨迹事件的会话按轮次分页倒序返回。
- 无轨迹事件的旧会话从 messages 表合成轮次(legacy)。
- conversation_id 不存在 → 404;page/page_size 越界 → 422。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from thumbelina.api.deps import get_repository_manager
from thumbelina.repository.manager import RepositoryManager

router = APIRouter(prefix="/trajectory", tags=["trajectory"])

_PAGE_SIZE_MAX = 100


def _synthesize_legacy_turns(
    messages: list[dict[str, Any]], page: int, page_size: int
) -> dict[str, Any]:
    """把纯文本消息史合成为轮次(设计文档 §4.2):user 开轮、后续 assistant 归入。"""
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for msg in messages:
        role = msg.get("role")
        created_at = msg.get("created_at", "")
        if role == "user":
            current = {
                "turn_id": f"legacy-{msg['id']}",
                "started_at": created_at,
                "legacy": True,
                "events": [
                    {
                        "seq": 0,
                        "event_type": "user",
                        "payload": {"content": msg.get("content", "")},
                        "created_at": created_at,
                    }
                ],
            }
            turns.append(current)
        elif role == "assistant":
            if current is None:
                current = {
                    "turn_id": f"legacy-{msg['id']}",
                    "started_at": created_at,
                    "legacy": True,
                    "events": [],
                }
                turns.append(current)
            current["events"].append(
                {
                    "seq": len(current["events"]),
                    "event_type": "assistant",
                    "payload": {"content": msg.get("content", "")},
                    "created_at": created_at,
                }
            )
    turns.reverse()
    total = len(turns)
    start = (page - 1) * page_size
    page_turns = turns[start : start + page_size]
    return {"total_turns": total, "page": page, "page_size": page_size, "turns": page_turns}


@router.get("/{conversation_id}")
async def get_trajectory(
    conversation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=_PAGE_SIZE_MAX),
    repository: RepositoryManager = Depends(get_repository_manager),
) -> dict[str, Any]:
    """按轮次分页返回轨迹(最新轮次在前)。"""
    conversation = await repository.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    name = conversation.get("name")
    if await repository.has_trajectory(conversation_id):
        data = await repository.get_trajectory_page(conversation_id, page, page_size)
        return {
            "conversation_id": conversation_id,
            "conversation_name": name,
            "legacy": False,
            **data,
            "page": page,
            "page_size": page_size,
        }
    messages = await repository.get_messages(conversation_id)
    data = _synthesize_legacy_turns(messages, page, page_size)
    return {
        "conversation_id": conversation_id,
        "conversation_name": name,
        "legacy": True,
        **data,
    }
```

- [ ] **Step 4: 注册路由**

修改 `src/thumbelina/api/app.py`：

L30-43 的 `from thumbelina.api.routes import (...)` 元组中追加 `trajectory,`；L799-811 的 `include_router` 区域 `memory` 之后追加：

```python
    app.include_router(trajectory.router, prefix="/api/v1")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_api/test_trajectory.py -v`
Expected: 4 个测试全部 PASS

回归：`python -m pytest tests/test_api -q` 通过。

- [ ] **Step 6: 提交**

```bash
git add tests/test_api/test_trajectory.py src/thumbelina/api/routes/trajectory.py src/thumbelina/api/app.py
git commit -m "feat: 新增轨迹查询 API"
```

---

### Task 5: 前端轨迹页组件与 i18n

**Files:**
- Create: `frontend/src/types/trajectory.ts`
- Create: `frontend/src/api/trajectory.ts`
- Create: `frontend/src/components/Trajectory/TrajectoryPage.tsx`
- Create: `frontend/src/components/Trajectory/TrajectoryPage.test.tsx`
- Modify: `frontend/src/i18n/locales/zh-CN.json`
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/App.css`

**Interfaces:**
- Produces: `TrajectoryPage`（props：`initialConversationId?: string`），data-testid：`trajectory-page`、`trajectory-select`、`trajectory-empty`、`turn-card`、`turn-event`、`event-toggle`、`trajectory-load-more`、`trajectory-error`、`retry-button`。

- [ ] **Step 1: 写失败测试**

```python
（前端测试为 TS 文件，见下方完整代码）
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test -- --run TrajectoryPage`（或 `npx vitest run src/components/Trajectory/TrajectoryPage.test.tsx`）
Expected: FAIL（找不到 `./TrajectoryPage` 模块）

<details><summary>Step 1 完整测试代码（TS）</summary>

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TrajectoryPage } from './TrajectoryPage'

const TRAJECTORY_DATA = {
  conversation_id: 'c1',
  conversation_name: '会话1',
  legacy: false,
  total_turns: 3,
  page: 1,
  page_size: 2,
  turns: [
    {
      turn_id: 't3',
      started_at: '2026-08-22T10:03:11',
      legacy: false,
      events: [
        { seq: 0, event_type: 'user', payload: { content: '你好' }, created_at: '2026-08-22T10:03:11' },
        { seq: 1, event_type: 'tool_call', payload: { tool: 'search', args: { q: 'x' }, call_id: 'c1' }, created_at: '2026-08-22T10:03:12' },
        { seq: 2, event_type: 'tool_result', payload: { call_id: 'c1', content: '结果A', is_error: false }, created_at: '2026-08-22T10:03:13' },
        { seq: 3, event_type: 'assistant', payload: { content: '好的' }, created_at: '2026-08-22T10:03:14' },
      ],
    },
    {
      turn_id: 't2',
      started_at: '2026-08-22T10:00:00',
      legacy: true,
      events: [
        { seq: 0, event_type: 'user', payload: { content: '旧消息' }, created_at: '2026-08-22T10:00:00' },
        { seq: 1, event_type: 'assistant', payload: { content: '旧回复' }, created_at: '2026-08-22T10:00:01' },
      ],
    },
  ],
}

const CONVERSATIONS = [{ id: 'c1', name: '会话1', created_at: '2026-08-01', updated_at: '2026-08-22' }]

function mockFetchOnce(resp: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(resp), { status: 200 }))
}

describe('TrajectoryPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockFetchOnce(CONVERSATIONS)
  })

  it('默认空状态：不请求轨迹数据', async () => {
    const fetchSpy = mockFetchOnce(CONVERSATIONS)
    render(<TrajectoryPage />)
    expect(await screen.findByTestId('trajectory-empty')).toBeInTheDocument()
    expect(fetchSpy.mock.calls.some(c => c[0].includes('/trajectory/'))).toBe(false)
  })

  it('选择会话后加载轨迹并展示轮次', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    render(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })

    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(2)
    })
    expect(screen.getByText('你好')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('/trajectory/c1?page=1'))
  })

  it('工具调用与上下文事件默认折叠，点击展开', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    render(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })

    const toggle = await screen.findAllByTestId('event-toggle')
    expect(toggle.length).toBeGreaterThan(0)
    expect(screen.queryByText('结果A')).not.toBeInTheDocument()
    fireEvent.click(toggle[0])
    expect(await screen.findByText('结果A')).toBeInTheDocument()
  })

  it('legacy 轮次展示旧记录提示', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    render(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })
    expect(await screen.findByText('旧记录：无工具调用/上下文数据')).toBeInTheDocument()
  })

  it('加载更多：翻页追加', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        const page = url.includes('page=2') ? 2 : 1
        return Promise.resolve(new Response(JSON.stringify({
          ...TRAJECTORY_DATA,
          page,
          turns: page === 2 ? [{ ...TRAJECTORY_DATA.turns[0], turn_id: 't1' }] : TRAJECTORY_DATA.turns,
        }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    render(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })
    await screen.findAllByTestId('turn-card')

    fireEvent.click(screen.getByTestId('trajectory-load-more'))
    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(3)
    })
  })

  it('加载失败展示错误与重试', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.reject(new Error('network'))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    render(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })
    expect(await screen.findByTestId('trajectory-error')).toBeInTheDocument()

    fetchSpy.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    fireEvent.click(screen.getByTestId('retry-button'))
    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(2)
    })
  })
})
```

</details>

- [ ] **Step 3: 实现类型与 API 客户端**

创建 `frontend/src/types/trajectory.ts`：

```ts
export interface TrajectoryEvent {
  seq: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface TrajectoryTurn {
  turn_id: string
  started_at: string
  legacy: boolean
  events: TrajectoryEvent[]
}

export interface TrajectoryPageData {
  conversation_id: string
  conversation_name?: string | null
  legacy: boolean
  total_turns: number
  page: number
  page_size: number
  turns: TrajectoryTurn[]
}
```

创建 `frontend/src/api/trajectory.ts`：

```ts
import type { TrajectoryPageData } from '../types/trajectory'

const API_BASE = '/api/v1'

export async function fetchTrajectory(conversationId: string, page = 1, pageSize = 20): Promise<TrajectoryPageData> {
  const res = await fetch(`${API_BASE}/trajectory/${encodeURIComponent(conversationId)}?page=${page}&page_size=${pageSize}`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<TrajectoryPageData>
}
```

- [ ] **Step 4: 实现 TrajectoryPage 组件**

创建 `frontend/src/components/Trajectory/TrajectoryPage.tsx`：

```tsx
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, RefreshCw } from 'lucide-react'
import type { Conversation } from '../../types/chat'
import type { TrajectoryPageData, TrajectoryTurn } from '../../types/trajectory'
import { fetchTrajectory } from '../../api/trajectory'
import { useTranslation } from '../../i18n'

const PAGE_SIZE = 20

export function TrajectoryPage({ initialConversationId }: { initialConversationId?: string }) {
  const { t } = useTranslation()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>(initialConversationId)
  const [data, setData] = useState<TrajectoryPageData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    fetch('/api/v1/conversations')
      .then(res => (res.ok ? res.json() : []))
      .then(list => setConversations(Array.isArray(list) ? list : []))
      .catch(() => setConversations([]))
  }, [])

  const load = useCallback(async (conversationId: string, page: number, append: boolean) => {
    setLoading(true)
    setError('')
    try {
      const pageData = await fetchTrajectory(conversationId, page, PAGE_SIZE)
      setData(prev => {
        if (append && prev && prev.conversation_id === conversationId) {
          return { ...pageData, turns: [...prev.turns, ...pageData.turns] }
        }
        return pageData
      })
    } catch {
      setError(t('trajectory.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (selectedId) {
      void load(selectedId, 1, false)
    } else {
      setData(null)
    }
  }, [selectedId, load])

  const handleSelect = (id: string) => {
    setSelectedId(id)
    setExpanded({})
  }

  const toggle = useCallback((key: string) => {
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const hasMore = data !== null && data.turns.length < data.total_turns

  return (
    <div className="trajectory-page" data-testid="trajectory-page">
      <h2>{t('trajectory.title')}</h2>
      <select
        data-testid="trajectory-select"
        value={selectedId ?? ''}
        onChange={e => handleSelect(e.target.value)}
        className="trajectory-select"
      >
        <option value="">{t('trajectory.selectPlaceholder')}</option>
        {conversations.map(c => (
          <option key={c.id} value={c.id}>{c.name || c.id}</option>
        ))}
      </select>

      {!selectedId && <div className="trajectory-empty" data-testid="trajectory-empty">{t('trajectory.selectPlaceholder')}</div>}

      {error && (
        <div className="trajectory-error" data-testid="trajectory-error">
          {error}
          <button type="button" data-testid="retry-button" onClick={() => selectedId && void load(selectedId, 1, false)}>
            <RefreshCw size={14} /> {t('trajectory.retry')}
          </button>
        </div>
      )}

      {data?.turns.map((turn, turnIndex) => (
        <TurnCard
          key={turn.turn_id}
          turn={turn}
          index={turnIndex}
          expanded={expanded}
          onToggle={toggle}
        />
      ))}

      {hasMore && (
        <button
          type="button"
          className="trajectory-load-more"
          data-testid="trajectory-load-more"
          disabled={loading}
          onClick={() => selectedId && void load(selectedId, (data?.page ?? 1) + 1, true)}
        >
          {loading ? <Loader2 size={14} /> : null} {t('trajectory.loadMore')}
        </button>
      )}
    </div>
  )
}

function TurnCard({ turn, index, expanded, onToggle }: {
  turn: TrajectoryTurn
  index: number
  expanded: Record<string, boolean>
  onToggle: (key: string) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="turn-card" data-testid="turn-card">
      <div className="turn-header">
        <span>{t('trajectory.turn')} #{index + 1}</span>
        <span className="turn-time">{turn.started_at}</span>
        {turn.legacy && <span className="turn-legacy">{t('trajectory.legacyNote')}</span>}
      </div>
      <div className="turn-events">
        {turn.events.map(event => {
          if (event.event_type === 'user') {
            return (
              <div key={event.seq} className="turn-event message-user" data-testid="turn-event">
                <span className="event-badge">{t('trajectory.user')}</span>
                <span className="event-content">{String(event.payload.content ?? '')}</span>
              </div>
            )
          }
          if (event.event_type === 'assistant') {
            return (
              <div key={event.seq} className="turn-event message-assistant" data-testid="turn-event">
                <span className="event-badge">{t('trajectory.assistant')}</span>
                <span className="event-content">{String(event.payload.content ?? '')}</span>
              </div>
            )
          }
          const label = event.event_type === 'context'
            ? t('trajectory.context')
            : event.event_type === 'tool_call'
              ? `${t('trajectory.toolCall')}: ${String((event.payload as Record<string, unknown>).tool ?? '')}`
              : t('trajectory.toolResult')
          const key = `${turn.turn_id}-${event.seq}`
          const isOpen = !!expanded[key]
          const isError = event.event_type === 'tool_result' && (event.payload as Record<string, unknown>).is_error === true
          return (
            <div key={event.seq} className={`turn-event event-tech${isError ? ' event-error' : ''}`} data-testid="turn-event">
              <button
                type="button"
                className="event-toggle"
                data-testid="event-toggle"
                onClick={() => onToggle(key)}
              >
                {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                {label}
              </button>
              {isOpen && (
                <pre className="event-detail">{JSON.stringify(event.payload, null, 2)}</pre>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

（轮次序号直接拼接 `#{index + 1}`，末期不依赖 i18n 插值。）

- [ ] **Step 5: 添加 i18n 文案**

`zh-CN.json` 的 `"dream"` 段之前新增：

```json
  "trajectory": {
    "title": "轨迹",
    "selectPlaceholder": "请选择要查看的会话",
    "loadMore": "加载更多",
    "loading": "加载中…",
    "loadFailed": "加载失败",
    "retry": "重试",
    "legacyNote": "旧记录：无工具调用/上下文数据",
    "toolCall": "工具调用",
    "toolResult": "工具结果",
    "context": "上下文",
    "user": "用户",
    "assistant": "助手",
    "turn": "轮次"
  },
```

`en.json` 对应新增：

```json
  "trajectory": {
    "title": "Trajectory",
    "selectPlaceholder": "Please select a conversation to view",
    "loadMore": "Load more",
    "loading": "Loading…",
    "loadFailed": "Failed to load",
    "retry": "Retry",
    "legacyNote": "Legacy record: no tool call / context data",
    "toolCall": "Tool call",
    "toolResult": "Tool result",
    "context": "Context",
    "user": "User",
    "assistant": "Assistant",
    "turn": "Turn"
  },
```

- [ ] **Step 6: 添加样式**

在 `frontend/src/App.css` 末尾追加：

```css
.trajectory-page { padding: 16px; max-width: 960px; margin: 0 auto; }
.trajectory-page h2 { margin-bottom: 12px; }
.trajectory-select { width: 100%; max-width: 400px; padding: 8px 10px; margin-bottom: 16px; border-radius: 6px; border: 1px solid var(--border-color, #444); background: var(--bg-input, #1e1e1e); color: inherit; }
.trajectory-empty { padding: 32px; text-align: center; color: #888; }
.trajectory-error { padding: 12px; margin-bottom: 12px; border: 1px solid #c33; border-radius: 6px; color: #c33; display: flex; gap: 12px; align-items: center; }
.trajectory-error button { display: inline-flex; align-items: center; gap: 4px; }
.trajectory-load-more { display: block; margin: 16px auto; padding: 8px 16px; }
.turn-card { border: 1px solid var(--border-color, #444); border-radius: 8px; margin-bottom: 12px; padding: 12px; }
.turn-header { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; font-weight: 600; }
.turn-time { font-weight: 400; color: #888; }
.turn-legacy { font-size: 12px; color: #b58900; border: 1px solid currentColor; border-radius: 4px; padding: 0 6px; }
.turn-events { display: flex; flex-direction: column; gap: 6px; }
.turn-event { display: flex; gap: 8px; align-items: flex-start; padding: 6px 8px; border-radius: 6px; }
.turn-event.message-user { background: rgba(80, 120, 255, 0.08); }
.turn-event.message-assistant { background: rgba(80, 200, 120, 0.08); }
.turn-event.event-tech { flex-direction: column; }
.turn-event.event-error { border: 1px solid #c33; }
.event-badge { flex-shrink: 0; font-size: 12px; border-radius: 4px; padding: 0 6px; background: #333; }
.event-content { white-space: pre-wrap; word-break: break-word; }
.event-toggle { display: inline-flex; align-items: center; gap: 6px; background: none; border: none; color: inherit; cursor: pointer; font-family: inherit; }
.event-detail { width: 100%; max-height: 320px; overflow: auto; font-size: 12px; background: rgba(0, 0, 0, 0.25); padding: 8px; border-radius: 6px; }
```

- [ ] **Step 7: 运行测试与构建确认通过**

Run: `cd frontend && npm test`
Expected: 既有测试 + 新增 TrajectoryPage 测试全部 PASS

Run: `cd frontend && npm run build`（`tsc -b && vite build`）
Expected: 类型检查与构建通过

- [ ] **Step 8: 提交**

```bash
git add frontend/src/types/trajectory.ts frontend/src/api/trajectory.ts frontend/src/components/Trajectory/ frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json frontend/src/App.css
git commit -m "feat: 前端新增轨迹页面组件"
```

---

### Task 6: 导航入口、App 接线与聊天页跳转按钮

**Files:**
- Modify: `frontend/src/components/Layout/Header.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Chat/ChatWindow.tsx`
- Modify: `frontend/src/components/Layout/Header.test.tsx`
- Modify: `frontend/src/components/Chat/ChatWindow.test.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/i18n/locales/zh-CN.json`、`en.json`

**Interfaces:**
- Consumes: `TrajectoryPage`（Task 5）；`ChatWindow` props 新增 `onViewTrajectory?: (id: string) => void`。
- Produces: 导航 `Page` 类型新增 `'trajectory'`；`App.tsx` 状态 `trajectorySessionId` 与回调 `handleViewTrajectory`。

- [ ] **Step 1: 写失败测试**

修改 `frontend/src/components/Layout/Header.test.tsx`：在现有头部渲染断言基础上追加：

```ts
it('renders trajectory nav entry', () => {
  render(<Header activePage="chat" onNavigate={vi.fn()} />)
  expect(screen.getByTestId('nav-trajectory')).toBeInTheDocument()
})
```

修改 `frontend/src/components/Chat/ChatWindow.test.tsx`：沿用该文件既有的 ws mock 结构，新增用例：

```ts
it('view trajectory button navigates with current conversation', () => {
  const onViewTrajectory = vi.fn()
  render(<ChatWindow {...baseProps} conversationId="conv-1" onViewTrajectory={onViewTrajectory} />)
  fireEvent.click(screen.getByTestId('view-trajectory'))
  expect(onViewTrajectory).toHaveBeenCalledWith('conv-1')
})
```

（具体 mock 与既有用例保持一致；若既有文件无 `baseProps`，则按该文件已有模式构造。）

修改 `frontend/src/App.test.tsx`：追加：

```ts
it('switches to trajectory page from nav', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }))
  render(<App />)
  fireEvent.click(screen.getByTestId('nav-trajectory'))
  expect(await screen.findByTestId('trajectory-page')).toBeInTheDocument()
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: 新增 3 个用例 FAIL（`nav-trajectory` / `view-trajectory` / `trajectory-page` 不存在）

- [ ] **Step 3: 修改 Header**

`frontend/src/components/Layout/Header.tsx`：

- 导入 `Footprints`：`import { ..., Footprints, ... } from 'lucide-react'`
- `Page` 类型追加 `| 'trajectory'`
- `navKeys` 数组在 `'chat'` 之后插入 `'trajectory'`
- `NAV_ICONS` 追加：`trajectory: Footprints`
- `NAV_I18N` 追加：`trajectory: 'nav.trajectory'`

- [ ] **Step 4: 添加导航文案**

`zh-CN.json` `nav` 段（`"chat": "聊天"` 前后均可）追加 `"trajectory": "轨迹",`；`en.json` 对应 `"trajectory": "Trajectory",`。

`zh-CN.json` `"chat"` 段追加（`chat` 段内任意位置）：
`"viewTrajectory": "查看轨迹",`
`"viewTrajectoryTitle": "在轨迹页审计该会话",`
`en.json` 对应：
`"viewTrajectory": "View trajectory",`
`"viewTrajectoryTitle": "Audit this conversation in the trajectory page",`

- [ ] **Step 5: 修改 App.tsx 接线**

- 导入：`import { TrajectoryPage } from './components/Trajectory/TrajectoryPage'`
- state：`const [trajectorySessionId, setTrajectorySessionId] = useState<string | undefined>()`
- 回调：

```tsx
const handleViewTrajectory = useCallback(() => {
  setTrajectorySessionId(selectedId)
  setActivePage('trajectory')
}, [selectedId])
```

- `renderPage` switch 新增：

```tsx
      case 'trajectory':
        return <TrajectoryPage initialConversationId={trajectorySessionId} />
```

- `ChatWindow` 传参追加：`onViewTrajectory={handleViewTrajectory}`

- [ ] **Step 6: 修改 ChatWindow**

`ChatWindowProps` 追加 `onViewTrajectory?: (id: string) => void`；解构时取出 `onViewTrajectory`。

在 `.chat-status` 的流式开关之后、`ConversationModelSelector` 之前插入（需导入 `Route` 图标）：

```tsx
        {conversationId && onViewTrajectory && (
          <button
            type="button"
            className="clear-context-btn"
            data-testid="view-trajectory"
            title={t('chat.viewTrajectoryTitle')}
            aria-label={t('chat.viewTrajectoryTitle')}
            onClick={() => onViewTrajectory(conversationId)}
          >
            <Route size={14} />
            <span>{t('chat.viewTrajectory')}</span>
          </button>
        )}
```

- [ ] **Step 7: 运行测试与构建确认通过**

Run: `cd frontend && npm test`
Expected: 包括新增 3 个用例在内全部 PASS

Run: `cd frontend && npm run build`
Expected: 通过

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/Layout/Header.tsx frontend/src/components/Layout/Header.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/components/Chat/ChatWindow.tsx frontend/src/components/Chat/ChatWindow.test.tsx frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json
git commit -m "feat: 接入导航与聊天页轨迹入口"
```

---

### Task 7: 集成验证

**Files:** 无新增（验证 + 按需修复）

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest -q`
Expected: 全部通过（含新 tests/test_trajectory 与 tests/test_api/test_trajectory.py）

- [ ] **Step 2: 后端 lint**

Run: `ruff check src tests && ruff format --check src tests`
Expected: 无错误

- [ ] **Step 3: 前端测试与构建**

Run: `cd frontend && npm test && npm run build`
Expected: 全绿、构建通过

- [ ] **Step 4: 手工验证清单**

1. 启动服务（`python start_dev.py` 或既有开发启动方式），打开 WEB。
2. 顶部导航出现“轨迹”标签；点击进入轨迹页，默认显示“请选择要查看的会话”，滚动条下方为空（无任何轨迹请求）。
3. 在聊天页选择会话并发送一条会触发工具调用的消息（如“搜索 天气”），确认回复正常（写入失败不阻塞验证）。
4. 用 sqlite 查询确认存在 `trajectory_events` 行（`sqlite3 thumbelina.db "select count(*) from trajectory_events;"`）> 0。
5. 轨迹页选择该会话：出现轮次卡片，最新轮次在最上；轮次内顺序为 user → context → tool_call → tool_result → assistant；工具调用/上下文默认折叠，点击展开可见 JSON。
6. 旧会话（改造前创建的）选择后显示 `legacy` 提示与已有消息，无工具调用/上下文内容。
7. 聊天页数据条点击“查看轨迹”：跳转轨迹页并自动过滤当前会话；在轨迹页切换其他会话下拉仍然生效。
8. “加载更多”在轮次超过 20 时会话正常追加下一页。
9. 访问不存在的会话 ID：`curl http://localhost:8000/api/v1/trajectory/nonexistent` 返回 404。

- [ ] **Step 5: 自审与最终提交**

对照 `docs/superpowers/specs/2026-08-22-trajectory-page-design.md` §3-§7 核对逐项完成；检查 git 状态只包含本计划涉及文件后：

```bash
git status --short
git add <上述涉及文件（如有遗漏）>
git commit -m "chore: 轨迹页面集成收尾"  # 若无遗漏则跳过
```