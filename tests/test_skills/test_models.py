"""Tests for skill data models."""

from __future__ import annotations

from thumbelina.skills.models import Skill


class TestSkillModel:
    """Tests for the Skill model."""

    def test_skill_class_exists(self):
        """Skill should be importable."""
        assert Skill is not None

    def test_skill_create(self):
        """Should be able to create a Skill."""
        skill = Skill(
            id="skill-1",
            name="python_list_creation",
            description="How to create Python lists",
            trigger_conditions=["user asks about creating lists"],
            steps=["Use [] or list()"],
            version=1,
            success_rate=0.9,
        )
        assert skill.id == "skill-1"
        assert skill.name == "python_list_creation"

    def test_skill_default_version(self):
        """Skill should default to version 1."""
        skill = Skill(
            id="skill-1",
            name="test",
            description="test",
            trigger_conditions=[],
            steps=[],
        )
        assert skill.version == 1

    def test_skill_default_success_rate(self):
        """Skill should default to 0.0 success rate."""
        skill = Skill(
            id="skill-1",
            name="test",
            description="test",
            trigger_conditions=[],
            steps=[],
        )
        assert skill.success_rate == 0.0
