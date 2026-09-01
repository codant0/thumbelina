"""Tests for the scheduler persistence layer (design §7.1).

Every test uses a tmp-path sqlite *file* database (never ``:memory:``,
whose pool semantics hide cross-connection bugs) with tables created by
``Base.metadata.create_all`` — the same entry point ``init_db`` uses in
production.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import insert
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from thumbelina.repository.db import create_db_engine
from thumbelina.repository.models import Base
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    TriggerKind,
)
from thumbelina.scheduler.store import TaskEventRecord, TaskStore

NOW = datetime(2026, 8, 30, 12, 0, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """File-backed sqlite engine with both scheduler tables created."""
    eng = create_db_engine(f"sqlite:///{tmp_path / 'scheduler.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def store(engine: Engine) -> TaskStore:
    return TaskStore(engine)


def _full_task() -> ScheduledTask:
    """A task with every one of the 18 dataclass fields set explicitly."""
    return ScheduledTask(
        id="task-cron-1",
        description="Every morning briefing",
        trigger=TriggerKind.CRON,
        cron_expr="0 9 * * *",
        scheduled_time=datetime(2026, 8, 29, 9, 0, 0),
        next_run=datetime(2026, 8, 31, 9, 0, 0),
        last_run=datetime(2026, 8, 30, 9, 0, 0),
        status=TaskStatus.PENDING,
        channel=DeliveryChannel.WECHAT,
        content="早安简报已生成",
        mode="notify",
        condition="file_changed:/tmp/data.csv",
        result="last result",
        error=None,
        source="web",
        conversation_id="conv-42",
        created_at=datetime(2026, 8, 28, 8, 0, 0, 123456),
        updated_at=datetime(2026, 8, 30, 9, 0, 5, 654321),
    )


def _task(task_id: str, **overrides: object) -> ScheduledTask:
    """Minimal once task at ``NOW - 1min``, overridable field by field."""
    fields: dict[str, object] = {
        "id": task_id,
        "description": f"task {task_id}",
        "scheduled_time": NOW - timedelta(minutes=1),
    }
    fields.update(overrides)
    return ScheduledTask(**fields)  # type: ignore[arg-type]


def _event(
    event_id: str, task_id: str, fired_at: datetime, trigger: TriggerKind = TriggerKind.ONCE
) -> TaskEvent:
    return TaskEvent(
        id=event_id,
        type=TaskEventType.COMPLETED,
        task_id=task_id,
        fired_at=fired_at,
        trigger=trigger,
        channel=DeliveryChannel.WEB,
        content="早安简报已生成",
        payload={"result": "ok", "nested": {"a": 1}, "scheduled_for": "2026-08-30T09:00:00"},
    )


class TestTaskRoundTrip:
    """upsert_task + get_task preserve all 18 ScheduledTask fields."""

    async def test_all_fields_round_trip(self, store: TaskStore) -> None:
        task = _full_task()

        await store.upsert_task(task)
        loaded = await store.get_task("task-cron-1")

        assert loaded is not None
        assert loaded == task

    async def test_upsert_updates_existing_row(self, store: TaskStore) -> None:
        task = _full_task()
        await store.upsert_task(task)

        task.status = TaskStatus.COMPLETED
        task.next_run = None
        task.last_run = NOW
        task.error = None
        task.result = "done"
        await store.upsert_task(task)

        loaded = await store.get_task("task-cron-1")
        assert loaded == task

        rows = await store.list_tasks()
        assert len(rows) == 1  # upsert, not duplicate insert

    async def test_get_missing_task_returns_none(self, store: TaskStore) -> None:
        assert await store.get_task("nope") is None

    async def test_list_tasks_returns_all(self, store: TaskStore) -> None:
        await store.upsert_task(_task("a"))
        await store.upsert_task(_task("b"))

        rows = await store.list_tasks()
        assert {t.id for t in rows} == {"a", "b"}

    async def test_delete_task_removes_row_and_is_idempotent(self, store: TaskStore) -> None:
        await store.upsert_task(_task("a"))

        await store.delete_task("a")
        assert await store.get_task("a") is None
        await store.delete_task("a")  # missing id: no-op, no raise


class TestListDue:
    """list_due returns due PENDING tasks only (design §4 scheduling rule)."""

    async def test_due_pending_once_and_cron_returned_others_excluded(
        self, store: TaskStore
    ) -> None:
        await store.upsert_task(_task("due-once"))  # ONCE, now-1min, PENDING
        await store.upsert_task(
            _task(
                "due-cron",
                trigger=TriggerKind.CRON,
                cron_expr="*/5 * * * *",
                scheduled_time=None,
                next_run=NOW - timedelta(minutes=1),
            )
        )
        await store.upsert_task(_task("future-once", scheduled_time=NOW + timedelta(hours=1)))
        await store.upsert_task(
            _task(
                "future-cron",
                trigger=TriggerKind.CRON,
                cron_expr="*/5 * * * *",
                scheduled_time=None,
                next_run=NOW + timedelta(hours=1),
            )
        )
        await store.upsert_task(
            _task(
                "paused-cron",
                trigger=TriggerKind.CRON,
                cron_expr="*/5 * * * *",
                scheduled_time=None,
                next_run=NOW - timedelta(minutes=1),
                status=TaskStatus.PAUSED,
            )
        )
        await store.upsert_task(_task("running-once", status=TaskStatus.RUNNING))
        await store.upsert_task(_task("done-once", status=TaskStatus.COMPLETED))

        due = await store.list_due(now=NOW, grace=timedelta(minutes=5))

        assert {t.id for t in due} == {"due-once", "due-cron"}

    async def test_list_due_loads_every_field(self, store: TaskStore) -> None:
        task = _full_task()
        task.next_run = NOW - timedelta(minutes=1)
        await store.upsert_task(task)

        due = await store.list_due(now=NOW, grace=timedelta(minutes=5))

        assert due == [task]


class TestTaskEventRoundTrip:
    """append_event + list_events preserve all 8 TaskEvent fields."""

    async def test_all_fields_round_trip(self, store: TaskStore) -> None:
        task = _full_task()
        await store.upsert_task(task)
        event = _event(
            "evt-1", "task-cron-1", datetime(2026, 8, 30, 9, 0, 0, 999999), trigger=TriggerKind.CRON
        )

        await store.append_event(event)
        events = await store.list_events()

        assert events == [event]
        assert events[0].trigger is TriggerKind.CRON  # reconstructed from the task row

    async def test_event_without_task_row_falls_back_to_once(self, store: TaskStore) -> None:
        event = _event("evt-orphan", "deleted-task", NOW)

        await store.append_event(event)
        events = await store.list_events()

        assert events[0].trigger is TriggerKind.ONCE


class TestListEvents:
    """list_events returns newest-first events, bounded by limit."""

    async def test_descending_order_and_limit(self, store: TaskStore) -> None:
        for i in range(5):
            await store.append_event(_event(f"e{i}", "t1", NOW + timedelta(seconds=i)))

        assert [e.id for e in await store.list_events(limit=3)] == ["e4", "e3", "e2"]
        assert [e.id for e in await store.list_events()] == ["e4", "e3", "e2", "e1", "e0"]


class TestPruneEvents:
    """prune_events keeps the newest N rows and returns the deleted count."""

    async def test_prune_keeps_newest_and_returns_count(self, store: TaskStore) -> None:
        for i in range(5):
            await store.append_event(_event(f"e{i}", "t1", NOW + timedelta(seconds=i)))

        deleted = await store.prune_events(keep=2)

        assert deleted == 3
        assert [e.id for e in await store.list_events()] == ["e4", "e3"]

    async def test_prune_below_limit_deletes_nothing(self, store: TaskStore) -> None:
        await store.append_event(_event("e0", "t1", NOW))

        assert await store.prune_events(keep=10) == 0
        assert len(await store.list_events()) == 1


class TestCounts:
    """counts aggregates task rows by lowercase status."""

    async def test_counts_by_status(self, store: TaskStore) -> None:
        await store.upsert_task(_task("p1"))
        await store.upsert_task(_task("p2"))
        await store.upsert_task(_task("paused", status=TaskStatus.PAUSED))
        await store.upsert_task(_task("done", status=TaskStatus.COMPLETED))

        assert await store.counts() == {"pending": 2, "paused": 1, "completed": 1}

    async def test_counts_empty_store(self, store: TaskStore) -> None:
        assert await store.counts() == {}


class TestPayloadCheckConstraint:
    """task_events.payload CHECK (payload IS NULL OR json_valid(payload))."""

    def test_non_json_payload_rejected(self, engine: Engine) -> None:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                insert(TaskEventRecord).values(
                    id=str(uuid.uuid4()),
                    task_id="t1",
                    event_type="task.failed",
                    payload="not json at all",
                )
            )

    def test_valid_json_payload_accepted(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                insert(TaskEventRecord).values(
                    id=str(uuid.uuid4()),
                    task_id="t1",
                    event_type="task.completed",
                    payload='{"result": "ok"}',
                )
            )


class TestSchemaMatchesDesignDDL:
    """Reflected schema matches design §7.1 column-for-column."""

    def test_scheduled_tasks_columns(self, engine: Engine) -> None:
        columns = {c["name"]: c for c in sa_inspect(engine).get_columns("scheduled_tasks")}

        assert list(columns) == [
            "id",
            "description",
            "trigger_kind",
            "cron_expr",
            "scheduled_at",
            "next_run_at",
            "last_run_at",
            "status",
            "channel",
            "content",
            "mode",
            "condition",
            "result",
            "error",
            "source",
            "conversation_id",
            "created_at",
            "updated_at",
        ]
        assert str(columns["id"]["type"]) == "VARCHAR(36)"
        assert str(columns["description"]["type"]) == "TEXT"
        assert str(columns["trigger_kind"]["type"]) == "VARCHAR(10)"
        assert str(columns["cron_expr"]["type"]) == "VARCHAR(100)"
        assert str(columns["scheduled_at"]["type"]) == "DATETIME"
        assert str(columns["status"]["type"]) == "VARCHAR(20)"
        assert str(columns["channel"]["type"]) == "VARCHAR(20)"
        assert str(columns["mode"]["type"]) == "VARCHAR(10)"
        assert str(columns["condition"]["type"]) == "VARCHAR(200)"
        assert str(columns["conversation_id"]["type"]) == "VARCHAR(36)"
        assert str(columns["source"]["type"]) == "VARCHAR(20)"

        not_null = [name for name, col in columns.items() if not col["nullable"]]
        assert set(not_null) == {
            "id",
            "description",
            "trigger_kind",
            "status",
            "channel",
            "content",
            "mode",
            "source",
            "created_at",
            "updated_at",
        }

    def test_scheduled_tasks_indexes_and_status_check(self, engine: Engine) -> None:
        insp = sa_inspect(engine)

        indexes = {i["name"]: i["column_names"] for i in insp.get_indexes("scheduled_tasks")}
        assert indexes == {
            "ix_scheduled_tasks_due": ["status", "scheduled_at"],
            "ix_scheduled_tasks_next": ["status", "next_run_at"],
        }

        check_sql = " ".join(c["sqltext"] for c in insp.get_check_constraints("scheduled_tasks"))
        for status in TaskStatus:
            assert f"'{status.value}'" in check_sql

    def test_task_events_columns(self, engine: Engine) -> None:
        columns = {c["name"]: c for c in sa_inspect(engine).get_columns("task_events")}

        assert list(columns) == [
            "id",
            "task_id",
            "event_type",
            "channel",
            "content",
            "payload",
            "created_at",
        ]
        assert str(columns["id"]["type"]) == "VARCHAR(36)"
        assert str(columns["task_id"]["type"]) == "VARCHAR(36)"
        assert str(columns["event_type"]["type"]) == "VARCHAR(20)"
        assert str(columns["channel"]["type"]) == "VARCHAR(20)"
        assert str(columns["payload"]["type"]) == "TEXT"
        assert str(columns["created_at"]["type"]) == "DATETIME"

    def test_task_events_index_and_payload_check(self, engine: Engine) -> None:
        insp = sa_inspect(engine)

        indexes = {i["name"]: i["column_names"] for i in insp.get_indexes("task_events")}
        assert indexes == {"ix_task_events_task": ["task_id", "created_at"]}

        check_sql = " ".join(c["sqltext"] for c in insp.get_check_constraints("task_events"))
        assert "json_valid(payload)" in check_sql

    def test_tables_created_by_shared_metadata(self, engine: Engine) -> None:
        """Both tables live on the repository Base metadata (init_db path)."""
        assert {"scheduled_tasks", "task_events"} <= set(Base.metadata.tables)
        assert {"scheduled_tasks", "task_events"} <= set(sa_inspect(engine).get_table_names())
