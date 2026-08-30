"""Tests for the Heartbeat periodic inspection (design §7.4, §7.3).

Each §7.4 inspection row gets a deterministic test driven either by a
direct ``Heartbeat._run_checks(now)`` call with an injected ``now`` (no
sleeps) or by a short ``heartbeat_interval_seconds=0.05`` loop for the
genuinely time-driven behaviours (loop cycling, poll-loop revival,
periodic pruning).  Time-of-day dependent assertions anchor on
``FIXED_NOW`` (a whole hour) so hourly cron fire times stay deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import Engine

from thumbelina.repository.db import create_db_engine
from thumbelina.repository.models import Base
from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.heartbeat import Heartbeat
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    TriggerKind,
)
from thumbelina.scheduler.scheduler import TaskScheduler
from thumbelina.scheduler.store import TaskStore

# Whole hour so the hourly expression ``0 * * * *`` lands deterministically.
FIXED_NOW = datetime(2026, 8, 30, 12, 0, 0)

# The five §7.4 inspection item names surfaced in ``status()["checks"]``.
CHECK_NAMES = {"poll_loop", "stale_running", "cron_next_run", "once_overdue", "event_prune"}


# ----------------------------------------------------------------------
# fixtures / helpers
# ----------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """File-backed sqlite engine with both scheduler tables created."""
    eng = create_db_engine(f"sqlite:///{tmp_path / 'heartbeat.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def store(engine: Engine) -> TaskStore:
    return TaskStore(engine)


def _config(**overrides: object) -> SimpleNamespace:
    """Duck-typed stand-in for T8's ``SchedulerConfig`` (design §10)."""
    values: dict[str, object] = {
        "heartbeat_interval_seconds": 0.05,
        "missed_policy": "mark",
        "missed_grace_minutes": 5,
        "stale_running_minutes": 10,
        "event_retention": 500,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _task(task_id: str, **overrides: object) -> ScheduledTask:
    fields: dict[str, object] = {
        "id": task_id,
        "description": f"task {task_id}",
        "scheduled_time": FIXED_NOW,
        "status": TaskStatus.PENDING,
    }
    fields.update(overrides)
    return ScheduledTask(**fields)


class _EventLog:
    """Subscribe to every event type and record what the bus dispatches."""

    def __init__(self, bus: EventBus) -> None:
        self.events: list[TaskEvent] = []
        for event_type in TaskEventType:
            bus.subscribe(event_type, self._record)

    async def _record(self, event: TaskEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: TaskEventType) -> list[TaskEvent]:
        return [event for event in self.events if event.type == event_type]


async def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Poll ``predicate`` until it holds or ``timeout`` (real seconds) pass."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def _event(task_id: str, index: int = 0) -> TaskEvent:
    return TaskEvent(
        type=TaskEventType.CREATED,
        task_id=task_id,
        trigger=TriggerKind.ONCE,
        channel=DeliveryChannel.WEB,
        content=f"event {index}",
    )


# ----------------------------------------------------------------------
# §7.4 row 2: stale RUNNING → FAILED + task.failed
# ----------------------------------------------------------------------


class TestStaleRunning:
    async def test_beyond_threshold_marked_failed_with_event(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus)
        task = _task(
            "t-stale",
            status=TaskStatus.RUNNING,
            last_run=FIXED_NOW - timedelta(minutes=11),
        )
        await sched.add_task(task)

        hb = Heartbeat(sched, bus, _config())
        acted = await hb._run_checks(FIXED_NOW)

        assert task.status == TaskStatus.FAILED
        assert task.error == "stale running"
        assert "stale_running" in acted
        failed = log.of_type(TaskEventType.FAILED)
        assert len(failed) == 1
        assert failed[0].task_id == "t-stale"
        assert failed[0].payload["error"] == "stale running"

    async def test_within_threshold_or_unknown_start_untouched(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus)
        fresh = _task(
            "t-fresh",
            status=TaskStatus.RUNNING,
            last_run=FIXED_NOW - timedelta(minutes=9),
        )
        no_start = _task("t-nostart", status=TaskStatus.RUNNING, last_run=None)
        await sched.add_task(fresh)
        await sched.add_task(no_start)

        hb = Heartbeat(sched, bus, _config())
        acted = await hb._run_checks(FIXED_NOW)

        assert fresh.status == TaskStatus.RUNNING
        assert no_start.status == TaskStatus.RUNNING
        assert "stale_running" not in acted
        assert log.of_type(TaskEventType.FAILED) == []

    async def test_persisted_before_event_emitted(self, store: TaskStore) -> None:
        """§5 transition semantics: the store row is FAILED when the hook runs."""
        bus = EventBus()
        rows_at_emit: list[TaskStatus | None] = []

        async def on_failed(event: TaskEvent) -> None:
            row = await store.get_task(event.task_id)
            rows_at_emit.append(row.status if row is not None else None)

        bus.subscribe(TaskEventType.FAILED, on_failed)
        sched = TaskScheduler(store=store, bus=bus)
        task = _task(
            "t-stale-store",
            status=TaskStatus.RUNNING,
            last_run=FIXED_NOW - timedelta(minutes=30),
        )
        await sched.add_task(task)

        hb = Heartbeat(sched, bus, _config())
        await hb._run_checks(FIXED_NOW)

        assert rows_at_emit == [TaskStatus.FAILED]
        row = await store.get_task("t-stale-store")
        assert row is not None and row.status == TaskStatus.FAILED
        assert row.error == "stale running"


# ----------------------------------------------------------------------
# §7.4 row 3: cron next_run behind now → advance + summary task.missed
# ----------------------------------------------------------------------


class TestCronMissed:
    async def test_mark_policy_advances_next_run_and_emits_summary(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus, config=_config(missed_policy="mark"))
        old_next = FIXED_NOW - timedelta(hours=2)
        task = _task(
            "t-cron",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=old_next,
        )
        await sched.add_task(task)

        hb = Heartbeat(sched, bus, _config())
        acted = await hb._run_checks(FIXED_NOW)

        assert task.next_run == FIXED_NOW + timedelta(hours=1)
        assert task.status == TaskStatus.PENDING
        assert "cron_next_run" in acted
        missed = log.of_type(TaskEventType.MISSED)
        assert len(missed) == 1  # one summary event, never per-occurrence
        assert missed[0].payload["skipped_occurrences"] == 2
        assert missed[0].payload["scheduled_for"] == old_next.isoformat()
        assert missed[0].payload["policy"] == "mark"

    async def test_run_policy_emits_summary_without_advance(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus, config=_config(missed_policy="run"))
        old_next = FIXED_NOW - timedelta(hours=2)
        task = _task(
            "t-cron",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=old_next,
        )
        await sched.add_task(task)

        hb = Heartbeat(sched, bus, _config(missed_policy="run"))
        acted = await hb._run_checks(FIXED_NOW)

        # run policy: next_run untouched so the scan fires the backlog at
        # most once (§7.3); the summary missed event is still emitted.
        assert task.next_run == old_next
        assert "cron_next_run" in acted
        missed = log.of_type(TaskEventType.MISSED)
        assert len(missed) == 1
        assert missed[0].payload["policy"] == "run"
        assert missed[0].payload["skipped_occurrences"] == 2

    async def test_future_next_run_and_paused_untouched(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus)
        future = _task(
            "t-future",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=FIXED_NOW + timedelta(hours=1),
        )
        paused = _task(
            "t-paused",
            trigger=TriggerKind.CRON,
            cron_expr="0 * * * *",
            scheduled_time=None,
            next_run=FIXED_NOW - timedelta(hours=2),
            status=TaskStatus.PAUSED,
        )
        await sched.add_task(future)
        await sched.add_task(paused)

        hb = Heartbeat(sched, bus, _config())
        acted = await hb._run_checks(FIXED_NOW)

        assert future.next_run == FIXED_NOW + timedelta(hours=1)
        assert paused.next_run == FIXED_NOW - timedelta(hours=2)  # user paused it
        assert "cron_next_run" not in acted
        assert log.of_type(TaskEventType.MISSED) == []


# ----------------------------------------------------------------------
# §7.4/§7.3: once overdue beyond grace → mark=MISSED / run=stays PENDING
# ----------------------------------------------------------------------


class TestOnceMissed:
    async def test_dead_loop_mark_policy_beyond_grace_marked_missed(self) -> None:
        """I2 (final review): the missed determination only runs against a
        DEAD scan loop (scheduler still ``running``) — recover rule 1
        semantics (§7.3)."""
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus, config=_config(missed_policy="mark"))
        overdue = _task("t-late", scheduled_time=FIXED_NOW - timedelta(minutes=10))
        within_grace = _task("t-grace", scheduled_time=FIXED_NOW - timedelta(minutes=3))
        await sched.add_task(overdue)
        await sched.add_task(within_grace)

        # Simulate a crashed scan loop: scheduler intent intact, loop dead.
        await sched.start()
        assert sched._poll_task is not None
        sched._poll_task.cancel()
        await asyncio.sleep(0.05)  # let the cancellation land
        assert sched._poll_task.done()

        hb = Heartbeat(sched, bus, _config())
        acted = await hb._run_checks(FIXED_NOW)
        await sched.stop()

        assert overdue.status == TaskStatus.MISSED  # terminal (§5.1)
        assert within_grace.status == TaskStatus.PENDING  # grace still open
        assert "once_overdue" in acted
        missed = log.of_type(TaskEventType.MISSED)
        assert len(missed) == 1
        assert missed[0].task_id == "t-late"
        assert missed[0].payload["scheduled_for"] == overdue.scheduled_time.isoformat()
        assert missed[0].payload["policy"] == "mark"

    async def test_alive_but_blocked_loop_does_not_mark_missed(self) -> None:
        """I2: with the scan loop alive — even blocked inside a hanging
        delivery — an overdue once task is queue backlog, not a miss.  The
        heartbeat leaves it PENDING for the loop to deliver when it
        unblocks; marking it MISSED here would silently drop the work."""
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus, config=_config())

        unblock = asyncio.Event()
        entered = asyncio.Event()

        async def hanging_delivery(task: ScheduledTask) -> None:
            entered.set()
            await unblock.wait()

        first = _task("t-blocking", scheduled_time=datetime.now() - timedelta(seconds=5))
        await sched.add_task(first)
        await sched.start(hanging_delivery)
        try:
            assert await _wait_for(entered.is_set)
            # The loop is alive — stuck inside the hanging delivery.
            assert sched._poll_task is not None and not sched._poll_task.done()

            # Becomes overdue beyond grace while the loop is blocked.
            overdue = _task("t-backlog", scheduled_time=datetime.now() - timedelta(minutes=10))
            await sched.add_task(overdue)

            hb = Heartbeat(sched, bus, _config())
            acted = await hb._run_checks(datetime.now())

            assert "once_overdue" not in acted
            assert overdue.status == TaskStatus.PENDING  # backlog, not missed
            assert log.of_type(TaskEventType.MISSED) == []
        finally:
            unblock.set()
            await sched.stop()

    async def test_never_started_scheduler_leaves_overdue_alone(self) -> None:
        """I2: before ``scheduler.start()`` (running=False) the missed
        determination must not fire — the startup path is recover()'s job
        (§7.2), and a deliberately stopped scheduler is not ours to reap."""
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus, config=_config(missed_policy="mark"))
        overdue = _task("t-late", scheduled_time=FIXED_NOW - timedelta(minutes=10))
        await sched.add_task(overdue)

        hb = Heartbeat(sched, bus, _config())
        acted = await hb._run_checks(FIXED_NOW)

        assert overdue.status == TaskStatus.PENDING  # recover's call, not the heartbeat's
        assert "once_overdue" not in acted
        assert log.of_type(TaskEventType.MISSED) == []

    async def test_dead_loop_run_policy_stays_pending_and_immediately_due(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus, config=_config(missed_policy="run"))
        overdue = _task("t-late", scheduled_time=datetime.now() - timedelta(minutes=10))
        await sched.add_task(overdue)

        # I2: the missed determination only runs against a dead scan loop.
        await sched.start()
        assert sched._poll_task is not None
        sched._poll_task.cancel()
        await asyncio.sleep(0.05)

        hb = Heartbeat(sched, bus, _config(missed_policy="run"))
        acted = await hb._run_checks(datetime.now())
        await sched.stop()

        assert overdue.status == TaskStatus.PENDING  # fires immediately, not MISSED
        assert log.of_type(TaskEventType.MISSED) == []
        assert "once_overdue" in acted
        assert overdue in await sched.get_due_tasks()


