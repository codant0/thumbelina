"""Tests for the user feedback system."""

from __future__ import annotations

import pytest

from thumbelina.memory.feedback_repo import Feedback, FeedbackRepository


@pytest.fixture
def repo() -> FeedbackRepository:
    """Create an in-memory FeedbackRepository for testing."""
    return FeedbackRepository(db_url="sqlite:///:memory:")


@pytest.fixture
def sample_feedback() -> Feedback:
    """Create a sample feedback record."""
    return Feedback(
        conversation_id="conv-1",
        message_index=2,
        rating=4,
        comment="Good response",
        skill_id="skill-1",
    )


# ------------------------------------------------------------------
# Model / creation tests
# ------------------------------------------------------------------


class TestFeedbackModel:
    """Tests for Feedback dataclass defaults."""

    def test_default_id_is_uuid(self) -> None:
        fb = Feedback(conversation_id="c1", message_index=0, rating=3)
        assert len(fb.id) == 36
        assert fb.id.count("-") == 4

    def test_default_fields(self) -> None:
        fb = Feedback()
        assert fb.comment is None
        assert fb.skill_id is None
        assert fb.rating == 0

    def test_explicit_fields(self, sample_feedback: Feedback) -> None:
        assert sample_feedback.conversation_id == "conv-1"
        assert sample_feedback.message_index == 2
        assert sample_feedback.rating == 4
        assert sample_feedback.comment == "Good response"
        assert sample_feedback.skill_id == "skill-1"


# ------------------------------------------------------------------
# Save / get
# ------------------------------------------------------------------


class TestSaveAndGet:
    """Tests for save and get operations."""

    @pytest.mark.asyncio
    async def test_save_and_get(
        self, repo: FeedbackRepository, sample_feedback: Feedback
    ) -> None:
        saved = await repo.save(sample_feedback)
        assert saved.id == sample_feedback.id
        assert saved.rating == 4

        fetched = await repo.get(saved.id)
        assert fetched is not None
        assert fetched.conversation_id == "conv-1"
        assert fetched.rating == 4
        assert fetched.comment == "Good response"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, repo: FeedbackRepository) -> None:
        result = await repo.get("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_updates_existing(
        self, repo: FeedbackRepository, sample_feedback: Feedback
    ) -> None:
        await repo.save(sample_feedback)
        sample_feedback.rating = 1
        sample_feedback.comment = "Changed my mind"
        updated = await repo.save(sample_feedback)

        assert updated.rating == 1
        assert updated.comment == "Changed my mind"

        fetched = await repo.get(sample_feedback.id)
        assert fetched is not None
        assert fetched.rating == 1


# ------------------------------------------------------------------
# List by conversation
# ------------------------------------------------------------------


class TestListByConversation:
    """Tests for listing feedback by conversation."""

    @pytest.mark.asyncio
    async def test_list_by_conversation(
        self, repo: FeedbackRepository
    ) -> None:
        fb1 = Feedback(conversation_id="conv-1", message_index=0, rating=3)
        fb2 = Feedback(conversation_id="conv-1", message_index=1, rating=5)
        fb3 = Feedback(conversation_id="conv-2", message_index=0, rating=2)

        await repo.save(fb1)
        await repo.save(fb2)
        await repo.save(fb3)

        results = await repo.list_by_conversation("conv-1")
        assert len(results) == 2
        # Ordered by message_index
        assert results[0].message_index == 0
        assert results[1].message_index == 1

    @pytest.mark.asyncio
    async def test_list_by_conversation_empty(
        self, repo: FeedbackRepository
    ) -> None:
        results = await repo.list_by_conversation("no-such-conv")
        assert results == []


# ------------------------------------------------------------------
# List by skill
# ------------------------------------------------------------------


class TestListBySkill:
    """Tests for listing feedback by skill."""

    @pytest.mark.asyncio
    async def test_list_by_skill(self, repo: FeedbackRepository) -> None:
        fb1 = Feedback(
            conversation_id="conv-1", message_index=0, rating=5, skill_id="s1"
        )
        fb2 = Feedback(
            conversation_id="conv-2", message_index=0, rating=3, skill_id="s1"
        )
        fb3 = Feedback(
            conversation_id="conv-3", message_index=0, rating=4, skill_id="s2"
        )
        await repo.save(fb1)
        await repo.save(fb2)
        await repo.save(fb3)

        results = await repo.list_by_skill("s1")
        assert len(results) == 2
        assert all(r.skill_id == "s1" for r in results)

    @pytest.mark.asyncio
    async def test_list_by_skill_empty(
        self, repo: FeedbackRepository
    ) -> None:
        results = await repo.list_by_skill("nonexistent")
        assert results == []


# ------------------------------------------------------------------
# Average rating
# ------------------------------------------------------------------


