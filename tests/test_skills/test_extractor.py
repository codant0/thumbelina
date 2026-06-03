"""Tests for skill extractor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.skills.extractor import SkillExtractor


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=(
        '{"name": "test_skill", "description": "A test skill",'
        ' "trigger_conditions": ["test"], "steps": ["step 1"]}'
    ))
    return provider


@pytest.fixture
def extractor(mock_llm):
    """Create a SkillExtractor with mock LLM."""
    return SkillExtractor(llm_provider=mock_llm)


class TestSkillExtractor:
    """Tests for the SkillExtractor class."""

    def test_extractor_class_exists(self):
        """SkillExtractor should be importable."""
        assert SkillExtractor is not None

    def test_extractor_requires_llm_provider(self):
        """SkillExtractor should accept an LLM provider."""
        mock_llm = MagicMock()
        ext = SkillExtractor(llm_provider=mock_llm)
        assert ext.llm_provider is mock_llm

    @pytest.mark.asyncio
    async def test_extract_skill_from_messages(self, extractor):
        """Should extract a skill from conversation messages."""
        messages = [
            {"role": "user", "content": "How do I create a Python list?"},
            {"role": "assistant", "content": "Use brackets: my_list = [1, 2, 3]"},
            {"role": "user", "content": "Thanks, that worked!"},
        ]

        skill = await extractor.extract(messages)

        assert skill is not None
        assert skill.name == "test_skill"

    @pytest.mark.asyncio
    async def test_extract_returns_none_for_empty(self, extractor):
        """Should return None for empty messages."""
        skill = await extractor.extract([])
        assert skill is None

    @pytest.mark.asyncio
    async def test_extract_returns_none_on_error(self, mock_llm):
        """Should return None when LLM raises ValueError."""
        mock_llm.chat = AsyncMock(side_effect=ValueError("LLM error"))
        ext = SkillExtractor(llm_provider=mock_llm)

        messages = [{"role": "user", "content": "test"}]
        skill = await ext.extract(messages)

        assert skill is None

    @pytest.mark.asyncio
    async def test_extract_propagates_unexpected_error(self, mock_llm):
        """Should propagate unexpected exceptions like RuntimeError."""
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("unexpected"))
        ext = SkillExtractor(llm_provider=mock_llm)

        messages = [{"role": "user", "content": "test"}]
        with pytest.raises(RuntimeError, match="unexpected"):
            await ext.extract(messages)

    @pytest.mark.asyncio
    async def test_extract_handles_invalid_json(self, mock_llm):
        """Should return None for invalid JSON response."""
        mock_llm.chat = AsyncMock(return_value="not valid json")
        ext = SkillExtractor(llm_provider=mock_llm)

        messages = [{"role": "user", "content": "test"}]
        skill = await ext.extract(messages)

        assert skill is None
