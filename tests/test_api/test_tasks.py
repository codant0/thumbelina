"""API tests for the task endpoints (design §8.1) and app assembly (§5.3).

The shared conftest ``client`` fixture runs the real lifespan with a mocked
agent/repository; the lifespan therefore wires a scheduler whose store sits
on a ``MagicMock`` engine.  Tests that exercise real behaviour re-inject
genuine components (real sqlite engine + ``TaskStore``/``EventBus``/
``TaskScheduler``/``Heartbeat``) into ``app.state`` — the routes read those
attributes.  None of the injected components start background loops, so
teardown needs no cross-thread bookkeeping.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.config import load_config
from thumbelina.config.models import (
    AppConfig,
    LLMConfig,
    RepositoryConfig,
    SchedulerConfig,
)

if TYPE_CHECKING:
    from thumbelina.scheduler.events import EventBus
    from thumbelina.scheduler.heartbeat import Heartbeat
    from thumbelina.scheduler.models import ScheduledTask, TaskEvent
    from thumbelina.scheduler.scheduler import TaskScheduler
    from thumbelina.scheduler.store import TaskStore

# Imported first among local modules so that — when this file runs
# standalone — the app import chain registers the scheduler ORM on
# ``Base.metadata`` before any ``init_db`` call (T4 ruling).
import thumbelina.api.app  # noqa: F401

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _make_components() -> tuple[TaskStore, EventBus, TaskScheduler, Heartbeat]:
    """Build real scheduler components on a throwaway in-memory database."""
    from thumbelina.repository.db import create_db_engine, init_db
    from thumbelina.scheduler.events import EventBus
    from thumbelina.scheduler.heartbeat import Heartbeat
    from thumbelina.scheduler.scheduler import TaskScheduler
    from thumbelina.scheduler.store import TaskStore

    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)  # creates scheduled_tasks + task_events
    store = TaskStore(engine)
    bus = EventBus()
    scheduler = TaskScheduler(store=store, bus=bus, config=SchedulerConfig())
    heartbeat = Heartbeat(scheduler, bus, SchedulerConfig())
    return store, bus, scheduler, heartbeat


@pytest.fixture
def task_client(client: TestClient) -> TestClient:
    """``client`` with real scheduler components injected into app.state."""
    store, bus, scheduler, heartbeat = _make_components()
    client.app.state.task_store = store
    client.app.state.task_event_bus = bus
    client.app.state.task_scheduler = scheduler
    client.app.state.task_heartbeat = heartbeat
    client.app.state.task_dispatcher = None
    return client


@pytest.fixture
def disabled_client(mock_agent, mock_repository) -> TestClient:
    """Client whose config disables the scheduler entirely (design §10)."""

    config = AppConfig(
        llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
        repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        scheduler=SchedulerConfig(enabled=False),
    )
    with (
        patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
        patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
        patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
    ):
        from thumbelina.api.app import create_app

        app = create_app(config)
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# config (design §10)
# ---------------------------------------------------------------------------


def test_scheduler_config_defaults() -> None:
    cfg = SchedulerConfig()
    assert cfg.enabled is True
    assert cfg.heartbeat_interval_seconds == 30
    assert cfg.missed_policy == "mark"
    assert cfg.missed_grace_minutes == 5
    assert cfg.stale_running_minutes == 10
    assert cfg.event_retention == 500
    assert cfg.default_channel == "web"
    assert cfg.prompt_timeout_seconds == 300


def test_scheduler_config_yaml_override(tmp_path) -> None:
    yaml_file = tmp_path / "thumbelina.yaml"
    yaml_file.write_text(
        "scheduler:\n  enabled: false\n  missed_policy: run\n  heartbeat_interval_seconds: 15\n",
        encoding="utf-8",
    )
    config = load_config(str(yaml_file))
    assert config.scheduler.enabled is False
    assert config.scheduler.missed_policy == "run"
    assert config.scheduler.heartbeat_interval_seconds == 15
    # Unspecified fields keep their defaults.
    assert config.scheduler.default_channel == "web"
    assert config.scheduler.event_retention == 500


# ---------------------------------------------------------------------------
# ORM registration ordering (T4 ruling): init_db must create both tables
# ---------------------------------------------------------------------------


def test_app_import_registers_scheduler_orm() -> None:
    # thumbelina.api.app is imported at the top of this module; its import
    # chain must have registered the scheduler ORM on the shared Base.
    from thumbelina.repository.models import Base

    assert "thumbelina.scheduler.store" in sys.modules
    assert "scheduled_tasks" in Base.metadata.tables
    assert "task_events" in Base.metadata.tables


def test_init_db_creates_task_tables(tmp_path) -> None:
    from sqlalchemy import inspect

    from thumbelina.repository.db import create_db_engine, init_db

    engine = create_db_engine(f"sqlite:///{tmp_path}/tasks.db")
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    assert "scheduled_tasks" in tables
    assert "task_events" in tables


# ---------------------------------------------------------------------------
# GET /tasks — legacy 4 keys verbatim + new fields (design §8.1)
# ---------------------------------------------------------------------------


async def test_list_tasks_returns_legacy_and_new_fields(task_client: TestClient) -> None:
    from thumbelina.scheduler.models import DeliveryChannel, ScheduledTask, TriggerKind

    scheduler: TaskScheduler = task_client.app.state.task_scheduler
    await scheduler.add_task(
        ScheduledTask(
            description="once job",
            trigger=TriggerKind.ONCE,
            scheduled_time=datetime(2027, 1, 1, 10, 0, 0),
            channel=DeliveryChannel.WEB,
            content="hello",
            mode="prompt",  # §5.4: web 创建任务默认 prompt(直接构造仍默认 notify,故显式传)
            source="web",
        )
    )

    resp = task_client.get("/api/v1/tasks")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    # Legacy four keys, verbatim.
    assert set(item) >= {"id", "description", "scheduled_time", "status"}
    assert item["description"] == "once job"
    assert item["scheduled_time"] == "2027-01-01T10:00:00"
    assert item["status"] == "pending"
    # New fields.
    assert item["trigger"] == "once"
    assert item["cron"] is None
    assert item["next_run"] is None
    assert item["last_run"] is None
    assert item["channel"] == "web"
    assert item["content"] == "hello"
    assert item["mode"] == "prompt"  # §5.4: mode 默认 prompt 的行为变更
    assert item["source"] == "web"
    assert item["error"] is None
    assert item["conversation_id"] is None


async def test_list_tasks_cron_scheduled_time_null(task_client: TestClient) -> None:
    from thumbelina.scheduler.models import ScheduledTask, TriggerKind

    scheduler: TaskScheduler = task_client.app.state.task_scheduler
    await scheduler.add_task(
        ScheduledTask(
            description="cron job",
            trigger=TriggerKind.CRON,
            cron_expr="*/5 * * * *",
            scheduled_time=None,
        )
    )

    items = task_client.get("/api/v1/tasks").json()
    assert len(items) == 1
    item = items[0]
    assert item["trigger"] == "cron"
    assert item["cron"] == "*/5 * * * *"
    assert item["scheduled_time"] is None  # cron tasks may have null scheduled_time
    assert item["next_run"] is not None  # add_task computed the next fire time


def test_list_tasks_empty_when_scheduler_unavailable(client: TestClient) -> None:
    client.app.state.task_scheduler = None
    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /tasks — creation + validation (design §8.1, T5 ruling)
# ---------------------------------------------------------------------------


async def test_create_once_task_201(task_client: TestClient) -> None:
    client = task_client
    resp = client.post(
        "/api/v1/tasks",
        json={
            "description": "remind me",
            "trigger": "once",
            "scheduled_time": "2027-01-01T08:30:00",
            "channel": "web",
            "content": "custom content",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["description"] == "remind me"
    assert body["trigger"] == "once"
    assert body["scheduled_time"] == "2027-01-01T08:30:00"
    assert body["status"] == "pending"
    assert body["channel"] == "web"
    assert body["content"] == "custom content"
    assert body["source"] == "web"

    # The task is live on the scheduler and persisted through the store.
    scheduler: TaskScheduler = client.app.state.task_scheduler
    task = await scheduler.get_task(body["id"])
    assert task is not None
    assert task.source == "web"
    stored: TaskStore = client.app.state.task_store
    stored_task = await stored.get_task(body["id"])
    assert stored_task is not None
    assert stored_task.description == "remind me"


async def test_create_once_task_tz_aware_time_normalized_to_local_naive(
    task_client: TestClient,
) -> None:
    """A ``Z``-suffixed timestamp (JS ``toISOString()``) must come back naive.

    The scheduler compares against naive ``datetime.now()``; an aware value
    would raise ``TypeError`` inside ``get_due_tasks`` and kill the poll
    loop (C1).  The API normalizes tz-aware input to local naive time.
    """
    client = task_client
    resp = client.post(
        "/api/v1/tasks",
        json={
            "description": "tz once",
            "trigger": "once",
            "scheduled_time": "2027-01-01T08:30:00Z",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scheduled_time"] is not None
    assert not body["scheduled_time"].endswith("+00:00")
    expected = (
        datetime.fromisoformat("2027-01-01T08:30:00+00:00")
        .astimezone()
        .replace(tzinfo=None)
        .isoformat()
    )
    assert body["scheduled_time"] == expected

    # The stored task is naive and the scheduler's naive comparison works.
    scheduler: TaskScheduler = client.app.state.task_scheduler
    task = await scheduler.get_task(body["id"])
    assert task is not None
    assert task.scheduled_time is not None
    assert task.scheduled_time.tzinfo is None
    await scheduler.get_due_tasks()  # would raise TypeError on an aware value

    items = client.get("/api/v1/tasks").json()
    created = next(i for i in items if i["id"] == body["id"])
    assert not created["scheduled_time"].endswith("+00:00")


async def test_create_once_task_content_defaults_to_description(
    task_client: TestClient,
) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={"description": "standup", "trigger": "once", "scheduled_time": "2027-01-01T09:00:00"},
    )
    assert resp.status_code == 201
    assert resp.json()["content"] == "standup"


async def test_create_cron_task_201(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={"description": "loop", "trigger": "cron", "cron": "*/5 * * * *"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["trigger"] == "cron"
    assert body["cron"] == "*/5 * * * *"
    assert body["next_run"] is not None
    assert body["scheduled_time"] is None
    assert body["channel"] == "web"  # SchedulerConfig.default_channel


def test_create_once_missing_scheduled_time_422(task_client: TestClient) -> None:
    resp = task_client.post("/api/v1/tasks", json={"description": "x", "trigger": "once"})
    assert resp.status_code == 422


def test_create_once_invalid_scheduled_time_422(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={
            "description": "x",
            "trigger": "once",
            "scheduled_time": "not-a-date",
        },
    )
    assert resp.status_code == 422


def test_create_cron_invalid_expression_422(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={"description": "x", "trigger": "cron", "cron": "not a cron"},
    )
    assert resp.status_code == 422
    assert "Invalid cron expression" in resp.json()["detail"]


def test_create_cron_missing_expression_422(task_client: TestClient) -> None:
    resp = task_client.post("/api/v1/tasks", json={"description": "x", "trigger": "cron"})
    assert resp.status_code == 422


def test_create_invalid_channel_422(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={
            "description": "x",
            "trigger": "once",
            "scheduled_time": "2027-01-01T09:00:00",
            "channel": "email",
        },
    )
    assert resp.status_code == 422


def test_create_blank_description_422(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={"description": "   ", "trigger": "once", "scheduled_time": "2027-01-01T09:00:00"},
    )
    assert resp.status_code == 422


def test_create_scheduler_unavailable_503(client: TestClient) -> None:
    client.app.state.task_scheduler = None
    resp = client.post("/api/v1/tasks", json={"description": "x"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /tasks — mode 默认 prompt / 显式 notify / conversation_id 透传 (§5.4)
# ---------------------------------------------------------------------------


def test_create_task_mode_field_describes_both_modes(task_client: TestClient) -> None:
    """T13 / Task 12 Minor 3: the API mode field's description names both
    prompt and notify modes (the default is prompt, per §5.4)."""
    openapi = task_client.app.openapi()
    post = openapi["paths"]["/api/v1/tasks"]["post"]
    schema_ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = openapi["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
    mode = schema["properties"]["mode"]
    assert mode["default"] == "prompt"
    assert mode["enum"] == ["prompt", "notify"]
    description = mode.get("description", "")
    assert "prompt" in description and "notify" in description


async def test_create_task_defaults_to_prompt_mode(task_client: TestClient) -> None:
    """mode 缺省为 prompt(plan-mandated 行为变更,设计 §5.4:定时任务默认'干活')。"""
    resp = task_client.post(
        "/api/v1/tasks",
        json={
            "description": "default mode",
            "trigger": "once",
            "scheduled_time": "2027-01-01T09:00:00",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["mode"] == "prompt"
    scheduler: TaskScheduler = task_client.app.state.task_scheduler
    task = await scheduler.get_task(body["id"])
    assert task is not None and task.mode == "prompt"


async def test_create_task_explicit_notify_mode(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={
            "description": "explicit notify",
            "trigger": "once",
            "scheduled_time": "2027-01-01T09:00:00",
            "mode": "notify",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["mode"] == "notify"
    scheduler: TaskScheduler = task_client.app.state.task_scheduler
    task = await scheduler.get_task(body["id"])
    assert task is not None and task.mode == "notify"


async def test_create_cron_task_defaults_to_prompt_mode(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={"description": "loop", "trigger": "cron", "cron": "*/5 * * * *"},
    )
    assert resp.status_code == 201
    assert resp.json()["mode"] == "prompt"


def test_create_task_invalid_mode_422(task_client: TestClient) -> None:
    resp = task_client.post(
        "/api/v1/tasks",
        json={
            "description": "x",
            "trigger": "once",
            "scheduled_time": "2027-01-01T09:00:00",
            "mode": "bogus",
        },
    )
    assert resp.status_code == 422


async def test_create_task_conversation_id_passthrough(task_client: TestClient) -> None:
    """conversation_id 直传:落库的 ScheduledTask 与序列化响应均携带。"""
    resp = task_client.post(
        "/api/v1/tasks",
        json={
            "description": "with conversation",
            "trigger": "once",
            "scheduled_time": "2027-01-01T09:00:00",
            "conversation_id": "conv-9",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["conversation_id"] == "conv-9"
    scheduler: TaskScheduler = task_client.app.state.task_scheduler
    task = await scheduler.get_task(body["id"])
    assert task is not None and task.conversation_id == "conv-9"
    stored: TaskStore = task_client.app.state.task_store
    stored_task = await stored.get_task(body["id"])
    assert stored_task is not None and stored_task.conversation_id == "conv-9"


# ---------------------------------------------------------------------------
# POST /tasks/{id}/pause | resume — state machine (404/409)
# ---------------------------------------------------------------------------


async def test_pause_resume_cycle(task_client: TestClient) -> None:
    client = task_client
    resp = client.post(
        "/api/v1/tasks",
        json={"description": "loop", "trigger": "cron", "cron": "*/5 * * * *"},
    )
    task_id = resp.json()["id"]

    paused = client.post(f"/api/v1/tasks/{task_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    # Pausing a PAUSED task → 409.
    assert client.post(f"/api/v1/tasks/{task_id}/pause").status_code == 409

    resumed = client.post(f"/api/v1/tasks/{task_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "pending"

    # Resuming a PENDING task → 409.
    assert client.post(f"/api/v1/tasks/{task_id}/resume").status_code == 409


async def test_pause_once_task_409(task_client: TestClient) -> None:
    from thumbelina.scheduler.models import DeliveryChannel, ScheduledTask, TriggerKind

    scheduler: TaskScheduler = task_client.app.state.task_scheduler
    task = ScheduledTask(
        description="once",
        trigger=TriggerKind.ONCE,
        scheduled_time=datetime(2027, 1, 1, 10, 0, 0),
        channel=DeliveryChannel.WEB,
    )
    await scheduler.add_task(task)
    resp = task_client.post(f"/api/v1/tasks/{task.id}/pause")
    assert resp.status_code == 409


def test_pause_unknown_task_404(task_client: TestClient) -> None:
    resp = task_client.post("/api/v1/tasks/no-such-id/pause")
    assert resp.status_code == 404


def test_resume_unknown_task_404(task_client: TestClient) -> None:
    resp = task_client.post("/api/v1/tasks/no-such-id/resume")
    assert resp.status_code == 404


def test_pause_scheduler_unavailable_404(client: TestClient) -> None:
    client.app.state.task_scheduler = None
    assert client.post("/api/v1/tasks/no-such-id/pause").status_code == 404


# ---------------------------------------------------------------------------
# GET /tasks/events — newest-first event log (design §8.1)
# ---------------------------------------------------------------------------


async def _append_events(store: TaskStore, count: int = 3) -> list[TaskEvent]:
    from thumbelina.scheduler.models import DeliveryChannel, TaskEvent, TaskEventType, TriggerKind

    base = datetime.now() - timedelta(hours=1)
    events: list[TaskEvent] = []
    for i in range(count):
        event = TaskEvent(
            type=TaskEventType.DUE,
            task_id="t-events",
            fired_at=base + timedelta(minutes=i),
            trigger=TriggerKind.ONCE,
            channel=DeliveryChannel.WEB,
            content=f"evt-{i}",
            payload={"seq": i},
        )
        await store.append_event(event)
        events.append(event)
    return events


async def test_events_newest_first(task_client: TestClient) -> None:
    store: TaskStore = task_client.app.state.task_store
    events = await _append_events(store, 3)

    resp = task_client.get("/api/v1/tasks/events")
    assert resp.status_code == 200
    items = resp.json()
    assert [i["content"] for i in items] == ["evt-2", "evt-1", "evt-0"]
    first = items[0]
    assert set(first) == {
        "id",
        "type",
        "task_id",
        "fired_at",
        "trigger",
        "channel",
        "content",
        "payload",
    }
    assert first["id"] == events[2].id
    assert first["type"] == "task.due"
    assert first["payload"] == {"seq": 2}


async def test_events_limit_and_clamp(task_client: TestClient) -> None:
    store: TaskStore = task_client.app.state.task_store
    await _append_events(store, 3)

    limited = task_client.get("/api/v1/tasks/events", params={"limit": 2}).json()
    assert [i["content"] for i in limited] == ["evt-2", "evt-1"]

    # limit is clamped into 1..200 (no 422 for out-of-range values).
    zero = task_client.get("/api/v1/tasks/events", params={"limit": 0})
    assert zero.status_code == 200
    assert len(zero.json()) == 1

    huge = task_client.get("/api/v1/tasks/events", params={"limit": 100000})
    assert huge.status_code == 200
    assert len(huge.json()) == 3


def test_events_store_unavailable_503(task_client: TestClient) -> None:
    task_client.app.state.task_store = None
    resp = task_client.get("/api/v1/tasks/events")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /tasks/scheduler/status (design §8.1)
# ---------------------------------------------------------------------------


def test_scheduler_status_200(task_client: TestClient) -> None:
    resp = task_client.get("/api/v1/tasks/scheduler/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"running", "last_heartbeat_at", "task_counts", "checks"}
    assert body["running"] is False  # heartbeat not started in tests
    assert body["last_heartbeat_at"] is None
    assert body["task_counts"] == {}
    assert set(body["checks"]) == {
        "poll_loop",
        "stale_running",
        "cron_next_run",
        "once_overdue",
        "event_prune",
    }


def test_scheduler_status_503(client: TestClient) -> None:
    client.app.state.task_heartbeat = None
    resp = client.get("/api/v1/tasks/scheduler/status")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# scheduler.enabled = False → whole assembly skipped (design §10)
# ---------------------------------------------------------------------------


def test_disabled_scheduler_degrades(disabled_client: TestClient) -> None:
    assert disabled_client.app.state.task_scheduler is None
    assert disabled_client.app.state.task_store is None
    assert disabled_client.app.state.task_event_bus is None
    assert disabled_client.app.state.task_dispatcher is None
    assert disabled_client.app.state.task_heartbeat is None

    assert disabled_client.get("/api/v1/tasks").json() == []
    assert disabled_client.get("/api/v1/tasks/scheduler/status").status_code == 503
    assert disabled_client.get("/api/v1/tasks/events").status_code == 503
    assert disabled_client.post("/api/v1/tasks", json={"description": "x"}).status_code == 503


# ---------------------------------------------------------------------------
# WebPushHook (T7 ruling): canonical frame + legacy compat frame
# ---------------------------------------------------------------------------


def _make_event(event_type) -> TaskEvent:
    from thumbelina.scheduler.models import DeliveryChannel, TaskEvent, TriggerKind

    return TaskEvent(
        type=event_type,
        task_id="t-push",
        trigger=TriggerKind.ONCE,
        channel=DeliveryChannel.WEB,
        content="hello",
        payload={"k": "v"},
    )


async def test_web_push_hook_broadcasts_task_event_frame(monkeypatch) -> None:
    import thumbelina.api.app as app_module
    from thumbelina.notifications import NotificationManager
    from thumbelina.scheduler.models import TaskEventType

    frames: list[dict] = []

    async def _capture(message: dict) -> None:
        frames.append(message)

    monkeypatch.setattr(app_module, "broadcast_chat_message", _capture)
    hook = app_module._make_web_push_hook(NotificationManager())
    event = _make_event(TaskEventType.DUE)
    await hook(event)

    assert frames == [
        {
            "task_event": {
                "id": event.id,
                "type": "task.due",
                "task_id": "t-push",
                "fired_at": event.fired_at.isoformat(),
                "trigger": "once",
                "channel": "web",
                "content": "hello",
                "payload": {"k": "v"},
            }
        }
    ]


async def test_web_push_hook_compat_frame_on_completed(monkeypatch) -> None:
    import thumbelina.api.app as app_module
    from thumbelina.notifications import NotificationManager
    from thumbelina.scheduler.models import TaskEventType

    class _Recorder(NotificationManager):
        def __init__(self) -> None:
            super().__init__()
            self.sent: list[dict] = []

        async def broadcast(self, message: dict) -> int:  # type: ignore[override]
            self.sent.append(message)
            return len(self.sent)

    async def _capture(message: dict) -> None:
        return None

    monkeypatch.setattr(app_module, "broadcast_chat_message", _capture)
    recorder = _Recorder()
    hook = app_module._make_web_push_hook(recorder)

    await hook(_make_event(TaskEventType.DUE))
    assert recorder.sent == []  # compat frame only for task.completed

    await hook(_make_event(TaskEventType.COMPLETED))
    assert recorder.sent == [
        {"type": "task_completed", "task_id": "t-push", "description": "hello"}
    ]


async def test_web_push_hook_compat_frame_uses_task_description(monkeypatch) -> None:
    """Agent-created tasks carry description, not content — old frame behaviour."""
    import thumbelina.api.app as app_module
    from thumbelina.notifications import NotificationManager
    from thumbelina.scheduler.models import ScheduledTask, TaskEventType
    from thumbelina.scheduler.scheduler import TaskScheduler

    class _Recorder(NotificationManager):
        def __init__(self) -> None:
            super().__init__()
            self.sent: list[dict] = []

        async def broadcast(self, message: dict) -> int:  # type: ignore[override]
            self.sent.append(message)
            return len(self.sent)

    async def _capture(message: dict) -> None:
        return None

    monkeypatch.setattr(app_module, "broadcast_chat_message", _capture)
    scheduler = TaskScheduler()  # no store/bus: pure in-memory lookup
    task = ScheduledTask(description="the real description", content="")
    await scheduler.add_task(task)
    recorder = _Recorder()
    hook = app_module._make_web_push_hook(recorder, scheduler)

    completed = _make_event(TaskEventType.COMPLETED)
    completed.task_id = task.id
    completed.content = ""  # agent tasks leave content empty
    await hook(completed)

    assert recorder.sent == [
        {"type": "task_completed", "task_id": task.id, "description": "the real description"}
    ]


async def test_web_push_hook_swallows_errors(monkeypatch) -> None:
    import thumbelina.api.app as app_module
    from thumbelina.scheduler.models import TaskEventType

    async def _boom(message: dict) -> None:
        raise RuntimeError("socket gone")

    monkeypatch.setattr(app_module, "broadcast_chat_message", _boom)
    # notification_manager=None must not blow up either.
    hook = app_module._make_web_push_hook(None)
    await hook(_make_event(TaskEventType.COMPLETED))  # no exception escapes


async def test_lifespan_bus_has_hooks_wired(client: TestClient, monkeypatch) -> None:
    """The lifespan subscribes the event-log + web-push hooks to every event type."""
    import thumbelina.api.app as app_module
    from thumbelina.scheduler.models import TaskEventType

    frames: list[dict] = []

    async def _capture(message: dict) -> None:
        frames.append(message)

    monkeypatch.setattr(app_module, "broadcast_chat_message", _capture)
    bus: EventBus | None = client.app.state.task_event_bus
    assert bus is not None

    await bus.emit(_make_event(TaskEventType.CREATED))

    assert len(frames) == 1
    assert frames[0]["task_event"]["type"] == "task.created"


# ---------------------------------------------------------------------------
# T13: prompt 模式装配——run_prompt 闭包(会话归属/串行化/agent.clone().run/
# 对话框实时可见) + 事件流 result (§5.4)
# ---------------------------------------------------------------------------


class _FakeChannel:
    """Minimal Channel double recording send_message calls (T13)."""

    def __init__(self) -> None:
        self.last_user_id = "u-1"
        self.sent: list[tuple[str, str]] = []

    async def send_message(
        self,
        user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any]:
        self.sent.append((user_id, text))
        return {"ok": True}


def _prompt_task(**overrides: Any) -> ScheduledTask:
    """A minimal once prompt-mode task; overrides bypass enum typing on purpose."""
    from thumbelina.scheduler.models import ScheduledTask, TriggerKind

    values: dict[str, Any] = {
        "id": "prompt-assembly",
        "description": "assembly",
        "content": "do the thing",
        "mode": "prompt",
        "trigger": TriggerKind.ONCE,
    }
    values.update(overrides)
    return ScheduledTask(**values)


async def _capture_frames(monkeypatch) -> list[dict]:
    """Monkeypatch broadcast_chat_message to record frames; return the list."""
    import thumbelina.api.app as app_module

    frames: list[dict] = []

    async def _capture(message: dict) -> None:
        frames.append(message)

    monkeypatch.setattr(app_module, "broadcast_chat_message", _capture)
    return frames


async def test_prompt_runner_uses_task_conversation_when_it_exists(
    task_client: TestClient, monkeypatch
) -> None:
    """§5.4 step 1/3/4: a task with an existing conversation_id runs the agent
    on that conversation (clone().run(content)), and the scheduler
    channel_message frame carries source='scheduler' + the reply."""
    import thumbelina.api.app as app_module

    frames = await _capture_frames(monkeypatch)
    app = task_client.app
    agent = app.state.agent
    runner = app_module._make_prompt_runner(app, app.state.repository_manager)

    reply = await runner(_prompt_task(conversation_id="test-conv-id"))

    assert reply == "Agent response"
    agent.clone.assert_called_once()
    agent.run.assert_awaited_once_with("do the thing")
    assert agent.current_conversation_id == "test-conv-id"
    assert frames == [
        {
            "channel_message": {
                "channel": "scheduler",
                "conversation_id": "test-conv-id",
                "user_message": "do the thing",
                "response": "Agent response",
                "source": "scheduler",
            }
        }
    ]


async def test_prompt_runner_falls_back_to_dedicated_conversation_when_missing(
    task_client: TestClient, monkeypatch
) -> None:
    """§5.4 step 1: no conversation_id (or a non-existent one) falls back to
    the dedicated '定时任务' conversation, created lazily once and cached on
    app.state.scheduler_conversation_id."""
    import thumbelina.api.app as app_module

    frames = await _capture_frames(monkeypatch)
    app = task_client.app
    agent = app.state.agent
    repository = app.state.repository_manager
    runner = app_module._make_prompt_runner(app, repository)

    first = await runner(_prompt_task(id="prompt-fallback-1", content="first"))
    assert first == "Agent response"
    dedicated = app.state.scheduler_conversation_id
    assert dedicated is not None
    assert dedicated != "test-conv-id"
    assert agent.current_conversation_id == dedicated
    repository.create_conversation.assert_awaited_once()

    # A missing conversation_id also lands on the same dedicated conversation,
    # and the cached id is reused — no second create.
    repository.create_conversation.reset_mock()
    second = await runner(_prompt_task(id="prompt-fallback-2", content="second"))
    assert second == "Agent response"
    repository.create_conversation.assert_not_awaited()
    assert app.state.scheduler_conversation_id == dedicated
    assert agent.current_conversation_id == dedicated

    assert len(frames) == 2
    assert all(f["channel_message"]["source"] == "scheduler" for f in frames)
    assert frames[0]["channel_message"]["conversation_id"] == dedicated
    assert frames[1]["channel_message"]["conversation_id"] == dedicated


async def test_prompt_runner_nonexistent_conversation_falls_back(
    task_client: TestClient, monkeypatch
) -> None:
    """A conversation_id that names no existing conversation is treated like a
    missing one — the dedicated conversation is used (§5.4 step 1 '存在')."""
    import thumbelina.api.app as app_module

    frames = await _capture_frames(monkeypatch)
    app = task_client.app
    agent = app.state.agent
    runner = app_module._make_prompt_runner(app, app.state.repository_manager)

    await runner(_prompt_task(conversation_id="no-such-conv"))

    dedicated = app.state.scheduler_conversation_id
    assert dedicated is not None
    assert dedicated != "no-such-conv"
    assert agent.current_conversation_id == dedicated
    assert frames[0]["channel_message"]["conversation_id"] == dedicated


async def test_prompt_runner_concurrent_fires_create_dedicated_conversation_once(
    task_client: TestClient, monkeypatch
) -> None:
    """Minor-1 (review): two prompt tasks firing concurrently (same poll round)
    must not race the lazy dedicated-conversation check-and-create — exactly
    one ``create_conversation`` call, both tasks land on the same conversation.

    A slow ``create_conversation`` makes the race window observable: without
    the ``scheduler_conversation_lock`` guard both tasks would pass the
    ``is None`` check and each call ``create_conversation``.
    """
    import thumbelina.api.app as app_module

    frames = await _capture_frames(monkeypatch)
    app = task_client.app
    agent = app.state.agent
    repository = app.state.repository_manager
    runner = app_module._make_prompt_runner(app, repository)

    release = asyncio.Event()

    async def _slow_create(*args, **kwargs) -> str:
        await release.wait()
        return "dedicated-conv-race"

    repository.create_conversation.side_effect = _slow_create

    first = asyncio.create_task(runner(_prompt_task(id="prompt-race-1", content="first")))
    second = asyncio.create_task(runner(_prompt_task(id="prompt-race-2", content="second")))
    await asyncio.sleep(0.05)  # both enter _run_prompt; one holds the lock
    release.set()
    await asyncio.gather(first, second)

    repository.create_conversation.assert_awaited_once()
    dedicated = app.state.scheduler_conversation_id
    assert dedicated == "dedicated-conv-race"
    assert agent.current_conversation_id == dedicated
    assert len(frames) == 2
    assert all(f["channel_message"]["conversation_id"] == dedicated for f in frames)


async def _wait_for_task_status(
    scheduler: TaskScheduler, task_id: str, status: Any
) -> ScheduledTask:
    """Poll until the task reaches ``status`` (bounded)."""
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        task = await scheduler.get_task(task_id)
        if task is not None and task.status == status:
            return task
        if asyncio.get_running_loop().time() > deadline:
            seen = task.status.value if task is not None else "missing"
            raise AssertionError(f"task {task_id} never reached {status} (saw {seen})")
        await asyncio.sleep(0.01)


async def test_prompt_task_full_chain_via_dispatcher_and_runner(
    task_client: TestClient, monkeypatch
) -> None:
    """End-to-end §5.4 chain: prompt wechat task fires → scheduler background
    execution → dispatcher.on_prompt_task → run_prompt closure (clone().run +
    scheduler channel_message frame) → wechat channel copy gets the REPLY →
    COMPLETED payload.result carries the reply."""
    import thumbelina.api.app as app_module
    from thumbelina.scheduler.dispatcher import DeliveryDispatcher
    from thumbelina.scheduler.models import DeliveryChannel, TaskEventType, TaskStatus

    frames = await _capture_frames(monkeypatch)
    app = task_client.app
    scheduler: TaskScheduler = app.state.task_scheduler
    agent = app.state.agent

    channel = _FakeChannel()
    runner = app_module._make_prompt_runner(app, app.state.repository_manager)
    dispatcher = DeliveryDispatcher(
        channels={"wechat": channel},
        bus=app.state.task_event_bus,
        prompt_runner=runner,
    )
    # Register the task BEFORE starting the loop: an in-memory StaticPool
    # engine shares one sqlite connection across ``asyncio.to_thread``
    # workers, so a poll round firing while add_task's persist is still in
    # flight corrupts that shared connection (sqlite InterfaceError).  The
    # production engine (file-backed, pooled) does not have this artifact.
    task = _prompt_task(
        id="chain-once",
        channel=DeliveryChannel.WECHAT,
        scheduled_time=datetime.now() - timedelta(hours=1),
    )
    await scheduler.add_task(task)
    # Mirror the real lifespan wiring before events flow: the event-log hook
    # must be subscribed to the injected bus for events to land in the store.
    store: TaskStore = app.state.task_store
    bus = app.state.task_event_bus
    assert bus is not None
    for event_type in TaskEventType:
        bus.subscribe(event_type, app_module._make_event_log_hook(store))
    await scheduler.start(
        on_due_task=dispatcher.on_due_task,
        on_prompt_task=dispatcher.on_prompt_task,
    )
    try:
        settled = await _wait_for_task_status(scheduler, "chain-once", TaskStatus.COMPLETED)
    finally:
        await scheduler.stop()

    assert settled.status is TaskStatus.COMPLETED
    # clone().run called with the task content; dedicated conversation used.
    agent.clone.assert_called_once()
    agent.run.assert_awaited_once_with("do the thing")
    assert agent.current_conversation_id == app.state.scheduler_conversation_id
    # Realtime dialog frame: source=scheduler + reply.
    assert frames and frames[0]["channel_message"]["source"] == "scheduler"
    assert frames[0]["channel_message"]["response"] == "Agent response"
    assert frames[0]["channel_message"]["conversation_id"] == app.state.scheduler_conversation_id
    # Channel copy got the REPLY (not the content), and only once.
    assert channel.sent == [("u-1", "Agent response")]
    # The COMPLETED event payload.result carries the reply.
    events = await store.list_events(limit=10)
    completed = [e for e in events if e.type is TaskEventType.COMPLETED]
    assert len(completed) == 1
    assert completed[0].payload["result"] == "Agent response"
