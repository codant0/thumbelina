"""Strategy 2: full summary — replace the droppable history with one summary.

Behaviour per design doc 四.5.3: everything between the protected boundaries
is handed to :class:`~thumbelina.agent.compression.summarizer_context.ContextSummarizer`
and replaced by a single summary ``SystemMessage``. The boundaries match
:class:`~thumbelina.agent.compression.sliding_window.SlidingWindowCompressor`:

- the leading run of ``SystemMessage`` units (session head: role prompt +
  first-turn user profile) is kept verbatim;
- the final deletion unit (the current turn's input) is kept verbatim.

When summarization fails (LLM error, empty result, or no budget left for the
summary) the strategy degrades to pure deletion so compression never blocks
a conversation.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from thumbelina.agent.compression.base import (
    LOW_WATERMARK,
    ContextCompressor,
    estimate_messages_tokens,
    flatten_units,
    group_deletion_units,
    leading_system_unit_count,
)
from thumbelina.agent.compression.sliding_window import SlidingWindowCompressor
from thumbelina.agent.compression.summarizer_context import (
    ContextSummarizer,
    build_summary_message,
)
from thumbelina.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class FullSummaryCompressor(ContextCompressor):
    """Summarize the old history into one message, keep head and current turn."""

    name = "full_summary"

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._summarizer = ContextSummarizer(llm_provider)

    @property
    def llm_provider(self) -> LLMProvider | None:
        """LLM provider used for summarization (kept in sync on hot-swap)."""
        return self._summarizer.llm_provider

    @llm_provider.setter
    def llm_provider(self, value: LLMProvider | None) -> None:
        self._summarizer.llm_provider = value

    async def compress(
        self, messages: Sequence[BaseMessage], window_tokens: int
    ) -> list[BaseMessage]:
        """Summarize the droppable middle of *messages* into one message."""
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_deletion_units(messages)
        head_count = leading_system_unit_count(units)

        # The final unit carries the current turn's input; it must survive.
        # With nothing between head and tail there is nothing to compress.
        if len(units) <= head_count + 1:
            return list(messages)
        head = flatten_units(units[:head_count])
        tail = flatten_units([units[-1]])
        middle = flatten_units(units[head_count:-1])

        summary = await self._summarizer.summarize(middle)
        if not summary:
            logger.warning("full_summary: summarization unavailable; degrading to pure deletion")
            return await SlidingWindowCompressor().compress(messages, window_tokens)

        reserved = estimate_messages_tokens(head) + estimate_messages_tokens(tail)
        summary_message = build_summary_message(summary, reserved, target)
        if summary_message is None:
            logger.warning("full_summary: no budget left for a summary; degrading to pure deletion")
            return await SlidingWindowCompressor().compress(messages, window_tokens)

        logger.info(
            "full_summary: replaced %d message(s) with a %d-token summary",
            len(middle),
            estimate_messages_tokens([summary_message]),
        )
        return head + [summary_message] + tail