# ----------------------------------------------------------------------
# §7.4 row 4: task_events over retention → pruned by created_at
# ----------------------------------------------------------------------


class TestEventPruning:
    async def test_prunes_over_retention(self, store: TaskStore) -> None:
        sched = TaskScheduler(store=store)
        for i in range(13):
            await store.append_event(_event(f"t{i}", i))

        hb = Heartbeat(sched, EventBus(), _config(event_retention=10))
        acted = await hb._run_checks(FIXED_NOW)

        assert "event_prune" in acted
        remaining = await store.list_events(limit=100)
        assert len(remaining) == 10

    async def test_within_retention_no_action(self, store: TaskStore) -> None:
        sched = TaskScheduler(store=store)
        for i in range(3):
            await store.append_event(_event(f"t{i}", i))

        hb = Heartbeat(sched, EventBus(), _config(event_retention=10))
        acted = await hb._run_checks(FIXED_NOW)

        assert "event_prune" not in acted
        assert len(await store.list_events(limit=100)) == 3

    async def test_loop_prunes_periodically(self, store: TaskStore) -> None:
        """The running heartbeat loop trims on its own cadence."""
        sched = TaskScheduler(store=store)
        for i in range(5):
            await store.append_event(_event(f"t{i}", i))

        hb = Heartbeat(sched, None, _config(event_retention=2))
        await hb.start()
        try:
            remaining: list[TaskEvent] = []
            deadline = asyncio.get_running_loop().time() + 3.0
            while asyncio.get_running_loop().time() < deadline:
                remaining = await store.list_events(limit=100)
                if len(remaining) == 2:
                    break
                await asyncio.sleep(0.01)
            assert len(remaining) == 2
        finally:
            await hb.stop()


