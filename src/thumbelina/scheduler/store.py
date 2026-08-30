"""Persistence layer for scheduled tasks and their lifecycle events.

Declares the two ORM records on the shared repository ``Base`` metadata so
``init_db``'s ``create_all`` creates the tables with no migration script,
and provides :class:`TaskStore` — an async facade that wraps synchronous
SQLAlchemy calls in ``asyncio.to_thread`` (same pattern as
``ConversationRepository``).

The DDL follows the design spec column-for-column:
``docs/plans/2026-08-30-event-timer-tasks-design.md`` §7.1.  Status values
are the lowercase ``TaskStatus.value`` strings.  The engine is the shared
application engine (``repository.engine``); the store never closes or
disposes it, and performs no DDL of its own.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, cast, overload

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, delete, func, select, text
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from thumbelina.repository.models import Base
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    TriggerKind,
)


class ScheduledTaskRecord(Base):
    """ORM record for the ``scheduled_tasks`` table (design §7.1).

    Attribute names intentionally differ from the ``ScheduledTask`` fields
    only where the DDL renames a column (``trigger_kind``/``scheduled_at``/
    ``next_run_at``/``last_run_at``); :meth:`TaskStore._to_record` and
    :meth:`TaskStore._to_model` own the mapping.
    """

    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    description: Mapped[str] = mapped_column(Text)
    trigger_kind: Mapped[str] = mapped_column(String(10), server_default="once")
    cron_expr: Mapped[str | None] = mapped_column(String(100))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint(
            "status IN ('pending','running','completed','cancelled','failed','paused','missed')"
        ),
        server_default="pending",
    )
    channel: Mapped[str] = mapped_column(String(20), server_default="web")
    content: Mapped[str] = mapped_column(Text, server_default="")
    mode: Mapped[str] = mapped_column(String(10), server_default="notify")
    condition: Mapped[str | None] = mapped_column(String(200))
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), server_default="agent")
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_scheduled_tasks_due", "status", "scheduled_at"),
        Index("ix_scheduled_tasks_next", "status", "next_run_at"),
    )


class TaskEventRecord(Base):
    """ORM record for the ``task_events`` table (design §7.1).

    ``created_at`` holds the event's ``fired_at``.  Per §7.1 the trigger
    kind of the originating task is not persisted; :meth:`TaskStore._to_model`
    reconstructs it from the task row while that row still exists.
    """

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str | None] = mapped_column(String(20))
    content: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[str | None] = mapped_column(
        Text, CheckConstraint("payload IS NULL OR json_valid(payload)")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_task_events_task", "task_id", text("created_at DESC")),)


class TaskStore:
    """Async persistence for scheduled tasks and task events.

    Parameters
    ----------
    engine:
        The shared application engine (``repository.engine``).  Tables must
        already exist (created by ``init_db`` / ``Base.metadata.create_all``);
        the store neither creates them nor disposes the engine.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def _get_session(self) -> Session:
        return self.SessionLocal()

    # ------------------------------------------------------------------
    # record <-> dataclass mapping
    # ------------------------------------------------------------------

    @overload
    def _to_record(self, obj: ScheduledTask) -> ScheduledTaskRecord: ...

    @overload
    def _to_record(self, obj: TaskEvent) -> TaskEventRecord: ...

    def _to_record(
        self, obj: ScheduledTask | TaskEvent
    ) -> ScheduledTaskRecord | TaskEventRecord:
        """Map a domain dataclass onto its ORM record."""
        if isinstance(obj, ScheduledTask):
            return ScheduledTaskRecord(
                id=obj.id,
                description=obj.description,
                trigger_kind=obj.trigger.value,
                cron_expr=obj.cron_expr,
                scheduled_at=obj.scheduled_time,
                next_run_at=obj.next_run,
                last_run_at=obj.last_run,
                status=obj.status.value,
                channel=obj.channel.value,
                content=obj.content,
                mode=obj.mode,
                condition=obj.condition,
                result=obj.result,
                error=obj.error,
                source=obj.source,
                conversation_id=obj.conversation_id,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
            )
        return TaskEventRecord(
            id=obj.id,
            task_id=obj.task_id,
            event_type=obj.type.value,
            channel=obj.channel.value,
            content=obj.content,
            payload=json.dumps(obj.payload, ensure_ascii=False),
            created_at=obj.fired_at,
        )

    @overload
    def _to_model(
        self, obj: ScheduledTaskRecord, *, trigger: TriggerKind | None = None
    ) -> ScheduledTask: ...

    @overload
    def _to_model(
        self, obj: TaskEventRecord, *, trigger: TriggerKind | None = None
    ) -> TaskEvent: ...

    def _to_model(
        self,
        obj: ScheduledTaskRecord | TaskEventRecord,
        *,
        trigger: TriggerKind | None = None,
    ) -> ScheduledTask | TaskEvent:
        """Map an ORM record onto its domain dataclass.

        ``trigger`` only applies to ``TaskEventRecord`` rows: §7.1 does not
        persist the originating task's trigger kind, so it is passed in from
        the joined task row; ``None`` (task row gone) reconstructs as ONCE.
        """
        if isinstance(obj, ScheduledTaskRecord):
            return ScheduledTask(
                id=obj.id,
                description=obj.description,
                trigger=TriggerKind(obj.trigger_kind),
                cron_expr=obj.cron_expr,
                scheduled_time=obj.scheduled_at,
                next_run=obj.next_run_at,
                last_run=obj.last_run_at,
                status=TaskStatus(obj.status),
                channel=DeliveryChannel(obj.channel),
                content=obj.content,
                mode=obj.mode,
                condition=obj.condition,
                result=obj.result,
                error=obj.error,
                source=obj.source,
                conversation_id=obj.conversation_id,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
            )
        channel = DeliveryChannel(obj.channel) if obj.channel is not None else DeliveryChannel.WEB
        return TaskEvent(
            id=obj.id,
            type=TaskEventType(obj.event_type),
            task_id=obj.task_id,
            fired_at=obj.created_at,
            trigger=trigger if trigger is not None else TriggerKind.ONCE,
            channel=channel,
            content=obj.content if obj.content is not None else "",
            payload=json.loads(obj.payload) if obj.payload else {},
        )

    # ------------------------------------------------------------------
    # scheduled_tasks
    # ------------------------------------------------------------------

    def _upsert_task_sync(self, task: ScheduledTask) -> None:
        with self._get_session() as session:
            session.merge(self._to_record(task))
            session.commit()

    async def upsert_task(self, task: ScheduledTask) -> None:
        """Insert the task or update it in place (matched by id)."""
        await asyncio.to_thread(self._upsert_task_sync, task)

    def _get_task_sync(self, task_id: str) -> ScheduledTask | None:
        with self._get_session() as session:
            record = session.get(ScheduledTaskRecord, task_id)
            return self._to_model(record) if record is not None else None

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        return await asyncio.to_thread(self._get_task_sync, task_id)

    def _list_tasks_sync(self) -> list[ScheduledTask]:
        with self._get_session() as session:
            records = session.scalars(select(ScheduledTaskRecord)).all()
            return [self._to_model(record) for record in records]

    async def list_tasks(self) -> list[ScheduledTask]:
        return await asyncio.to_thread(self._list_tasks_sync)

    def _delete_task_sync(self, task_id: str) -> None:
        with self._get_session() as session:
            session.execute(delete(ScheduledTaskRecord).where(ScheduledTaskRecord.id == task_id))
            session.commit()

    async def delete_task(self, task_id: str) -> None:
        """Remove the task row; a missing id is a no-op."""
        await asyncio.to_thread(self._delete_task_sync, task_id)

    def _list_due_sync(self, now: datetime, grace: timedelta) -> list[ScheduledTask]:
        # The grace window is applied by the scheduler's recover/heartbeat
        # (design §7.2/§7.3), not here: with missed_policy="run" the
        # scheduler must still see arbitrarily-late due tasks.
        due = (
            (ScheduledTaskRecord.trigger_kind == TriggerKind.ONCE.value)
            & (ScheduledTaskRecord.scheduled_at <= now)
        ) | (
            (ScheduledTaskRecord.trigger_kind == TriggerKind.CRON.value)
            & (ScheduledTaskRecord.next_run_at <= now)
        )
        stmt = select(ScheduledTaskRecord).where(
            ScheduledTaskRecord.status == TaskStatus.PENDING.value, due
        )
        with self._get_session() as session:
            records = session.scalars(stmt).all()
            return [self._to_model(record) for record in records]

    async def list_due(self, now: datetime, grace: timedelta) -> list[ScheduledTask]:
        """PENDING tasks whose trigger time has passed at ``now``.

        A task is due when (once ∧ ``scheduled_at`` ≤ now) ∨ (cron ∧
        ``next_run`` ≤ now); paused/running/finished tasks never qualify.
        """
        return await asyncio.to_thread(self._list_due_sync, now, grace)

    # ------------------------------------------------------------------
    # task_events
    # ------------------------------------------------------------------

    def _append_event_sync(self, event: TaskEvent) -> None:
        with self._get_session() as session:
            session.add(self._to_record(event))
            session.commit()

    async def append_event(self, event: TaskEvent) -> None:
        await asyncio.to_thread(self._append_event_sync, event)

    def _list_events_sync(self, limit: int) -> list[TaskEvent]:
        stmt = (
            select(TaskEventRecord, ScheduledTaskRecord.trigger_kind)
            .outerjoin(ScheduledTaskRecord, ScheduledTaskRecord.id == TaskEventRecord.task_id)
            .order_by(TaskEventRecord.created_at.desc())
            .limit(limit)
        )
        with self._get_session() as session:
            rows = session.execute(stmt).all()
            return [
                self._to_model(record, trigger=TriggerKind(kind) if kind is not None else None)
                for record, kind in rows
            ]

    async def list_events(self, limit: int = 50) -> list[TaskEvent]:
        """Newest-first events, at most ``limit`` of them."""
        return await asyncio.to_thread(self._list_events_sync, limit)

    def _prune_events_sync(self, keep: int) -> int:
        newest = select(TaskEventRecord.id).order_by(TaskEventRecord.created_at.desc()).limit(keep)
        stmt = delete(TaskEventRecord).where(TaskEventRecord.id.not_in(newest))
        with self._get_session() as session:
            result = cast("CursorResult[Any]", session.execute(stmt))
            session.commit()
            return int(result.rowcount)

    async def prune_events(self, keep: int) -> int:
        """Trim the event log to its newest ``keep`` rows; return deletions."""
        return await asyncio.to_thread(self._prune_events_sync, keep)

    def _counts_sync(self) -> dict[str, int]:
        stmt = select(ScheduledTaskRecord.status, func.count()).group_by(
            ScheduledTaskRecord.status
        )
        with self._get_session() as session:
            return {status: count for status, count in session.execute(stmt).all()}

    async def counts(self) -> dict[str, int]:
        """Task count per lowercase status (absent statuses omitted)."""
        return await asyncio.to_thread(self._counts_sync)
