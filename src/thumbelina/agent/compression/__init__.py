"""Context compression framework (design doc 四.5).

The compress graph node trims the checkpoint message history once its
estimated token usage reaches ``window × context.compress.threshold``:

- :class:`ContextCompressor` — strategy abstraction (shared contract);
- :class:`SlidingWindowCompressor` — built-in pure-deletion strategy;
- :class:`FullSummaryCompressor` — summarize all droppable history;
- :class:`SummaryRecentCompressor` — summarize old history, keep the
  recent K turns verbatim (default strategy);
- :class:`ContextSummarizer` — the compression-specific LLM summarizer
  (long prompt, batch-then-merge recursion, thinking/tool-output stripping);
- :func:`create_compressor` / :func:`register_compressor` — registry so new
  strategies can be added by configuration name only.
"""

from thumbelina.agent.compression.base import (
    LOW_WATERMARK,
    CompressionResult,
    ContextCompressor,
    compression_stats,
    estimate_messages_tokens,
    flatten_units,
    group_deletion_units,
    leading_system_unit_count,
    message_text,
    strip_first_assistant_thinking,
    strip_thinking_blocks,
    truncate_text_to_tokens,
)
from thumbelina.agent.compression.factory import (
    available_strategies,
    create_compressor,
    register_compressor,
)
from thumbelina.agent.compression.full_summary import FullSummaryCompressor
from thumbelina.agent.compression.sliding_window import SlidingWindowCompressor
from thumbelina.agent.compression.summarizer_context import ContextSummarizer
from thumbelina.agent.compression.summary_recent import SummaryRecentCompressor

__all__ = [
    "LOW_WATERMARK",
    "CompressionResult",
    "ContextCompressor",
    "ContextSummarizer",
    "FullSummaryCompressor",
    "SlidingWindowCompressor",
    "SummaryRecentCompressor",
    "available_strategies",
    "compression_stats",
    "create_compressor",
    "estimate_messages_tokens",
    "flatten_units",
    "group_deletion_units",
    "leading_system_unit_count",
    "message_text",
    "register_compressor",
    "strip_first_assistant_thinking",
    "strip_thinking_blocks",
    "truncate_text_to_tokens",
]
