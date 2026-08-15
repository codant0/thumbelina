"""Tests for the conversation title summarizer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.analysis.title_summarizer import TitleSummarizer


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="This is a summary of the conversation.")
    return provider


@pytest.fixture
def summarizer(mock_llm):
    """Create a TitleSummarizer with mock LLM."""
    return TitleSummarizer(llm_provider=mock_llm)


class TestTitleSummarizer:
    """Tests for the TitleSummarizer class."""

    def test_summarizer_class_exists(self):
        """TitleSummarizer should be importable."""
        assert TitleSummarizer is not None

    def test_summarizer_requires_llm_provider(self):
        """TitleSummarizer should accept an LLM provider."""
        mock_llm = MagicMock()
        s = TitleSummarizer(llm_provider=mock_llm)
        assert s.llm_provider is mock_llm

    @pytest.mark.asyncio
    async def test_generate_summary(self, summarizer, mock_llm):
        """Should generate a summary from messages."""
        messages = [
            {"role": "user", "content": "How do I create a Python list?"},
            {"role": "assistant", "content": "You can create a list with [] or list()."},
            {"role": "user", "content": "Thanks!"},
        ]

        summary = await summarizer.generate(messages)

        assert isinstance(summary, str)
        assert len(summary) > 0
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_passes_messages_to_llm(self, summarizer, mock_llm):
        """Should pass formatted messages to the LLM."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        await summarizer.generate(messages)

        call_args = mock_llm.chat.call_args[0][0]
        # Should contain the messages and a summarization prompt
        assert any("Hello" in str(m) for m in call_args)

    @pytest.mark.asyncio
    async def test_generate_empty_messages(self, summarizer):
        """Should return empty string for empty messages."""
        summary = await summarizer.generate([])
        assert summary == ""

    @pytest.mark.asyncio
    async def test_generate_handles_llm_error(self, mock_llm):
        """Should handle LLM errors gracefully."""
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))
        s = TitleSummarizer(llm_provider=mock_llm)

        messages = [{"role": "user", "content": "Hello"}]
        summary = await s.generate(messages)

        assert summary == ""

    @pytest.mark.asyncio
    async def test_generate_truncates_long_conversations(self, summarizer, mock_llm):
        """Should handle long conversations."""
        messages = [{"role": "user", "content": f"Message {i}"} for i in range(100)]

        summary = await summarizer.generate(messages)

        assert isinstance(summary, str)
