"""Skill data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Skill:
    """A reusable skill extracted from successful conversations.

    Attributes
    ----------
    id:
        Unique identifier for the skill.
    name:
        Short name for the skill.
    description:
        Description of what the skill does.
    trigger_conditions:
        Conditions that indicate when to use this skill.
    steps:
        Steps to execute the skill.
    version:
        Version number for tracking updates.
    success_rate:
        Success rate of this skill (0.0 to 1.0).
    created_at:
        When the skill was created.
    """

    id: str
    name: str
    description: str
    trigger_conditions: list[str]
    steps: list[str]
    version: int = 1
    success_rate: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
