"""Base classes for subagent system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal


class SubagentStatus(StrEnum):
    """Status of a subagent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Subagent:
    """A subagent for executing tasks.

    Attributes
    ----------
    id:
        Unique identifier.
    task:
        Description of the task to execute.
    status:
        Current status of the agent.
    result:
        Result of the task execution.
    error:
        Error message if the task failed.
    started_at:
        Wall-clock timestamp when execution began (``run_agent``).
    finished_at:
        Wall-clock timestamp when execution reached a terminal status.
    conversation_id:
        发起该子 agent 的会话 id（``CreateSubagentTool`` 从 ContextVar
        读取）；用于把生命周期事件路由到正确的会话流。
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task: str = ""
    status: SubagentStatus = SubagentStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    conversation_id: str | None = None


SubagentEventType = Literal[
    "subagent.started",
    "subagent.completed",
    "subagent.failed",
    "subagent.cancelled",
]


@dataclass
class SubagentEvent:
    """Lifecycle event for a subagent, broadcast to listeners.

    ``started_at`` and ``finished_at`` are ISO-8601 strings so the payload
    can travel over WebSocket JSON without bespoke datetime encoders.
    ``conversation_id`` 为发起会话 id（未标注时为 ``None``），供监听方
    按会话过滤。
    """

    type: SubagentEventType
    id: str
    task: str
    status: SubagentStatus
    result: Any = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    conversation_id: str | None = None
