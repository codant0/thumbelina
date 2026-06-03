"""Tests for skill composition model, repository, and engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.skills.composition import SkillComposition
from thumbelina.skills.composition_engine import CompositionEngine
from thumbelina.skills.composition_repo import CompositionRepository
from thumbelina.skills.models import Skill
from thumbelina.skills.repository import SkillRepository


@pytest.fixture
def comp_repo():
    """Create a CompositionRepository with in-memory storage."""
    return CompositionRepository(":memory:")


@pytest.fixture
def skill_repo():
    """Create a SkillRepository with in-memory storage."""
    return SkillRepository(":memory:")


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="step result")
    return provider


@pytest.fixture
def engine(comp_repo, skill_repo, mock_llm):
    """Create a CompositionEngine."""
    return CompositionEngine(
        composition_repo=comp_repo,
        skill_repo=skill_repo,
        llm_provider=mock_llm,
    )


@pytest.fixture
def sample_skills():
    """Create sample skills for testing."""
    return [
        Skill(
            id="skill-1",
            name="read_file",
            description="Read a file from disk",
            trigger_conditions=["read file", "load file"],
            steps=["Open the file", "Read contents"],
            version=1,
            success_rate=0.9,
        ),
        Skill(
            id="skill-2",
            name="analyze_content",
            description="Analyze text content",
            trigger_conditions=["analyze", "summarize text"],
            steps=["Parse the text", "Extract key points"],
            version=1,
            success_rate=0.8,
        ),
        Skill(
            id="skill-3",
            name="write_report",
            description="Write a formatted report",
            trigger_conditions=["write report", "generate report"],
            steps=["Format the output", "Save to file"],
            version=1,
            success_rate=0.85,
        ),
    ]


# ---- Model Tests ----


class TestSkillCompositionModel:
    """Tests for the SkillComposition dataclass."""

    def test_composition_creation(self):
        """Should create a composition with required fields."""
        comp = SkillComposition(
            id="comp-1",
            name="test_workflow",
            description="A test workflow",
            skill_ids=["s1", "s2"],
            trigger_patterns=["test workflow"],
        )
        assert comp.id == "comp-1"
        assert comp.name == "test_workflow"
        assert comp.skill_ids == ["s1", "s2"]
        assert comp.trigger_patterns == ["test workflow"]
        assert comp.usage_count == 0

    def test_composition_defaults(self):
        """Should have sensible defaults."""
        comp = SkillComposition(
            id="comp-2",
            name="minimal",
            description="minimal composition",
            skill_ids=[],
            trigger_patterns=[],
        )
        assert comp.usage_count == 0
        assert comp.created_at is not None


# ---- Repository Tests ----


class TestCompositionRepository:
    """Tests for the CompositionRepository."""

    @pytest.mark.asyncio
    async def test_save_and_get(self, comp_repo):
        """Should save and retrieve a composition."""
        comp = SkillComposition(
            id="comp-1",
            name="workflow",
            description="A workflow",
            skill_ids=["s1", "s2"],
            trigger_patterns=["trigger1"],
        )
        await comp_repo.save(comp)
        retrieved = await comp_repo.get("comp-1")

        assert retrieved is not None
        assert retrieved.name == "workflow"
        assert retrieved.skill_ids == ["s1", "s2"]
        assert retrieved.trigger_patterns == ["trigger1"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, comp_repo):
        """Should return None for non-existent ID."""
        result = await comp_repo.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all(self, comp_repo):
        """Should list all saved compositions."""
        for i in range(3):
            comp = SkillComposition(
                id=f"comp-{i}",
                name=f"workflow-{i}",
                description=f"workflow {i}",
                skill_ids=[f"s{i}"],
                trigger_patterns=[f"trigger-{i}"],
            )
            await comp_repo.save(comp)

        all_comps = await comp_repo.list_all()
        assert len(all_comps) == 3

    @pytest.mark.asyncio
    async def test_delete(self, comp_repo):
        """Should delete a composition."""
        comp = SkillComposition(
            id="comp-del",
            name="to_delete",
            description="will be deleted",
            skill_ids=["s1"],
            trigger_patterns=[],
        )
        await comp_repo.save(comp)
        assert await comp_repo.delete("comp-del") is True
        assert await comp_repo.get("comp-del") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, comp_repo):
        """Should return False when deleting non-existent composition."""
        assert await comp_repo.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_search_by_trigger(self, comp_repo):
        """Should search compositions by trigger pattern."""
        comp = SkillComposition(
            id="comp-search",
            name="data_pipeline",
            description="Process data",
            skill_ids=["s1"],
            trigger_patterns=["process data", "data pipeline"],
        )
        await comp_repo.save(comp)

        results = await comp_repo.search_by_trigger("data")
        assert len(results) >= 1
        assert any(r.id == "comp-search" for r in results)

    @pytest.mark.asyncio
    async def test_increment_usage(self, comp_repo):
        """Should increment usage count."""
        comp = SkillComposition(
            id="comp-usage",
            name="used_workflow",
            description="A used workflow",
            skill_ids=["s1"],
            trigger_patterns=[],
            usage_count=0,
        )
        await comp_repo.save(comp)

        await comp_repo.increment_usage("comp-usage")
        await comp_repo.increment_usage("comp-usage")

        retrieved = await comp_repo.get("comp-usage")
        assert retrieved is not None
        assert retrieved.usage_count == 2

    @pytest.mark.asyncio
    async def test_update_existing(self, comp_repo):
        """Should update an existing composition on save."""
        comp = SkillComposition(
            id="comp-update",
            name="original",
            description="original desc",
            skill_ids=["s1"],
            trigger_patterns=["old trigger"],
        )
        await comp_repo.save(comp)

        comp.name = "updated"
        comp.trigger_patterns = ["new trigger"]
        await comp_repo.save(comp)

        retrieved = await comp_repo.get("comp-update")
        assert retrieved is not None
        assert retrieved.name == "updated"
        assert retrieved.trigger_patterns == ["new trigger"]


# ---- Engine Tests ----


class TestCompositionEngine:
    """Tests for the CompositionEngine."""

    @pytest.mark.asyncio
    async def test_create_composition(self, engine):
        """Should create a composition via the engine."""
        comp = await engine.create_composition(
            skill_ids=["s1", "s2"],
            name="test_comp",
            description="test composition",
            trigger_patterns=["test pattern"],
        )
        assert comp.name == "test_comp"
        assert comp.skill_ids == ["s1", "s2"]

        # Verify it was persisted
        retrieved = await engine.composition_repo.get(comp.id)
        assert retrieved is not None

    @pytest.mark.asyncio
    async def test_match_composition_by_trigger(self, engine, skill_repo, sample_skills):
        """Should match composition by trigger pattern."""
        for skill in sample_skills:
            await skill_repo.save(skill)

        await engine.create_composition(
            skill_ids=["skill-1", "skill-2"],
            name="read_and_analyze",
            description="Read a file and analyze it",
            trigger_patterns=["read and analyze", "analyze file"],
        )

        result = await engine.match_composition("Please analyze file content")
        assert result is not None
        assert result.name == "read_and_analyze"

    @pytest.mark.asyncio
    async def test_match_composition_by_name(self, engine):
        """Should match composition by name when triggers don't match."""
        await engine.create_composition(
            skill_ids=["s1"],
            name="data_pipeline",
            description="Process data",
        )

        result = await engine.match_composition("Run the data_pipeline workflow")
        assert result is not None
        assert result.name == "data_pipeline"

    @pytest.mark.asyncio
    async def test_match_composition_no_match(self, engine):
        """Should return None when no composition matches."""
        await engine.create_composition(
            skill_ids=["s1"],
            name="specific_workflow",
            description="Very specific",
            trigger_patterns=["very specific trigger"],
        )

        result = await engine.match_composition("do something completely different")
        assert result is None

    @pytest.mark.asyncio
    async def test_match_empty_repo(self, engine):
        """Should return None when no compositions exist."""
        result = await engine.match_composition("anything")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_composition(self, engine, skill_repo, sample_skills, mock_llm):
        """Should execute a composition by chaining skills."""
        for skill in sample_skills:
            await skill_repo.save(skill)

        comp = await engine.create_composition(
            skill_ids=["skill-1", "skill-2", "skill-3"],
            name="full_pipeline",
            description="Full processing pipeline",
        )

        result = await engine.execute_composition(comp, "test input")
        assert isinstance(result, str)
        assert "步骤 1" in result
        assert "步骤 2" in result
        assert "步骤 3" in result
        # LLM should have been called for each skill
        assert mock_llm.chat.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_composition_increments_usage(self, engine, skill_repo, sample_skills):
        """Executing a composition should increment its usage count."""
        for skill in sample_skills:
            await skill_repo.save(skill)

        comp = await engine.create_composition(
            skill_ids=["skill-1"],
            name="simple",
            description="Simple workflow",
        )

        await engine.execute_composition(comp, "input")
        await engine.execute_composition(comp, "input")

        updated = await engine.composition_repo.get(comp.id)
        assert updated is not None
        assert updated.usage_count == 2

    @pytest.mark.asyncio
    async def test_execute_composition_with_missing_skill(self, engine, skill_repo):
        """Should handle missing skills gracefully."""
        # Only save one of two referenced skills
        await skill_repo.save(
            Skill(
                id="exists",
                name="existing_skill",
                description="exists",
                trigger_conditions=[],
                steps=["step"],
            )
        )

        comp = await engine.create_composition(
            skill_ids=["exists", "missing-skill"],
            name="partial",
            description="Has a missing skill",
        )

        result = await engine.execute_composition(comp, "input")
        assert "existing_skill" in result
        # Should still produce output for the valid skill

    @pytest.mark.asyncio
    async def test_execute_composition_all_skills_missing(self, engine, skill_repo):
        """Should handle case where all skills are missing."""
        comp = await engine.create_composition(
            skill_ids=["nonexistent-1", "nonexistent-2"],
            name="empty",
            description="All skills missing",
        )

        result = await engine.execute_composition(comp, "input")
        assert "no valid skills" in result.lower() or "没有" in result

    @pytest.mark.asyncio
    async def test_suggest_compositions(self, engine, skill_repo, sample_skills, mock_llm):
        """Should suggest compositions from conversation history."""
        import json

        for skill in sample_skills:
            await skill_repo.save(skill)

        mock_llm.chat = AsyncMock(
            return_value=json.dumps(
                {
                    "suggestions": [
                        {
                            "name": "file_analysis_workflow",
                            "description": "Read and analyze files",
                            "skill_names": ["read_file", "analyze_content"],
                            "trigger_patterns": ["analyze this file"],
                        }
                    ]
                }
            )
        )

        history = [
            {"role": "user", "content": "Read this file and analyze it"},
            {"role": "assistant", "content": "I'll read the file first..."},
        ]

        suggestions = await engine.suggest_compositions(history)
        assert len(suggestions) == 1
        assert suggestions[0]["name"] == "file_analysis_workflow"

    @pytest.mark.asyncio
    async def test_suggest_compositions_no_skills(self, engine, skill_repo, mock_llm):
        """Should return empty suggestions when no skills exist."""
        history = [{"role": "user", "content": "test"}]
        suggestions = await engine.suggest_compositions(history)
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_suggest_compositions_llm_failure(self, engine, skill_repo, sample_skills):
        """Should handle LLM failure gracefully during suggestion."""
        for skill in sample_skills:
            await skill_repo.save(skill)

        # Make LLM raise an exception
        mock_llm_fail = MagicMock()
        mock_llm_fail.chat = AsyncMock(side_effect=Exception("LLM error"))
        engine.llm_provider = mock_llm_fail

        history = [{"role": "user", "content": "test"}]
        suggestions = await engine.suggest_compositions(history)
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_execute_stops_on_skill_failure(self, engine, skill_repo, mock_llm):
        """Should stop execution when a skill step fails."""
        await skill_repo.save(
            Skill(
                id="fail-skill",
                name="failing_skill",
                description="This will fail",
                trigger_conditions=[],
                steps=["do something"],
            )
        )

        # Make the second call fail
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise Exception("LLM failure")
            return "first step done"

        mock_llm.chat = AsyncMock(side_effect=side_effect)

        comp = await engine.create_composition(
            skill_ids=["fail-skill", "fail-skill"],
            name="will_fail",
            description="Fails on second step",
        )

        result = await engine.execute_composition(comp, "input")
        assert "执行失败" in result
