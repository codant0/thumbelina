"""Skill composition data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SkillComposition:
    """A workflow that chains multiple skills together.

    Attributes
    ----------
    id:
        Unique identifier for the composition.
    name:
        Short name for the composition.
    description:
        Description of what the composition does.
    skill_ids:
        Ordered list of skill IDs to execute in sequence.
    trigger_patterns:
        Patterns that indicate when to use this composition.
    created_at:
        When the composition was created.
    usage_count:
        Number of times this composition has been used.
    """

    id: str
    name: str
    description: str
    skill_ids: list[str]
    trigger_patterns: list[str]
    created_at: datetime = field(default_factory=datetime.now)
    usage_count: int = 0
