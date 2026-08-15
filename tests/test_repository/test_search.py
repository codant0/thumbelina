"""Tests for conversation search functionality."""

from __future__ import annotations

import pytest

from thumbelina.repository.repository import ConversationRepository
from thumbelina.repository.search import SearchEngine


@pytest.fixture
def repo():
    """Create a repository with in-memory SQLite database."""
    return ConversationRepository("sqlite:///:memory:")


@pytest.fixture
def search_engine(repo):
    """Create a SearchEngine with the test repository."""
    return SearchEngine(repository=repo)


class TestSearchEngine:
    """Tests for the SearchEngine class."""

    def test_search_engine_class_exists(self):
        """SearchEngine should be importable."""
        assert SearchEngine is not None

    def test_search_engine_requires_repository(self):
        """SearchEngine should accept a repository."""
        repo = ConversationRepository("sqlite:///:memory:")
        engine = SearchEngine(repository=repo)
        assert engine.repository is repo

    @pytest.mark.asyncio
    async def test_keyword_search_finds_match(self, repo, search_engine):
        """Keyword search should find matching messages."""
        conv_id = await repo.create_conversation()
        await repo.add_message(conv_id, "user", "How do I learn Python?")
        await repo.add_message(conv_id, "assistant", "Start with the official tutorial.")

        results = await search_engine.keyword_search("Python")

        assert len(results) > 0
        assert any("Python" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_keyword_search_no_match(self, repo, search_engine):
        """Keyword search should return empty for no matches."""
        conv_id = await repo.create_conversation()
        await repo.add_message(conv_id, "user", "Hello world")

        results = await search_engine.keyword_search("Python")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_keyword_search_returns_message_details(self, repo, search_engine):
        """Keyword search results should include message details."""
        conv_id = await repo.create_conversation()
        await repo.add_message(conv_id, "user", "Test Python query")

        results = await search_engine.keyword_search("Python")

        assert len(results) > 0
        assert "id" in results[0]
        assert "conversation_id" in results[0]
        assert "role" in results[0]
        assert "content" in results[0]

    @pytest.mark.asyncio
    async def test_keyword_search_case_insensitive(self, repo, search_engine):
        """Keyword search should be case insensitive."""
        conv_id = await repo.create_conversation()
        await repo.add_message(conv_id, "user", "PYTHON programming")

        results = await search_engine.keyword_search("python")

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_keyword_search_with_limit(self, repo, search_engine):
        """Keyword search should respect limit parameter."""
        conv_id = await repo.create_conversation()
        for i in range(10):
            await repo.add_message(conv_id, "user", f"Python message {i}")

        results = await search_engine.keyword_search("Python", limit=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_keyword_search_across_conversations(self, repo, search_engine):
        """Keyword search should find matches across conversations."""
        conv1 = await repo.create_conversation()
        conv2 = await repo.create_conversation()
        await repo.add_message(conv1, "user", "Python is great")
        await repo.add_message(conv2, "user", "I love Python too")

        results = await search_engine.keyword_search("Python")

        conv_ids = {r["conversation_id"] for r in results}
        assert len(conv_ids) == 2
