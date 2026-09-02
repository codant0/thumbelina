"""Task and subagent API routes.

The task endpoints (design ``docs/plans/2026-08-30-event-timer-tasks-design.md``
§8.1) read the scheduler wiring from ``app.state`` — ``task_scheduler``,
``task_store`` and ``task_heartbeat``, all assembled in ``api/app.py``'s
lifespan.  When the scheduler is disabled or failed to initialize those
attributes are ``None`` and the routes degrade (empty list / 503) instead of
failing the service (design §11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.deps import get_agent
from thumbelina.scheduler.cron import validate_cron
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TriggerKind,
)
from thumbelina.scheduler.scheduler import TaskScheduler
from thumbelina.scheduler.store import TaskStore

router = APIRouter(tags=["tasks"])

# Clamp window for GET /tasks/events (design §8.1: default 50, max 200).
_EVENTS_LIMIT_DEFAULT = 50
_EVENTS_LIMIT_MIN = 1
_EVENTS_LIMIT_MAX = 200

# Pause/resume are only legal for cron tasks in the matching state; the
# scheduler's own pause_task/resume_task enforce this and return False.


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------


def _serialize_task(task: ScheduledTask) -> dict[str, Any]:
    """Serialize a task for REST responses.

    The legacy four keys (``id``/``description``/``scheduled_time``/``status``)
    are kept verbatim for existing consumers; the §8.1 fields are additive.
    ``scheduled_time`` is ``null`` for cron tasks (creation baseline is not
    persisted there) and ``cron``/``next_run`` are ``null`` for once tasks.
    """
    return {
        "id": task.id,
        "description": task.description,
        "scheduled_time": (
            task.scheduled_time.isoformat() if task.scheduled_time is not None else None
        ),
        "status": task.status.value,
        "trigger": task.trigger.value,
        "cron": task.cron_expr,
        "next_run": task.next_run.isoformat() if task.next_run is not None else None,
        "last_run": task.last_run.isoformat() if task.last_run is not None else None,
        "channel": task.channel.value,
        "content": task.content,
        "mode": task.mode,
        "source": task.source,
        "error": task.error,
        "conversation_id": task.conversation_id,
    }


def serialize_task_event(event: TaskEvent) -> dict[str, Any]:
    """Serialize an event for REST responses and the ``task_event`` WS frame (§8.2).

    Shared with ``api/app.py``'s WebPushHook so the WebSocket frame and the
    event-log REST view are byte-identical.
    """
    return {
        "id": event.id,
        "type": event.type.value,
        "task_id": event.task_id,
        "fired_at": event.fired_at.isoformat(),
        "trigger": event.trigger.value,
        "channel": event.channel.value,
        "content": event.content,
        "payload": event.payload,
    }


# ---------------------------------------------------------------------------
# component lookup helpers
# ---------------------------------------------------------------------------


def _get_scheduler(request: Request) -> TaskScheduler | None:
    """The wired scheduler, or ``None`` when disabled / failed to assemble."""
    return getattr(request.app.state, "task_scheduler", None)


def _get_store(request: Request) -> TaskStore | None:
    """The wired task store, or ``None`` when disabled / failed to assemble."""
    return getattr(request.app.state, "task_store", None)


# ---------------------------------------------------------------------------
# subagents (unchanged)
# ---------------------------------------------------------------------------


@router.get("/subagents")
async def list_subagents(
    agent: ThumbelinaAgent = Depends(get_agent),
) -> list[dict[str, Any]]:
    """List all subagents with their status."""
    if agent.subagent_manager:
        agents = await agent.subagent_manager.list_agents()
        return [
            {
                "id": a.id,
                "task": a.task,
                "status": a.status.value,
                "result": a.result,
            }
            for a in agents
        ]
    return []


@router.post("/subagents/{agent_id}/cancel")
async def cancel_subagent(
    agent_id: str,
    agent: ThumbelinaAgent = Depends(get_agent),
) -> dict[str, bool]:
    """Cancel a running subagent."""
    if not agent.subagent_manager:
        raise HTTPException(status_code=404, detail="Subagent manager not available")
    cancelled = await agent.subagent_manager.cancel_agent(agent_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Subagent not found")
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# tasks (design §8.1)
# ---------------------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(request: Request) -> list[dict[str, Any]]:
    """List all scheduled tasks (legacy 4 keys + §8.1 fields)."""
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return []
    tasks = await scheduler.list_tasks()
    return [_serialize_task(t) for t in tasks]


class TaskCreateRequest(BaseModel):
    """Body of ``POST /tasks`` (design §8.1)."""

    description: str = Field(min_length=1)
    trigger: Literal["once", "cron"] = "once"
    scheduled_time: datetime | None = None
    cron: str | None = None
    channel: Literal["web", "wechat", "qq"] | None = None
    content: str | None = None
    # §5.4: mode 默认 prompt——任务到期后由 AI 执行内容并把回复写入会话;
    # 纯提醒类任务显式传 "notify"(content 原样交付,不跑 agent)。
    mode: Literal["prompt", "notify"] = Field(
        default="prompt",
        description=(
            "Execution mode when the task fires: prompt=the AI performs the "
            "task content and writes the reply into the conversation "
            "(default); notify=the content is delivered as-is as a reminder "
            "without running the AI."
        ),
    )
    conversation_id: str | None = Field(
        default=None,
        description="prompt 模式回复写入的会话;缺省由调度链路决定",
    )

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value.strip()


@router.post("/tasks", status_code=201)
async def create_task(request: Request, body: TaskCreateRequest) -> dict[str, Any]:
    """Create a scheduled task from the web UI (source=``web``).

    Validation failures return 422: a blank description, a ``once`` task
    without a parseable ``scheduled_time``, a ``cron`` task whose expression
    does not pass :func:`validate_cron` (T5 ruling — ``add_task`` does not
    validate expressions for tasks without a caller-supplied ``next_run``),
    or an unknown channel.

    A tz-aware ``scheduled_time`` (e.g. a JS ``toISOString()`` value ending
    in ``Z``) is normalized to local naive time: the whole scheduling
    pipeline compares against naive :func:`datetime.now`, and an aware value
    would raise ``TypeError`` inside ``get_due_tasks`` and kill the poll
    loop (final review C1).
    """
    scheduler = _get_scheduler(request)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")

    scheduled_time: datetime | None = None
    cron_expr: str | None = None
    if body.trigger == "once":
        if body.scheduled_time is None:
            raise HTTPException(
                status_code=422,
                detail="scheduled_time is required for once tasks",
            )
        scheduled_time = body.scheduled_time
        if scheduled_time.tzinfo is not None:
            # tz-aware input (JS `toISOString()` "…Z") → local naive, the
            # project-wide datetime.now() convention (final review C1).
            scheduled_time = scheduled_time.astimezone().replace(tzinfo=None)
    else:
        if not body.cron:
            raise HTTPException(
                status_code=422,
                detail="cron expression is required for cron tasks",
            )
        error = validate_cron(body.cron)
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        cron_expr = body.cron

    config = getattr(request.app.state, "config", None)
    default_channel = getattr(getattr(config, "scheduler", None), "default_channel", "web")
    task = ScheduledTask(
        description=body.description,
        trigger=TriggerKind(body.trigger),
        cron_expr=cron_expr,
        scheduled_time=scheduled_time,
        channel=DeliveryChannel(body.channel or default_channel),
        content=body.content or body.description,
        mode=body.mode,
        conversation_id=body.conversation_id,
        source="web",
    )
    try:
        await scheduler.add_task(task)
    except ValueError as exc:
        # add_task's own cron fallback (never-firing expressions, …).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_task(task)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict[str, bool]:
    """Cancel a scheduled task (PAUSED cron tasks included)."""
    scheduler = _get_scheduler(request)
    if scheduler is None:
        raise HTTPException(status_code=404, detail="Scheduler not available")
    cancelled = await scheduler.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"cancelled": True}


async def _pause_or_resume(request: Request, task_id: str, *, resume: bool) -> dict[str, Any]:
    """Shared pause/resume handler: 404 unknown, 409 illegal state (§8.1)."""
    scheduler = _get_scheduler(request)
    if scheduler is None:
        raise HTTPException(status_code=404, detail="Scheduler not available")
    # Distinguish 404 (unknown id) from 409 (illegal state): look the task
    # up first, then let the scheduler's own state machine decide.
    task = await scheduler.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    ok = await (scheduler.resume_task(task_id) if resume else scheduler.pause_task(task_id))
    if not ok:
        action = "resumed" if resume else "paused"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task cannot be {action}: only cron tasks in the matching "
                "state (PENDING before pause, PAUSED before resume) qualify"
            ),
        )
    updated = await scheduler.get_task(task_id)
    if updated is None:  # pragma: no cover — we just found it above
        raise HTTPException(status_code=404, detail="Task not found")
    return _serialize_task(updated)


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str, request: Request) -> dict[str, Any]:
    """Pause a PENDING cron task; it will not fire until resumed."""
    return await _pause_or_resume(request, task_id, resume=False)


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, request: Request) -> dict[str, Any]:
    """Resume a PAUSED cron task, recomputing its next fire time."""
    return await _pause_or_resume(request, task_id, resume=True)


@router.get("/tasks/events")
async def list_task_events(
    request: Request,
    limit: int = Query(default=_EVENTS_LIMIT_DEFAULT),
) -> list[dict[str, Any]]:
    """Newest-first task lifecycle events (§8.2 shape), ``limit`` clamped to 1..200."""
    scheduler = _get_scheduler(request)
    store = _get_store(request)
    if scheduler is None or store is None:
        raise HTTPException(status_code=503, detail="Task event log not available")
    clamped = max(_EVENTS_LIMIT_MIN, min(_EVENTS_LIMIT_MAX, limit))
    events = await store.list_events(limit=clamped)
    return [serialize_task_event(e) for e in events]


@router.get("/tasks/scheduler/status")
async def scheduler_status(request: Request) -> dict[str, Any]:
    """Scheduler aliveness snapshot from the Heartbeat (§8.1)."""
    heartbeat = getattr(request.app.state, "task_heartbeat", None)
    if heartbeat is None:
        raise HTTPException(status_code=503, detail="Scheduler heartbeat not available")
    status: dict[str, Any] = heartbeat.status()
    return status


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict[str, Any]:
    """Single task detail for the UI's click-to-inspect view.

    Declared after the literal ``/tasks/events`` route on purpose: FastAPI
    matches routes in declaration order and ``{task_id}`` would otherwise
    swallow it.  Unlike the list endpoint this also returns ``result`` (the
    last successful run's output, persisted by the scheduler on completion)
    plus ``created_at``/``updated_at`` — the list stays lean because the
    UI polls it every 10s.
    """
    scheduler = _get_scheduler(request)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    task = await scheduler.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    data = _serialize_task(task)
    data["result"] = task.result
    data["created_at"] = task.created_at.isoformat()
    data["updated_at"] = task.updated_at.isoformat()
    return data


@router.get("/plugins/dependencies")
async def get_plugin_dependencies(request: Request) -> dict[str, Any]:
    """Return the plugin dependency graph and load order.

    Requires a ``PluginManager`` to be available on ``app.state``.
    Returns 404 if the plugin manager has not been initialised.
    """
    plugin_manager = getattr(request.app.state, "plugin_manager", None)
    if plugin_manager is None:
        raise HTTPException(
            status_code=404,
            detail="Plugin manager not available",
        )
    graph: dict[str, Any] = plugin_manager.get_dependency_graph()
    return graph
