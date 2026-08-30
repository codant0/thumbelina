"""Periodic health inspection for the task scheduler (design §7.4).

:class:`Heartbeat` runs as its own ``asyncio.Task`` beside the scheduler's
polling loop and, every ``heartbeat_interval_seconds`` (default 30), applies
the five §7.4 inspection items:

1. **poll loop liveness** — a dead/cancelled ``_poll_task`` is re-created via
   :meth:`TaskScheduler._restart_loop` (deliberately stopped schedulers are
   left alone) and the failure is logged at error level;
2. **stale RUNNING** — a task stuck in ``RUNNING`` longer than
   ``stale_running_minutes`` is moved to ``FAILED`` (``error="stale
   running"``) with a ``task.failed`` event;
3. **cron ``next_run`` behind now** — handled with the exact recover rule 4
   semantics (§7.3): a single summary ``task.missed`` per task, ``mark``
   additionally advances ``next_run`` without firing;
4. **once tasks overdue beyond the grace window** — recover rule 1
   semantics (§7.3): ``mark`` → terminal ``MISSED`` + ``task.missed``;
   ``run`` → stays ``PENDING`` so the scan fires it immediately;
5. **event log retention** — ``task_events`` is trimmed to
   ``event_retention`` rows via :meth:`TaskStore.prune_events`.

It also maintains the ``last_heartbeat_at`` marker and a per-status
``task_counts`` snapshot for ``GET /tasks/scheduler/status`` (§8.1),
exposed through :meth:`Heartbeat.status`.

Inspection logic is concentrated in :meth:`Heartbeat._run_checks`, a pure
async method (no sleeping) that returns the names of the checks that took
action; the loop merely calls it on a fixed cadence.  Every check is
individually guarded: a failure is logged and recorded in
``status()["checks"]`` as ``"error"`` and never terminates the loop nor the
other checks (design §11).  Dispositions reuse the scheduler's own
persist-then-emit transition helpers, so ordering and event payloads match
``recover`` exactly.

See ``docs/plans/2026-08-30-event-timer-tasks-design.md``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.models import TaskEventType, TaskStatus, TriggerKind
from thumbelina.scheduler.scheduler import TaskScheduler

__all__ = ["Heartbeat"]

logger = logging.getLogger(__name__)

# Defaults when no ``config`` object is supplied (design §10).
_DEFAULT_INTERVAL_SECONDS = 30.0
_DEFAULT_MISSED_GRACE_MINUTES = 5.0
_DEFAULT_STALE_RUNNING_MINUTES = 10.0
_DEFAULT_EVENT_RETENTION = 500

# The §7.4 inspection items, in execution order; keys of status()["checks"].
CHECK_NAMES: tuple[str, ...] = (
    "poll_loop",
    "stale_running",
    "cron_next_run",
    "once_overdue",
    "event_prune",
)


def _config_value(config: Any, name: str, default: Any) -> Any:
    """Duck-typed config read: a missing object or attribute yields default."""
    return getattr(config, name, default) if config is not None else default


def _iso(value: datetime | None) -> str | None:
    """JSON-safe ISO rendering for event payloads."""
    return value.isoformat() if value is not None else None


class Heartbeat:
    """Periodic scheduler inspection (design §7.4).

    Parameters
    ----------
    scheduler:
        The :class:`TaskScheduler` to supervise.  Its polling task, working
        set, store and bus are read directly (same-package coupling); task
        dispositions reuse the scheduler's own recover transition methods so
        state transitions stay persist-first with identical event payloads.
    bus:
        Optional event bus.  Kept for interface symmetry; events are
        actually emitted through the scheduler's own bus wiring so heartbeat
        dispositions land on the same bus the scheduler was built with.
    config:
        Duck-typed settings object (T8's ``SchedulerConfig``): attributes
        ``heartbeat_interval_seconds`` (30), ``missed_grace_minutes`` (5),
        ``stale_running_minutes`` (10), ``event_retention`` (500) and
        ``missed_policy`` — all optional with these defaults.  The effective
        missed policy is the scheduler's own (the transition methods live
        there); when both are wired from the same ``SchedulerConfig`` they
        agree by construction.
    now_fn:
        Optional clock injection for tests; defaults to :func:`datetime.now`.
        Only the loop cadence and ``last_heartbeat_at`` use it — the checks
        themselves take ``now`` as a parameter (:meth:`_run_checks`).
    """

    def __init__(
        self,
        scheduler: TaskScheduler,
        bus: EventBus | None = None,
        config: Any = None,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._bus = bus
        self._now: Callable[[], datetime] = now_fn if now_fn is not None else datetime.now
        self._interval = float(
            _config_value(config, "heartbeat_interval_seconds", _DEFAULT_INTERVAL_SECONDS)
        )
        self._grace = timedelta(
            minutes=float(
                _config_value(config, "missed_grace_minutes", _DEFAULT_MISSED_GRACE_MINUTES)
            )
        )
        self._stale_running = timedelta(
            minutes=float(
                _config_value(config, "stale_running_minutes", _DEFAULT_STALE_RUNNING_MINUTES)
            )
        )
        self._event_retention = int(
            _config_value(config, "event_retention", _DEFAULT_EVENT_RETENTION)
        )
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_heartbeat_at: datetime | None = None
        self._task_counts: dict[str, int] = {}
        self._check_outcomes: dict[str, str] = dict.fromkeys(CHECK_NAMES, "idle")

    @property
    def running(self) -> bool:
        """Whether the heartbeat loop itself is active."""
        return self._running

    # ------------------------------------------------------------------
    # lifecycle (mirrors TaskScheduler.start/stop semantics)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the heartbeat loop as an independent asyncio task.

        Raises
        ------
        RuntimeError
            If the heartbeat loop is already running.
        """
        if self._running:
            raise RuntimeError("Heartbeat loop is already running")
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the heartbeat loop gracefully; idempotent."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status(self) -> dict[str, Any]:
        """Snapshot for ``GET /tasks/scheduler/status`` (§8.1).

        ``running`` is the heartbeat's own loop state — the heartbeat is the
        aliveness witness (a scheduler it supervises is running or was
        deliberately stopped).  ``task_counts`` reflects the last completed
        cycle (store ``counts()`` when available, in-memory otherwise);
        ``checks`` maps each §7.4 item to ``"idle"`` (never run), ``"ok"``,
        ``"acted"`` (disposition taken) or ``"error"``.
        """
        return {
            "running": self._running,
            "last_heartbeat_at": self._last_heartbeat_at,
            "task_counts": dict(self._task_counts),
            "checks": dict(self._check_outcomes),
        }

    # ------------------------------------------------------------------
    # loop: nothing but a cadence around _run_checks
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._run_checks(self._now())
            except Exception as exc:  # belt & braces — per-check guards below
                logger.error("Heartbeat check cycle failed: %s", exc, exc_info=True)
            await asyncio.sleep(self._interval)
            # Re-check after sleep — stop() may have been called during sleep
            if not self._running:
                break

    async def _run_checks(self, now: datetime) -> list[str]:
        """Run all §7.4 checks once at ``now``; return the ones that acted.

        Pure async (no sleeping) so tests can drive it deterministically
        with an injected ``now``.  Each check is isolated: an exception is
        logged, recorded as ``"error"`` in ``status()["checks"]``, and the
        remaining checks still run (design §11).
        """
        acted: list[str] = []
        for name, check in (
            ("poll_loop", self._check_poll_loop()),
            ("stale_running", self._check_stale_running(now)),
            ("cron_next_run", self._check_cron_next_run(now)),
            ("once_overdue", self._check_once_overdue(now)),
            ("event_prune", self._check_event_prune()),
        ):
            try:
                outcome = await check
            except Exception as exc:
                self._check_outcomes[name] = "error"
                logger.warning("Heartbeat check %s failed: %s", name, exc, exc_info=True)
                continue
            if outcome is None:
                self._check_outcomes[name] = "ok"
            else:
                self._check_outcomes[name] = "acted"
                acted.append(name)
        # Snapshot after the dispositions so the counts reflect the post-check
        # state; store failure degrades to the in-memory working set (§11).
        self._task_counts = await self._compute_task_counts()
        self._last_heartbeat_at = now
        return acted

    # ------------------------------------------------------------------
    # the five §7.4 inspection items (each returns its name when it acted)
    # ------------------------------------------------------------------

    async def _check_poll_loop(self) -> str | None:
        """Item 1: revive a dead/cancelled polling loop; ignore stopped ones."""
        sched = self._scheduler
        if not sched.running:
            return None  # never started / deliberately stopped — not ours to revive
        old = sched._poll_task
        if old is not None and not old.done():
            return None  # healthy
        if old is not None and old.done() and not old.cancelled():
            # Retrieve the exception so asyncio does not warn about it and
            # §11's "log, don't avalanche" has something concrete to show.
            exc = old.exception()
            if exc is not None:
                logger.error("Scheduler poll loop crashed: %s", exc, exc_info=exc)
        logger.error("Scheduler poll loop is dead; restarting it (heartbeat)")
        sched._restart_loop()
        return "poll_loop"

    async def _check_stale_running(self, now: datetime) -> str | None:
        """Item 2: RUNNING longer than stale_running_minutes → FAILED."""
        acted = False
        for task in await self._scheduler.list_tasks():
            if task.status != TaskStatus.RUNNING or task.last_run is None:
                continue  # no reliable start reference → leave it alone
            if now - task.last_run <= self._stale_running:
                continue
            scheduled_for = (
                task.scheduled_time if task.trigger == TriggerKind.ONCE else task.next_run
            )
            task.status = TaskStatus.FAILED
            task.error = "stale running"
            await self._scheduler._persist(task)
            await self._scheduler._emit(
                self._scheduler._make_event(
                    task,
                    TaskEventType.FAILED,
                    {"error": "stale running", "scheduled_for": _iso(scheduled_for)},
                )
            )
            logger.warning("Task %s stuck RUNNING; marked failed (stale running)", task.id)
            acted = True
        return "stale_running" if acted else None

    async def _check_cron_next_run(self, now: datetime) -> str | None:
        """Item 3: cron PENDING with next_run <= now → recover rule 4 semantics.

        Delegates to the scheduler's own ``_recover_overdue_cron`` so the
        disposition (advance + summary ``task.missed`` for ``mark``; summary
        event only for ``run``, backlog fires at most once) is identical to
        startup recovery.  PAUSED/terminal tasks are skipped: a paused task
        did not "miss" anything, and resume recomputes next_run anyway.
        """
        acted = False
        for task in await self._scheduler.list_tasks():
            if task.trigger != TriggerKind.CRON or task.status != TaskStatus.PENDING:
                continue
            if task.next_run is None or task.next_run > now:
                continue
            await self._scheduler._recover_overdue_cron(task, now)
            acted = True
        return "cron_next_run" if acted else None

    async def _check_once_overdue(self, now: datetime) -> str | None:
        """Item 4: once PENDING overdue beyond grace → recover rule 1 semantics.

        Delegates to the scheduler's ``_recover_overdue_once``: ``mark`` →
        terminal MISSED + ``task.missed``; ``run`` → untouched (stays
        PENDING, i.e. immediately due, the scan fires it — §7.3).
        """
        acted = False
        grace_deadline = now - self._grace
        for task in await self._scheduler.list_tasks():
            if task.trigger != TriggerKind.ONCE or task.status != TaskStatus.PENDING:
                continue
            if task.scheduled_time is None or task.scheduled_time > grace_deadline:
                continue
            await self._scheduler._recover_overdue_once(task)
            acted = True
        return "once_overdue" if acted else None

    async def _check_event_prune(self) -> str | None:
        """Item 5: trim task_events to event_retention (no-op under the cap)."""
        store = self._scheduler._store
        if store is None:
            return None
        pruned = await store.prune_events(keep=self._event_retention)
        if pruned:
            logger.info("Pruned %d task events over retention %d", pruned, self._event_retention)
            return "event_prune"
        return None

    async def _compute_task_counts(self) -> dict[str, int]:
        """Per-status counts: store ``counts()`` first, memory fallback (§11)."""
        store = self._scheduler._store
        if store is not None:
            try:
                return await store.counts()
            except Exception as exc:
                logger.warning("Task store counts unavailable, using memory: %s", exc)
        counts: dict[str, int] = {}
        for task in await self._scheduler.list_tasks():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts
