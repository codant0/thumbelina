"""Strategy 3: summary + recent K turns (default strategy).

Behaviour per design doc 四.5.3: the oldest history is replaced by a summary
``SystemMessage`` while the most recent ``recent_turns`` turns stay verbatim.
The leading system run (session head) and the current turn are protected like
:class:`~thumbelina.agent.compression.sliding_window.SlidingWindowCompressor`.

K-shrink boundary: when the recent K turns alone exceed the 50% low
watermark, K shrinks automatically (never below 1 — the current turn always
survives) and the excess turns join the summarized region. Turns are built
from atomic deletion units, so ``AIMessage(tool_calls)``/``ToolMessage``
pairs are never split.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

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


def _split_turns(units: list[list[BaseMessage]]) -> list[list[list[BaseMessage]]]:
    """Split deletion units into conversation turns.

    A turn starts at the unit containing a ``HumanMessage`` and extends to
    the next such unit. The run of ``SystemMessage`` units immediately
    preceding a human unit (its per-turn RAG/skill injections) belongs to
    that turn. Units before the first human unit (none here — the session
    head is carved off by the caller) form a leading "turn".
    """
    human_positions = [
        index for index, unit in enumerate(units) if any(isinstance(m, HumanMessage) for m in unit)
    ]
    if not human_positions:
        return [units]
    starts: list[int] = []
    for position in human_positions:
        start = position
        previous = starts[-1] if starts else 0
        while start > previous and all(isinstance(m, SystemMessage) for m in units[start - 1]):
            start -= 1
        starts.append(start)
    turns: list[list[list[BaseMessage]]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(units)
        turns.append(units[start:end])
    return turns


def _flatten_turns(turns: list[list[list[BaseMessage]]]) -> list[BaseMessage]:
    """Flatten turns (lists of deletion units) into one message sequence."""
    return [message for turn in turns for unit in turn for message in unit]


class SummaryRecentCompressor(ContextCompressor):
    """Summarize the old history, keep the most recent K turns verbatim."""

    name = "summary_recent"

    def __init__(
        self,
        recent_turns: int = 6,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        """Parameters
        ----------
        recent_turns:
            Number of recent turns kept verbatim
            (``context.compress.recent_turns``). Shrinks automatically when
            even K turns exceed the low watermark.
        llm_provider:
            LLM provider for the :class:`ContextSummarizer`. ``None`` makes
            summarization degrade to pure deletion at compress time.
        """
        self.recent_turns = recent_turns
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
        """Summarize all but the recent K turns; keep those turns verbatim."""
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_deletion_units(messages)
        head_count = leading_system_unit_count(units)
        head = flatten_units(units[:head_count])
        work = units[head_count:]
        if not work:
            return list(messages)

        turns = _split_turns(work)
        k = min(self.recent_turns, len(turns))
        kept = turns[-k:]
        reserved = estimate_messages_tokens(head) + estimate_messages_tokens(_flatten_turns(kept))
        # K-shrink boundary: if the recent K turns alone exceed the low
        # watermark, shrink K — at least the current turn always survives.
        while k > 1 and reserved > target:
            k -= 1
            kept = turns[-k:]
            reserved = estimate_messages_tokens(head) + estimate_messages_tokens(
                _flatten_turns(kept)
            )

        middle = _flatten_turns(turns[: len(turns) - k])
        if not middle:
            # Nothing older than the kept turns: no compression possible.
            return list(messages)

        summary = await self._summarizer.summarize(middle)
        if not summary:
            logger.warning("summary_recent: summarization unavailable; degrading to pure deletion")
            return await SlidingWindowCompressor().compress(messages, window_tokens)

        summary_message = build_summary_message(summary, reserved, target)
        if summary_message is None:
            logger.warning(
                "summary_recent: no budget left for a summary; degrading to pure deletion"
            )
            return await SlidingWindowCompressor().compress(messages, window_tokens)

        logger.info(
            "summary_recent: kept %d recent turn(s), summarized %d older message(s)",
            k,
            len(middle),
        )
        return head + [summary_message] + _flatten_turns(kept)