# ----------------------------------------------------------------------
# §7.4 row 1: dead poll loop → restarted, scheduler.running restored
# ----------------------------------------------------------------------


class TestPollLoopLiveness:
    async def test_cancelled_poll_task_restarted_with_original_callback(self) -> None:
        bus = EventBus()
        log = _EventLog(bus)
        sched = TaskScheduler(bus=bus)
        fired: list[str] = []

        async def on_due(task: ScheduledTask) -> None:
            fired.append(task.id)

        await sched.start(on_due)
        hb = Heartbeat(sched, bus, _config())
        await hb.start()
        try:
            old = sched._poll_task
            assert old is not None
            old.cancel()
            await asyncio.sleep(0.05)  # let the cancellation land
            assert old.done()
            assert sched.running is True  # intent to run never changed

            restarted = await _wait_for(
                lambda: (
                    sched._poll_task is not None
                    and sched._poll_task is not old
                    and not sched._poll_task.done()
                )
            )
            assert restarted, "heartbeat did not revive the poll loop"
            assert hb.status()["checks"]["poll_loop"] == "acted"
            assert sched.running is True

            replacement = sched._poll_task
            await asyncio.sleep(0.2)  # several heartbeat cycles
            assert sched._poll_task is replacement  # no avalanche re-restarts

            # the restarted loop delivers through the original on_due_task
            task = _task("t-after-restart", scheduled_time=datetime.now())
            await sched.add_task(task)
            assert await _wait_for(lambda: bool(fired))
            assert fired == ["t-after-restart"]
            assert log.of_type(TaskEventType.DUE) != []
        finally:
            await hb.stop()
            await sched.stop()

    async def test_never_started_or_stopped_scheduler_left_alone(self) -> None:
        sched = TaskScheduler()
        hb = Heartbeat(sched, None, _config())
        await hb.start()
        try:
            await asyncio.sleep(0.15)  # a few supervision cycles
            assert sched._poll_task is None  # never started → not resurrected
            assert hb.status()["checks"]["poll_loop"] == "ok"
        finally:
            await hb.stop()

        await sched.start()
        await sched.stop()  # deliberate stop clears the loop task
        assert sched.running is False and sched._poll_task is None
        await hb._run_checks(datetime.now())
        assert sched._poll_task is None  # stop() intent respected

    async def test_heartbeat_stop_halts_supervision(self) -> None:
        sched = TaskScheduler()
        await sched.start()
        hb = Heartbeat(sched, None, _config())
        await hb.start()
        await hb.stop()

        old = sched._poll_task
        assert old is not None
        old.cancel()
        await asyncio.sleep(0.3)
        assert sched._poll_task is old  # identity unchanged: no restart
        assert old.done()