class TestAverageRating:
    """Tests for average rating calculation."""

    @pytest.mark.asyncio
    async def test_average_rating_all(self, repo: FeedbackRepository) -> None:
        await repo.save(Feedback(conversation_id="c1", message_index=0, rating=4))
        await repo.save(Feedback(conversation_id="c1", message_index=1, rating=5))
        await repo.save(Feedback(conversation_id="c2", message_index=0, rating=2))

        stats = await repo.get_average_rating()
        assert stats["count"] == 3
        assert stats["average_rating"] == pytest.approx(3.67, abs=0.01)

    @pytest.mark.asyncio
    async def test_average_rating_by_skill(
        self, repo: FeedbackRepository
    ) -> None:
        await repo.save(
            Feedback(
                conversation_id="c1", message_index=0, rating=5, skill_id="s1"
            )
        )
        await repo.save(
            Feedback(
                conversation_id="c2", message_index=0, rating=3, skill_id="s1"
            )
        )
        await repo.save(
            Feedback(
                conversation_id="c3", message_index=0, rating=1, skill_id="s2"
            )
        )

        stats = await repo.get_average_rating(skill_id="s1")
        assert stats["count"] == 2
        assert stats["average_rating"] == pytest.approx(4.0)
        assert stats["skill_id"] == "s1"

    @pytest.mark.asyncio
    async def test_average_rating_no_data(
        self, repo: FeedbackRepository
    ) -> None:
        stats = await repo.get_average_rating()
        assert stats["count"] == 0
        assert stats["average_rating"] == 0.0


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


class TestDelete:
    """Tests for feedback deletion."""

    @pytest.mark.asyncio
    async def test_delete_existing(
        self, repo: FeedbackRepository, sample_feedback: Feedback
    ) -> None:
        await repo.save(sample_feedback)
        assert await repo.delete(sample_feedback.id) is True
        assert await repo.get(sample_feedback.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo: FeedbackRepository) -> None:
        assert await repo.delete("no-such-id") is False


# ------------------------------------------------------------------
# List all
# ------------------------------------------------------------------


class TestListAll:
    """Tests for listing all feedback."""

    @pytest.mark.asyncio
    async def test_list_all(self, repo: FeedbackRepository) -> None:
        await repo.save(Feedback(conversation_id="c1", message_index=0, rating=3))
        await repo.save(Feedback(conversation_id="c2", message_index=0, rating=5))
        results = await repo.list_all()
        assert len(results) == 2


# ------------------------------------------------------------------
# Skill scoring integration
# ------------------------------------------------------------------


class TestSkillScoringIntegration:
    """Tests for feedback-based skill score adjustment."""

    @pytest.mark.asyncio
    async def test_adjust_score_no_feedback(self, repo: FeedbackRepository) -> None:
        """Without feedback_repo the base score is returned."""
        from thumbelina.skills.application import SkillApplicationEngine

        class _FakeRepo:
            pass

        class _FakeLLM:
            pass

        engine = SkillApplicationEngine(
            repository=_FakeRepo(),  # type: ignore[arg-type]
            llm_provider=_FakeLLM(),  # type: ignore[arg-type]
            feedback_repo=None,
        )
        result = await engine._adjust_score_by_feedback("skill-x", 0.8)
        assert result == 0.8

    @pytest.mark.asyncio
    async def test_adjust_score_positive_feedback(
        self, repo: FeedbackRepository
    ) -> None:
        """High ratings should boost the score."""

        from thumbelina.skills.application import SkillApplicationEngine

        class _FakeRepo:
            pass

        class _FakeLLM:
            pass

        engine = SkillApplicationEngine(
            repository=_FakeRepo(),  # type: ignore[arg-type]
            llm_provider=_FakeLLM(),  # type: ignore[arg-type]
            feedback_repo=repo,
        )

        # Add high-rated feedback
        await repo.save(
            Feedback(
                conversation_id="c1",
                message_index=0,
                rating=5,
                skill_id="s1",
            )
        )
        await repo.save(
            Feedback(
                conversation_id="c2",
                message_index=0,
                rating=5,
                skill_id="s1",
            )
        )

        result = await engine._adjust_score_by_feedback("s1", 0.5)
        # avg=5, count=2: adjustment = (5-3)/2 * min(2,5)/5 * 0.2 = 1.0 * 0.4 * 0.2 = 0.08
        assert result == pytest.approx(0.58, abs=0.001)

    @pytest.mark.asyncio
    async def test_adjust_score_negative_feedback(
        self, repo: FeedbackRepository
    ) -> None:
        """Low ratings should penalize the score."""
        from thumbelina.skills.application import SkillApplicationEngine

        class _FakeRepo:
            pass

        class _FakeLLM:
            pass

        engine = SkillApplicationEngine(
            repository=_FakeRepo(),  # type: ignore[arg-type]
            llm_provider=_FakeLLM(),  # type: ignore[arg-type]
            feedback_repo=repo,
        )

        await repo.save(
            Feedback(
                conversation_id="c1",
                message_index=0,
                rating=1,
                skill_id="s2",
            )
        )

        result = await engine._adjust_score_by_feedback("s2", 0.5)
        # avg=1, count=1: adjustment = (1-3)/2 * min(1,5)/5 * 0.2 = -1.0 * 0.2 * 0.2 = -0.04
        assert result == pytest.approx(0.46, abs=0.001)

    @pytest.mark.asyncio
    async def test_adjust_score_no_feedback_for_skill(
        self, repo: FeedbackRepository
    ) -> None:
        """Skills with no feedback keep their base score."""
        from thumbelina.skills.application import SkillApplicationEngine

        class _FakeRepo:
            pass

        class _FakeLLM:
            pass

        engine = SkillApplicationEngine(
            repository=_FakeRepo(),  # type: ignore[arg-type]
            llm_provider=_FakeLLM(),  # type: ignore[arg-type]
            feedback_repo=repo,
        )

        # Feedback exists for other skills but not this one
        await repo.save(
            Feedback(
                conversation_id="c1",
                message_index=0,
                rating=5,
                skill_id="other-skill",
            )
        )

        result = await engine._adjust_score_by_feedback("unrelated-skill", 0.7)
        assert result == 0.7
