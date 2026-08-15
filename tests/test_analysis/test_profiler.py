"""Tests for thumbelina.analysis.profiler module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.analysis.profiler import UserProfiler
from thumbelina.repository.user_profile_repo import UserProfileRepository


@pytest.fixture
def repo():
    """Create a UserProfileRepository with in-memory SQLite database."""
    return UserProfileRepository("sqlite:///:memory:")


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock()
    return provider


@pytest.fixture
def profiler(mock_llm_provider, repo):
    """Create a UserProfiler with mock LLM and real repo."""
    return UserProfiler(llm_provider=mock_llm_provider, profile_repo=repo)


class TestUserProfiler:
    """Tests for the UserProfiler class."""

    @pytest.mark.asyncio
    async def test_analyze_conversation_empty_messages(self, profiler):
        result = await profiler.analyze_conversation([])
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conversation_success(self, profiler, mock_llm_provider):
        mock_llm_provider.chat.return_value = """{
            "communication_style": "technical",
            "expertise_level": "advanced",
            "preferences": [
                {"category": "language", "key": "programming", "value": "Python", "confidence": 0.9}
            ],
            "topics_of_interest": ["machine learning", "data science"]
        }"""

        messages = [
            {"role": "user", "content": "How do I implement a neural network in PyTorch?"},
            {"role": "assistant", "content": "You can use torch.nn.Module..."},
        ]

        result = await profiler.analyze_conversation(messages, user_id="user1")
        assert result is not None
        assert result["communication_style"] == "technical"
        assert result["expertise_level"] == "advanced"
        assert len(result["preferences"]) == 1
        assert len(result["topics_of_interest"]) == 2

        # Verify persistence
        profile = await profiler.profile_repo.get_profile("user1")
        assert profile is not None
        assert profile["communication_style"] == "technical"
        assert profile["expertise_level"] == "advanced"

        prefs = await profiler.profile_repo.get_preferences("user1")
        assert len(prefs) >= 1  # at least the language pref + topics

    @pytest.mark.asyncio
    async def test_analyze_conversation_invalid_json(self, profiler, mock_llm_provider):
        mock_llm_provider.chat.return_value = "This is not valid JSON"

        messages = [{"role": "user", "content": "Hello"}]
        result = await profiler.analyze_conversation(messages)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conversation_llm_error(self, profiler, mock_llm_provider):
        mock_llm_provider.chat.side_effect = Exception("LLM error")

        messages = [{"role": "user", "content": "Hello"}]
        result = await profiler.analyze_conversation(messages)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conversation_persists_topics(self, profiler, mock_llm_provider):
        mock_llm_provider.chat.return_value = """{
            "communication_style": "casual",
            "expertise_level": "intermediate",
            "preferences": [],
            "topics_of_interest": ["Python", "web development"]
        }"""

        messages = [{"role": "user", "content": "I like Python web development"}]
        await profiler.analyze_conversation(messages, user_id="user1")

        prefs = await profiler.profile_repo.get_preferences("user1", category="topic")
        topic_values = {p["value"] for p in prefs}
        assert "Python" in topic_values
        assert "web development" in topic_values

    @pytest.mark.asyncio
    async def test_get_user_context_no_profile(self, profiler):
        context = await profiler.get_user_context("nonexistent")
        assert context is None

    @pytest.mark.asyncio
    async def test_get_user_context_default_profile_no_prefs(self, profiler):
        # Create a default profile with no preferences
        await profiler.profile_repo.get_or_create_profile("user1")
        context = await profiler.get_user_context("user1")
        # Default casual profile with no prefs should return None
        assert context is None

    @pytest.mark.asyncio
    async def test_get_user_context_with_profile(self, profiler):
        await profiler.profile_repo.get_or_create_profile("user1")
        await profiler.profile_repo.update_profile(
            "user1", communication_style="formal", expertise_level="advanced"
        )
        await profiler.profile_repo.upsert_preference(
            "user1", "topic", "interest_0", "machine learning", 0.8
        )

        context = await profiler.get_user_context("user1")
        assert context is not None
        assert "formal" in context
        assert "advanced" in context
        assert "machine learning" in context

    @pytest.mark.asyncio
    async def test_get_user_context_with_multiple_preferences(self, profiler):
        await profiler.profile_repo.get_or_create_profile("user1")
        await profiler.profile_repo.update_profile(
            "user1", communication_style="technical", expertise_level="advanced"
        )
        await profiler.profile_repo.upsert_preference("user1", "topic", "interest_0", "Python", 0.9)
        await profiler.profile_repo.upsert_preference(
            "user1", "language", "preferred", "English", 0.7
        )

        context = await profiler.get_user_context("user1")
        assert context is not None
        assert "technical" in context
        assert "Python" in context
        assert "English" in context

    @pytest.mark.asyncio
    async def test_get_user_context_error_handling(self, mock_llm_provider, repo):
        # Create a profiler with a broken repo
        broken_repo = MagicMock()
        broken_repo.get_profile = AsyncMock(side_effect=Exception("DB error"))
        profiler = UserProfiler(llm_provider=mock_llm_provider, profile_repo=broken_repo)

        context = await profiler.get_user_context("user1")
        assert context is None

    @pytest.mark.asyncio
    async def test_update_profile_creates_if_not_exists(self, profiler):
        result = await profiler.update_profile(
            "user1", communication_style="formal", expertise_level="advanced"
        )
        assert result is not None
        assert result["communication_style"] == "formal"
        assert result["expertise_level"] == "advanced"

    @pytest.mark.asyncio
    async def test_update_profile_existing(self, profiler):
        await profiler.profile_repo.get_or_create_profile("user1")
        result = await profiler.update_profile("user1", communication_style="technical")
        assert result is not None
        assert result["communication_style"] == "technical"

    @pytest.mark.asyncio
    async def test_update_profile_error_handling(self, mock_llm_provider, repo):
        broken_repo = MagicMock()
        broken_repo.get_or_create_profile = AsyncMock(side_effect=Exception("DB error"))
        profiler = UserProfiler(llm_provider=mock_llm_provider, profile_repo=broken_repo)

        result = await profiler.update_profile("user1", communication_style="formal")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conversation_updates_existing_profile(self, profiler, mock_llm_provider):
        # Create initial profile
        await profiler.profile_repo.get_or_create_profile("user1")
        await profiler.profile_repo.update_profile(
            "user1", communication_style="casual", expertise_level="beginner"
        )

        # Analyze a technical conversation
        mock_llm_provider.chat.return_value = """{
            "communication_style": "technical",
            "expertise_level": "advanced",
            "preferences": [],
            "topics_of_interest": []
        }"""

        messages = [{"role": "user", "content": "Explain async/await in Python"}]
        await profiler.analyze_conversation(messages, user_id="user1")

        profile = await profiler.profile_repo.get_profile("user1")
        assert profile["communication_style"] == "technical"
        assert profile["expertise_level"] == "advanced"