# ----------------------------------------------------------------------
# status() snapshot (§8.1 GET /tasks/scheduler/status)
# ----------------------------------------------------------------------


class TestStatusSnapshot:
    async def test_snapshot_fields_before_and_after_checks(self) -> None:
        sched = TaskScheduler()
        await sched.add_task(_task("t1"))
        await sched.add_task(_task("t2", status=TaskStatus.FAILED, error="boom"))
        hb = Heartbeat(sched, None, _config())

        before = hb.status()
        assert set(before) == {"running", "last_heartbeat_at", "task_counts", "checks"}
        assert before["running"] is False
        assert before["last_heartbeat_at"] is None
        assert before["task_counts"] == {}
        assert before["checks"] == {name: "idle" for name in CHECK_NAMES}

        await hb._run_checks(FIXED_NOW)
        snap = hb.status()
        assert snap["running"] is False  # the loop itself has not started
        assert snap["last_heartbeat_at"] == FIXED_NOW
        assert snap["task_counts"] == {"pending": 1, "failed": 1}
        assert set(snap["checks"]) == CHECK_NAMES
        assert set(snap["checks"].values()) <= {"ok", "acted", "error", "idle"}

        await hb.start()
        try:
            assert hb.status()["running"] is True
        finally:
            await hb.stop()
        after = hb.status()
        assert after["running"] is False
        assert after["last_heartbeat_at"] == FIXED_NOW  # snapshot retained

    async def test_loop_uses_injected_clock(self) -> None:
        hb = Heartbeat(TaskScheduler(), None, _config(), now_fn=lambda: FIXED_NOW)
        await hb.start()
        try:
            assert await _wait_for(lambda: hb.status()["last_heartbeat_at"] == FIXED_NOW)
        finally:
            await hb.stop()


