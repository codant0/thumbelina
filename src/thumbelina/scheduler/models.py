"""Domain models for the scheduler subsystem.

Defines the value enumerations and the two core dataclasses —
:class:`ScheduledTask` (the task itself) and :class:`TaskEvent` (a
structured lifecycle event) — shared by the scheduler, its store, the
delivery dispatcher and the API layer.

See ``docs/plans/2026-08-30-event-timer-tasks-design.md`` (§3 event
model, §4 task model, D10 status enum extension).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """Status of a scheduled task.

    ``PENDING``/``RUNNING``/``COMPLETED``/``CANCELLED`` are the legacy
    members and their values are frozen; ``FAILED``/``PAUSED``/``MISSED``
    are additive extensions (design decision D10 — failure is no longer
    conflated with cancellation).
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"  # delivery failed (terminal for once tasks)
    PAUSED = "paused"  # paused (cron only; not firing, resumable)
    MISSED = "missed"  # missed (once, beyond grace; terminal)


class TriggerKind(StrEnum):
    """How a task is triggered."""

    ONCE = "once"
    CRON = "cron"


class DeliveryChannel(StrEnum):
    """Channel a task's content is delivered through."""

    WEB = "web"  # frontend WebSocket push
    WECHAT = "wechat"  # WeChat channel send_message
    QQ = "qq"  # QQ channel send_message


class TaskEventType(StrEnum):
    """Type of a structured task lifecycle event."""

    CREATED = "task.created"  # task registered (agent tool / API)
    DUE = "task.due"  # trigger due, delivery starts
    COMPLETED = "task.completed"  # delivery succeeded (cron: this round)
    FAILED = "task.failed"  # delivery failed (incl. channel errors)
    MISSED = "task.missed"  # heartbeat determined missed (beyond grace)
    CANCELLED = "task.cancelled"  # user cancellation / other termination


@dataclass
class ScheduledTask:
    """A scheduled task.

    Attributes
    ----------
    id:
        Unique identifier (auto-generated when omitted).
    description:
        Description of the task.
    trigger:
        Trigger kind: ``once`` or ``cron``.
    cron_expr:
        5-field cron expression; required when ``trigger`` is CRON.
    scheduled_time:
        For ONCE tasks: when the task should run.  For CRON tasks:
        creation baseline (may be ``None``).
    next_run:
        For CRON tasks: next fire time (the sole scheduling basis).
    last_run:
        When the task last fired.
    status:
        Current status of the task.
    channel:
        Delivery channel for the task content.
    content:
        Delivery content (message body).
    mode:
        ``notify`` (only implementation this phase) or ``prompt`` (reserved).
    condition:
        Optional condition string for condition-based tasks
        (e.g., ``"file_changed:/path/to/file"``).  When set, the task
        is only executed when the ``check_condition`` callback returns True.
    result:
        Result of the task execution.
    error:
        Error message when delivery failed.
    source:
        Where the task was created: ``agent`` / ``web`` / ``api``.
    conversation_id:
        Reserved for conversation association.
    created_at:
        Creation timestamp.
    updated_at:
        Last update timestamp.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    trigger: TriggerKind = TriggerKind.ONCE
    cron_expr: str | None = None
    scheduled_time: datetime | None = field(default_factory=datetime.now)
    next_run: datetime | None = None
    last_run: datetime | None = None
    status: TaskStatus = TaskStatus.PENDING
    channel: DeliveryChannel = DeliveryChannel.WEB
    content: str = ""
    mode: str = "notify"
    condition: str | None = None
    result: str | None = None
    error: str | None = None
    source: str = "agent"
    conversation_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass(kw_only=True)
class TaskEvent:
    """A structured task lifecycle event.

    Emitted on every task status transition and observed by subscribers
    (event log, WebSocket push); delivery itself does not go through the
    event bus (design §3).  Built keyword-only so the declared field
    order matches the design spec while ``id``/``fired_at`` still
    auto-generate.

    Attributes
    ----------
    id:
        Unique event identifier (auto-generated when omitted).
    type:
        Event type.
    task_id:
        ID of the task the event belongs to.
    fired_at:
        When the event was produced (local naive; auto-generated when omitted).
    trigger:
        Trigger kind of the originating task.
    channel:
        Delivery channel of the originating task.
    content:
        Delivery content (snapshot of the task content).
    payload:
        Type-specific extension data (error / scheduled_for / cron / result ...).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: TaskEventType
    task_id: str
    fired_at: datetime = field(default_factory=datetime.now)
    trigger: TriggerKind
    channel: DeliveryChannel
    content: str
    payload: dict[str, Any] = field(default_factory=dict)
