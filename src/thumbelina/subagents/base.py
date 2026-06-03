"""Base classes for subagent system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task: str = ""
    status: SubagentStatus = SubagentStatus.PENDING
    result: Any = None
    error: str | None = None
