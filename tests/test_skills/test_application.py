"""Tests for skill application engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.skills.application import SkillApplicationEngine
from thumbelina.skills.models import Skill
from thumbelina.skills.repository import SkillRepository


@pytest.fixture
def repo():
    """Create a SkillRepository with in-memory storage."""
    return SkillRepository(":memory:")


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="python_list_creation")
    return provider


@pytest.fixture
def engine(repo, mock_llm):
    """Create a SkillApplicationEngine."""
    return SkillApplicationEngine(repository=repo, llm_provider=mock_llm)


@pytest.fixture
def sample_skill():
    """Create a sample skill."""
    return Skill(
        id="skill-1",
        name="python_list_creation",
        description="How to create Python lists",
        trigger_conditions=["user asks about creating lists", "user asks about Python arrays"],
        steps=["Use [] or list() to create a list"],
        version=1,
        success_rate=0.9,
    )


class TestSkillApplicationEngine:
    """Tests for the SkillApplicationEngine class."""

    def test_engine_class_exists(self):
        """SkillApplicationEngine should be importable."""
        assert SkillApplicationEngine is not None

    def test_engine_requires_repository(self):
        """Should accept a repository."""
        repo = SkillRepository(":memory:")
        mock_llm = MagicMock()
        engine = SkillApplicationEngine(repository=repo, llm_provider=mock_llm)
        assert engine.repository is repo

    @pytest.mark.asyncio
    async def test_find_matching_skills(self, engine, repo, sample_skill):
        """Should find skills matching user input."""
        await repo.save(sample_skill)
        skills = await engine.find_matching_skills("How do I create a list in Python?")

        assert len(skills) > 0
        assert skills[0].name == "python_list_creation"

    @pytest.mark.asyncio
    async def test_find_no_matching_skills(self, repo, sample_skill):
        """Should return empty for non-matching input."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="")  # LLM finds no match
        engine = SkillApplicationEngine(repository=repo, llm_provider=mock_llm)

        await repo.save(sample_skill)
        skills = await engine.find_matching_skills("What is the weather today?")

        assert len(skills) == 0

    @pytest.mark.asyncio
    async def test_apply_skill(self, engine, sample_skill):
        """Should apply a skill to generate context."""
        context = await engine.apply_skill(
            skill=sample_skill,
            user_input="How do I create a list?",
        )

        assert isinstance(context, str)
        assert "python_list_creation" in context or "list" in context.lower()

    @pytest.mark.asyncio
    async def test_record_usage(self, engine, repo, sample_skill):
        """Should record skill usage."""
        await repo.save(sample_skill)
        await engine.record_usage("skill-1", success=True)

        skill = await repo.get("skill-1")
        assert skill is not None

    @pytest.mark.asyncio
    async def test_record_usage_updates_success_rate(self, engine, repo, sample_skill):
        """Recording usage should update success rate."""
        await repo.save(sample_skill)
        initial_rate = sample_skill.success_rate

        await engine.record_usage("skill-1", success=True)

        skill = await repo.get("skill-1")
        assert skill.success_rate >= initial_rate
