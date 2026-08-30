"""Task scheduler for managing scheduled tasks.

v2 (design ``docs/plans/2026-08-30-event-timer-tasks-design.md``): the
scheduler is event-driven — every status transition can be persisted to a
:class:`~thumbelina.scheduler.store.TaskStore` and is announced as a
structured :class:`~thumbelina.scheduler.models.TaskEvent` on an
:class:`~thumbelina.scheduler.events.EventBus`, while the public v1 API
(``add_task/get_task/list_tasks/cancel_task/complete_task/get_due_tasks/
start(on_due_task=)/stop``) keeps its signatures and semantics.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from thumbelina.scheduler.cron import CronTrigger
from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.models import (
    ScheduledTask,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    TriggerKind,
)
from thumbelina.scheduler.store import TaskStore

__all__ = ["ScheduledTask", "TaskScheduler", "TaskStatus"]

logger = logging.getLogger(__name__)

# How often the polling loop wakes up to check for due tasks (seconds).
_POLL_INTERVAL = 1.0

# Defaults when no ``config`` object is supplied (design §10).
_DEFAULT_MISSED_POLICY = "mark"
_DEFAULT_MISSED_GRACE_MINUTES = 5

# Upper bound for counting skipped cron occurrences when summarising a
# missed backlog — keeps recover() bounded across absurdly long downtimes.
_MAX_SKIPPED_OCCURRENCES = 10_000

# The callback may return a delivery receipt (DeliveryDispatcher); a
# non-None return is recorded in the COMPLETED event payload ``result``.
DueCallback = Callable[[ScheduledTask], Awaitable[Any]]
ConditionCallback = Callable[[str], Awaitable[bool]]


def _iso(value: datetime | None) -> str | None:
    """JSON-safe ISO rendering for event payloads."""
    return value.isoformat() if value is not None else None


def _count_skipped_occurrences(expr: str, after: datetime, now: datetime) -> int:
    """Count cron fire times in ``(after, now]``, capped for safety."""
    count = 0
    try:
        trigger = CronTrigger(expr)
        cursor = after
        while count < _MAX_SKIPPED_OCCURRENCES:
            nxt = trigger.next_after(cursor)
            if nxt > now:
                break
            count += 1
            cursor = nxt
    except ValueError:
        return count
    return count


class TaskScheduler:
    """Scheduler for managing and executing scheduled tasks.

    Parameters
    ----------
    store:
        Optional persistence backend (:class:`TaskStore`).  Every status
        transition is written through when injected; without it the
        scheduler runs purely in memory (v1 behaviour).
    bus:
        Optional :class:`EventBus`.  Lifecycle events (``task.created``,
        ``task.due``, ``task.completed``, ``task.failed``, ``task.missed``,
        ``task.cancelled``) are emitted through it; without a bus events
        are silently dropped.
    check_condition:
        Optional async callback that evaluates a condition string and
        returns ``True`` when the condition is satisfied.  Used for
        condition-based tasks (those with a ``condition`` field set).
    config:
        Optional duck-typed settings object exposing ``missed_policy``
        (``"mark"``/``"run"``, design §7.3/§10) and ``missed_grace_minutes``;
        defaults to ``mark`` / ``5``.

    Call :meth:`recover` before :meth:`start` when a store is injected
    (§7.2), :meth:`start` to begin the background polling loop, and
    :meth:`stop` to shut down gracefully.
    """

    def __init__(
        self,
        store: TaskStore | None = None,
        bus: EventBus | None = None,
        check_condition: ConditionCallback | None = None,
        config: Any = None,
    ) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._poll_task: asyncio.Task[None] | None = None
        # Retained so the Heartbeat (§7.4) can re-create a dead polling loop
        # with the exact delivery callback this scheduler was started with.
        self._on_due_task: DueCallback | None = None
        self._check_condition = check_condition
        self._store = store
        self._bus = bus
        self._missed_policy: str = (
            getattr(config, "missed_policy", _DEFAULT_MISSED_POLICY)
            if config is not None
            else _DEFAULT_MISSED_POLICY
        )
        grace_minutes = (
            getattr(config, "missed_grace_minutes", _DEFAULT_MISSED_GRACE_MINUTES)
            if config is not None
            else _DEFAULT_MISSED_GRACE_MINUTES
        )
        self._missed_grace = timedelta(minutes=grace_minutes)

    @property
    def running(self) -> bool:
        """Whether the background polling loop is active."""
        return self._running

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    async def _persist(self, task: ScheduledTask) -> None:
        """Write a status transition through to the store (when injected).

        A store failure never breaks scheduling (design §11): the error is
        logged and the transition lives on in memory only — degraded to v1
        behaviour, the server keeps running.
        """
        if self._store is None:
            return
        try:
            await self._store.upsert_task(task)
        except Exception as exc:
            logger.warning(
                "Task store unavailable, task %s kept in memory only: %s", task.id, exc
            )

    async def _emit(self, event: TaskEvent) -> None:
        """Publish an event on the bus (silently dropped when absent)."""
        if self._bus is not None:
            await self._bus.emit(event)

    def _make_event(
        self, task: ScheduledTask, event_type: TaskEventType, payload: dict[str, Any]
    ) -> TaskEvent:
        return TaskEvent(
            type=event_type,
            task_id=task.id,
            trigger=task.trigger,
            channel=task.channel,
            content=task.content,
            payload=payload,
        )

    async def _lookup_task(self, task_id: str) -> ScheduledTask | None:
        """Memory-first lookup with a store fallback (cached on hit).

        A store read failure is logged and treated as a miss (design §11).
        """
        task = self._tasks.get(task_id)
        if task is None and self._store is not None:
            try:
                task = await self._store.get_task(task_id)
            except Exception as exc:
                logger.warning("Task store read failed for task %s: %s", task_id, exc)
                return None
            if task is not None:
                self._tasks[task_id] = task
        return task

    # ------------------------------------------------------------------
    # public CRUD API (v1 signatures preserved)
    # ------------------------------------------------------------------

    async def add_task(self, task: ScheduledTask) -> None:
        """Add a task to the scheduler.

        For cron tasks without a caller-supplied ``next_run`` the next fire
        time is computed from ``cron_expr`` as a fallback.  An invalid or
        never-firing expression (e.g. ``0 0 31 2 *``) raises ``ValueError``
        and the task is not created (design §6).
        """
        if task.trigger == TriggerKind.CRON and task.next_run is None:
            if not task.cron_expr:
                raise ValueError(
                    f"Invalid cron expression: {task.cron_expr!r} "
                    "(cron tasks require a cron_expr)"
                )
            base = task.scheduled_time if task.scheduled_time is not None else datetime.now()
            try:
                task.next_run = CronTrigger(task.cron_expr).next_after(base)
            except ValueError as exc:
                raise ValueError(f"Invalid cron expression: {task.cron_expr!r} ({exc})") from exc
        self._tasks[task.id] = task
        await self._persist(task)
        await self._emit(self._make_event(task, TaskEventType.CREATED, {"source": task.source}))

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        """Get a task by ID (falls back to the store when injected)."""
        return await self._lookup_task(task_id)

    async def list_tasks(self) -> list[ScheduledTask]:
        """List all tasks."""
        return list(self._tasks.values())

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task (PAUSED cron tasks included)."""
        task = await self._lookup_task(task_id)
        if not task:
            return False
        task.status = TaskStatus.CANCELLED
        await self._persist(task)
        # ``task.cancelled`` is reserved for user-initiated termination;
        # pause/resume are deliberately excluded from it (design §3).
        await self._emit(self._make_event(task, TaskEventType.CANCELLED, {"by": "scheduler"}))
        return True

    async def complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        task = await self._lookup_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            await self._persist(task)

    async def get_due_tasks(self) -> list[ScheduledTask]:
        """Get tasks that are due to run.

        A task is due when ``status=PENDING`` and its trigger time has
        passed: ``scheduled_time`` for ONCE tasks, ``next_run`` for CRON
        tasks.  PAUSED (and all other non-pending) tasks are skipped.
        """
        now = datetime.now()
        due: list[ScheduledTask] = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            trigger_time = (
                task.scheduled_time if task.trigger == TriggerKind.ONCE else task.next_run
            )
            if trigger_time is not None and trigger_time <= now:
                due.append(task)
        return due

    # ------------------------------------------------------------------
    # pause / resume (cron only)
    # ------------------------------------------------------------------

    async def pause_task(self, task_id: str) -> bool:
        """Pause a PENDING cron task; it will not fire until resumed.

        Returns ``False`` for unknown ids and for anything that is not a
        PENDING cron task.  No event is emitted: none of the existing
        ``TaskEventType`` values fits a pause (``task.cancelled`` explicitly
        excludes pause per design §3) and adding enum values is out of
        scope — the state change is persisted and visible via the task API.
        """
        task = await self._lookup_task(task_id)
        if task is None:
            return False
        if task.trigger != TriggerKind.CRON or task.status != TaskStatus.PENDING:
            return False
        task.status = TaskStatus.PAUSED
        await self._persist(task)
        return True

    async def resume_task(self, task_id: str) -> bool:
        """Resume a PAUSED cron task, recomputing ``next_run`` from now.

        Returns ``False`` for unknown ids and for anything that is not a
        PAUSED cron task (including tasks whose expression can no longer be
        evaluated).
        """
        task = await self._lookup_task(task_id)
        if task is None:
            return False
        if task.trigger != TriggerKind.CRON or task.status != TaskStatus.PAUSED:
            return False
        try:
            task.next_run = CronTrigger(task.cron_expr or "").next_after(datetime.now())
        except ValueError as exc:
            logger.warning("Cannot resume task %s: %s", task_id, exc)
            return False
        task.status = TaskStatus.PENDING
        await self._persist(task)
        return True

    # ------------------------------------------------------------------
    # startup recovery (design §7.2)
    # ------------------------------------------------------------------

    async def recover(self, now: datetime | None = None) -> None:
        """Apply the five startup-recovery rules (§7.2); no-op without a store.

        Hydrates every persisted task into memory, then:

        1. ONCE PENDING due before ``now - grace`` → per missed policy
           (§7.3): ``mark`` → MISSED terminal + ``task.missed``; ``run`` →
           stays PENDING (fires immediately on the next scan);
        2. ONCE PENDING due within ``(now - grace, now]`` → stays PENDING
           (the scan loop fires it within seconds);
        3. ONCE RUNNING residue → FAILED (``error="interrupted by restart"``)
           + ``task.failed``;
        4. CRON PENDING with ``next_run <= now`` → a single summary
           ``task.missed`` event is emitted for the skipped occurrences
           under both policies; ``mark`` additionally advances ``next_run``
           to the nearest future occurrence without firing, while ``run``
           leaves ``next_run`` as-is so the scan fires the backlog at most
           once (skipped occurrences are never replayed);
        5. CRON RUNNING residue → same as rule 3.

        Call this before :meth:`start` when a store is injected.
        """
        if self._store is None:
            return
        now = now if now is not None else datetime.now()
        grace_deadline = now - self._missed_grace
        try:
            stored_tasks = await self._store.list_tasks()
        except Exception as exc:
            # Design §11: a dead store degrades to memory-only operation.
            logger.warning("Task store unavailable during recover, skipping: %s", exc)
            return
        for stored in stored_tasks:
            self._tasks[stored.id] = stored  # hydrate the working set
        for task in list(self._tasks.values()):
            if task.status == TaskStatus.RUNNING:
                # rules 3 & 5: residue from a previous process
                scheduled_for = (
                    task.scheduled_time if task.trigger == TriggerKind.ONCE else task.next_run
                )
                task.status = TaskStatus.FAILED
                task.error = "interrupted by restart"
                await self._persist(task)
                await self._emit(
                    self._make_event(
                        task,
                        TaskEventType.FAILED,
                        {"error": task.error, "scheduled_for": _iso(scheduled_for)},
                    )
                )
            elif (
                task.trigger == TriggerKind.ONCE
                and task.status == TaskStatus.PENDING
                and task.scheduled_time is not None
            ):
                if task.scheduled_time <= grace_deadline:
                    await self._recover_overdue_once(task)
                # else: rule 2 — within grace, the scan fires it shortly
            elif (
                task.trigger == TriggerKind.CRON
                and task.status == TaskStatus.PENDING
                and task.next_run is not None
                and task.next_run <= now
            ):
                await self._recover_overdue_cron(task, now)

    async def _recover_overdue_once(self, task: ScheduledTask) -> None:
        """Rule 1: a once task overdue beyond the grace window."""
        if self._missed_policy == "run":
            # §7.3: late tasks fire immediately — keep PENDING so the scan
            # loop picks them up (the grace limit is bypassed entirely).
            return
        task.status = TaskStatus.MISSED
        await self._persist(task)
        await self._emit(
            self._make_event(
                task,
                TaskEventType.MISSED,
                {"scheduled_for": _iso(task.scheduled_time), "policy": self._missed_policy},
            )
        )

    async def _recover_overdue_cron(self, task: ScheduledTask, now: datetime) -> None:
        """Rule 4: a cron task whose next_run passed while the process was down.

        Both policies emit a single summary ``task.missed`` for the skipped
        occurrences (review ruling R2 — the §7.3 "no replay of skipped
        occurrences" limit caps the firing count, not observability).  They
        differ only in firing: ``mark`` advances ``next_run`` to the nearest
        future occurrence without firing; ``run`` leaves ``next_run`` as-is
        so the scan fires the backlog at most once, after which §5.2
        advances it normally.
        """
        assert task.next_run is not None  # guarded by the caller
        old_next_run = task.next_run
        skipped = _count_skipped_occurrences(task.cron_expr or "", old_next_run, now)
        if self._missed_policy != "run":
            try:
                task.next_run = CronTrigger(task.cron_expr or "").next_after(now)
            except ValueError as exc:
                logger.warning("Cannot advance cron next_run for task %s: %s", task.id, exc)
                return
            await self._persist(task)
        await self._emit(
            self._make_event(
                task,
                TaskEventType.MISSED,
                {
                    "scheduled_for": _iso(old_next_run),
                    "policy": self._missed_policy,
                    "skipped_occurrences": skipped,
                },
            )
        )

    # ------------------------------------------------------------------
    # polling loop
    # ------------------------------------------------------------------

    async def start(
        self,
        on_due_task: DueCallback | None = None,
    ) -> None:
        """Start the background polling loop.

        Parameters
        ----------
        on_due_task:
            Optional async callback invoked for each due task.  The
            scheduler sets the task status to ``RUNNING`` (and emits
            ``task.due``) before calling and to ``COMPLETED`` on success /
            ``FAILED`` on error (D10).  A non-``None`` return value (a
            delivery receipt) is recorded in the COMPLETED payload
            ``result``.  Without a callback due tasks are simply marked
            completed (v1 behaviour).

        Raises
        ------
        RuntimeError
            If the polling loop is already running.
        """
        if self._running:
            raise RuntimeError("Scheduler polling loop is already running")

        self._on_due_task = on_due_task
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(on_due_task))

    async def stop(self) -> None:
        """Stop the background polling loop gracefully."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    def _restart_loop(self) -> None:
        """Re-create a dead polling loop (Heartbeat liveness check, §7.4).

        No-op unless the scheduler believes it is running *and* the previous
        loop task has actually finished — a deliberately stopped scheduler is
        never resurrected, and a live loop is never duplicated.  Reuses the
        ``on_due_task`` callback captured by :meth:`start` so a restarted
        loop delivers exactly like the original one.  Must be called from
        within the running event loop (the Heartbeat loop is).
        """
        if not self._running:
            return
        old = self._poll_task
        if old is not None and not old.done():
            return
        self._poll_task = asyncio.create_task(self._poll_loop(self._on_due_task))

    async def _poll_loop(
        self,
        on_due_task: DueCallback | None,
    ) -> None:
        """Internal: periodically check for and execute due tasks.

        For condition-based tasks (those with a ``condition`` field), the
        ``check_condition`` callback is called instead of relying solely on
        the scheduled time.  The task is only executed when the condition
        returns ``True`` — in that case it is not set to RUNNING and no
        ``task.due`` event is emitted.
        """
        while self._running:
            due = await self.get_due_tasks()
            for task in due:
                # 条件任务：仅在条件满足时执行
                if task.condition and self._check_condition is not None:
                    try:
                        condition_met = await self._check_condition(task.condition)
                    except Exception as exc:
                        logger.warning("Condition check failed for task %s: %s", task.id, exc)
                        continue
                    if not condition_met:
                        continue
                await self._fire_task(task, on_due_task)
            # Calculate dynamic sleep interval based on nearest pending task
            next_wake = _POLL_INTERVAL  # default
            if self._tasks:
                pending_times = []
                for t in self._tasks.values():
                    if t.status != TaskStatus.PENDING:
                        continue
                    trigger_time = (
                        t.scheduled_time if t.trigger == TriggerKind.ONCE else t.next_run
                    )
                    if trigger_time is not None:
                        pending_times.append(trigger_time.timestamp())
                if pending_times:
                    now_ts = time.time()
                    nearest = min(pending_times)
                    # Sleep until next task is due, but cap at 60s and floor at 1s
                    next_wake = max(1.0, min(60.0, nearest - now_ts))
                elif not any(t.status == TaskStatus.RUNNING for t in self._tasks.values()):
                    # No pending tasks and nothing running — sleep longer
                    next_wake = 30.0
            await asyncio.sleep(next_wake)
            # Re-check after sleep — stop() may have been called during sleep
            if not self._running:
                break

    async def _fire_task(self, task: ScheduledTask, on_due_task: DueCallback | None) -> None:
        """Run one firing round (§5.2): RUNNING → DUE → callback → terminal.

        ONCE tasks end in COMPLETED (success) or FAILED (error, D10).  CRON
        tasks return to PENDING with ``next_run`` advanced to the next
        future occurrence in both outcomes — the consumed slot is never
        re-fired on the next poll cycle: after success delivery continues
        on the next scheduled round, after failure the error is recorded
        and delivery retries on the next scheduled round (review R1).
        """
        started = time.monotonic()
        scheduled_for = (
            task.scheduled_time if task.trigger == TriggerKind.ONCE else task.next_run
        )
        task.status = TaskStatus.RUNNING
        task.last_run = datetime.now()
        task.error = None
        await self._persist(task)
        await self._emit(
            self._make_event(task, TaskEventType.DUE, {"scheduled_for": _iso(scheduled_for)})
        )
        delivered: str | None = None
        try:
            if on_due_task is not None:
                receipt = await on_due_task(task)
                if receipt is not None:
                    delivered = str(receipt)
        except Exception as exc:
            logger.warning("Scheduled task %s failed: %s", task.id, exc)
            payload: dict[str, Any] = {
                "error": str(exc),
                "scheduled_for": _iso(scheduled_for),
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
            task.error = str(exc)
            if task.trigger == TriggerKind.ONCE:
                task.status = TaskStatus.FAILED  # D10: failure ≠ cancellation
            else:
                # The failed slot is consumed: return to PENDING and advance
                # next_run to the next future occurrence, so delivery retries
                # on the next scheduled round — not on the next poll cycle
                # (review ruling R1, aligned with recover rule 4).
                task.status = TaskStatus.PENDING
                try:
                    task.next_run = CronTrigger(task.cron_expr or "").next_after(datetime.now())
                except ValueError as adv_exc:
                    logger.warning("Cannot advance cron next_run for task %s: %s", task.id, adv_exc)
            await self._persist(task)
            await self._emit(self._make_event(task, TaskEventType.FAILED, payload))
            return

        payload = {"duration_ms": int((time.monotonic() - started) * 1000)}
        if delivered is not None:
            payload["result"] = delivered
        if task.trigger == TriggerKind.CRON:
            task.status = TaskStatus.PENDING
            try:
                task.next_run = CronTrigger(task.cron_expr or "").next_after(datetime.now())
            except ValueError as exc:
                # Unreachable for validated expressions (§6/§11); keep the
                # task pending rather than crash the loop.
                logger.warning("Cannot advance cron next_run for task %s: %s", task.id, exc)
            await self._persist(task)
        else:
            task.status = TaskStatus.COMPLETED
            await self._persist(task)
        await self._emit(self._make_event(task, TaskEventType.COMPLETED, payload))
