"""Strategy 1: sliding window — drop the oldest messages, no summarization."""

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

logger = logging.getLogger(__name__)


class SlidingWindowCompressor(ContextCompressor):
    """Drop the oldest messages until usage falls to the low watermark.

    Zero LLM cost and zero latency; dropped information is lost entirely.
    Two boundaries are protected from deletion:

    - the leading run of ``SystemMessage`` units — the session-level head
      (role prompt + first-turn user profile) must stay stable for the
      whole conversation;
    - the final deletion unit — it carries the current turn's input which
      the agent still has to answer.

    Everything in between is dropped oldest-first in whole deletion units,
    so ``AIMessage(tool_calls)``/``ToolMessage`` pairs are never split.
    """

    name = "sliding_window"

    async def compress(
        self, messages: Sequence[BaseMessage], window_tokens: int
    ) -> list[BaseMessage]:
        """Return *messages* with the oldest droppable units removed."""
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_deletion_units(messages)

        # Protect the leading run of system messages (session-level head).
        head = leading_system_unit_count(units)

        total = estimate_messages_tokens(messages)
        # Never drop the last unit: it holds the current turn's input.
        droppable_end = len(units) - 1
        cursor = head
        dropped_count = 0
        while cursor < droppable_end and total > target:
            total -= estimate_messages_tokens(units[cursor])
            dropped_count += len(units[cursor])
            cursor += 1

        if dropped_count == 0:
            return list(messages)

        kept: list[BaseMessage] = flatten_units(units[:head] + units[cursor:])
        logger.info(
            "sliding_window dropped %d oldest message(s); estimate %d -> %d tokens",
            dropped_count,
            estimate_messages_tokens(messages),
            estimate_messages_tokens(kept),
        )
        return kept
