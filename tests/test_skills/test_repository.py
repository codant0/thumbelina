"""Tests for skill repository."""

from __future__ import annotations

import pytest

from thumbelina.skills.models import Skill
from thumbelina.skills.repository import SkillRepository


@pytest.fixture
def repo():
    """Create a SkillRepository with in-memory storage."""
    return SkillRepository(":memory:")


@pytest.fixture
def sample_skill():
    """Create a sample skill."""
    return Skill(
        id="skill-1",
        name="python_list_creation",
        description="How to create Python lists",
        trigger_conditions=["user asks about creating lists"],
        steps=["Use [] or list()"],
        version=1,
        success_rate=0.9,
    )


class TestSkillRepository:
    """Tests for the SkillRepository class."""

    def test_repository_class_exists(self):
        """SkillRepository should be importable."""
        assert SkillRepository is not None

    def test_repository_creates_instance(self):
        """Should be able to create a SkillRepository."""
        repo = SkillRepository(":memory:")
        assert repo is not None

    @pytest.mark.asyncio
    async def test_save_skill(self, repo, sample_skill):
        """Should be able to save a skill."""
        await repo.save(sample_skill)

    @pytest.mark.asyncio
    async def test_get_skill(self, repo, sample_skill):
        """Should be able to retrieve a saved skill."""
        await repo.save(sample_skill)
        result = await repo.get("skill-1")

        assert result is not None
        assert result.id == "skill-1"
        assert result.name == "python_list_creation"

    @pytest.mark.asyncio
    async def test_get_nonexistent_skill(self, repo):
        """Should return None for non-existent skill."""
        result = await repo.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_skills(self, repo, sample_skill):
        """Should be able to list all skills."""
        await repo.save(sample_skill)
        await repo.save(Skill(
            id="skill-2",
            name="another_skill",
            description="Another skill",
            trigger_conditions=[],
            steps=[],
        ))

        skills = await repo.list_all()
        assert len(skills) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, repo):
        """Should return empty list when no skills exist."""
        skills = await repo.list_all()
        assert skills == []

    @pytest.mark.asyncio
    async def test_delete_skill(self, repo, sample_skill):
        """Should be able to delete a skill."""
        await repo.save(sample_skill)
        result = await repo.delete("skill-1")

        assert result is True
        assert await repo.get("skill-1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo):
        """Should return False when deleting non-existent skill."""
        result = await repo.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_skill(self, repo, sample_skill):
        """Should be able to update a skill."""
        await repo.save(sample_skill)

        updated = Skill(
            id="skill-1",
            name="python_list_creation_v2",
            description="Updated description",
            trigger_conditions=["updated trigger"],
            steps=["updated step"],
            version=2,
            success_rate=0.95,
        )
        await repo.save(updated)

        result = await repo.get("skill-1")
        assert result.name == "python_list_creation_v2"
        assert result.version == 2

    @pytest.mark.asyncio
    async def test_search_by_name(self, repo):
        """Should be able to search skills by name."""
        await repo.save(Skill(
            id="s1", name="python_list", description="Python lists",
            trigger_conditions=[], steps=[],
        ))
        await repo.save(Skill(
            id="s2", name="python_dict", description="Python dicts",
            trigger_conditions=[], steps=[],
        ))
        await repo.save(Skill(
            id="s3", name="javascript_array", description="JS arrays",
            trigger_conditions=[], steps=[],
        ))

        results = await repo.search("python")
        assert len(results) == 2