# ----------------------------------------------------------------------
# lifecycle: start/stop semantics aligned with TaskScheduler
# ----------------------------------------------------------------------


class TestLifecycle:
    async def test_double_start_raises_and_stop_idempotent(self) -> None:
        hb = Heartbeat(TaskScheduler(), None, _config())
        await hb.start()
        try:
            with pytest.raises(RuntimeError):
                await hb.start()
        finally:
            await hb.stop()
        await hb.stop()  # second stop is a no-op, no error
        assert hb.running is False


# ----------------------------------------------------------------------
# §11: a failing check is logged and isolated, never kills the loop
# ----------------------------------------------------------------------


class _BrokenStore:
    """Store whose event-log calls always fail (design §11 degraded mode)."""

    async def upsert_task(self, task: ScheduledTask) -> None:
        return None

    async def counts(self) -> dict[str, int]:
        raise RuntimeError("store down")

    async def prune_events(self, keep: int) -> int:
        raise RuntimeError("store down")


class TestErrorIsolation:
    async def test_store_failure_does_not_break_other_checks(self) -> None:
        sched = TaskScheduler()
        sched._store = _BrokenStore()
        late = _task("t-late", scheduled_time=FIXED_NOW - timedelta(minutes=10))
        await sched.add_task(late)

        # I2: once_overdue only acts on a dead scan loop — simulate a crash.
        await sched.start()
        assert sched._poll_task is not None
        sched._poll_task.cancel()
        await asyncio.sleep(0.05)

        hb = Heartbeat(sched, None, _config())
        acted = await hb._run_checks(FIXED_NOW)
        await sched.stop()

        assert "once_overdue" in acted  # other checks still ran
        assert late.status == TaskStatus.MISSED
        assert hb.status()["checks"]["event_prune"] == "error"
        assert hb.status()["checks"]["once_overdue"] == "acted"
        assert hb.status()["task_counts"] == {"missed": 1}  # in-memory fallback

        # repeated failing cycles never kill the loop
        await hb.start()
        try:
            await asyncio.sleep(0.2)
            assert hb.running is True
        finally:
            await hb.stop()
