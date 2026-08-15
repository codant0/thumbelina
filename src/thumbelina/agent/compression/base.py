"""Compression strategy abstraction and shared helpers.

The compress graph node (entry → compress → agent) invokes a
:class:`ContextCompressor` once the estimated token usage of the checkpoint
messages reaches ``window × context.compress.threshold``. Every strategy
shares the same contract (design doc 四.5):

- compress down to at most ``window_tokens × LOW_WATERMARK`` (the 50% low
  watermark) so compression does not retrigger every following turn;
- never split an ``AIMessage(tool_calls)`` from its ``ToolMessage`` replies —
  deletions happen on whole "deletion units" (see
  :func:`group_deletion_units`);
- the returned sequence is written back to the graph state, so the
  checkpointer fixes the compressed history for the next turn.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from thumbelina.rag.retrieval.context_formatter import estimate_tokens

# Low watermark: compress down to at most 50% of the window so that the
# next turns can append again without immediately retriggering compression.
LOW_WATERMARK = 0.5

# Content-block types carrying model reasoning; Anthropic rejects replayed
# assistant turns whose thinking blocks lost their signatures (HTTP 400).
_THINKING_BLOCK_TYPES = ("thinking", "redacted_thinking", "reasoning")


def message_text(message: BaseMessage) -> str:
    """Extract estimable text from a message's ``content``.

    Handles both plain-string content and structured content blocks
    (text/thinking dicts, e.g. Anthropic), so usage estimation covers
    assistant turns with block-style content too.
    """
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("thinking") or ""
                parts.append(str(text))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def estimate_messages_tokens(messages: Sequence[BaseMessage]) -> int:
    """Estimate the total token usage of *messages*.

    Reuses the RAG :func:`~thumbelina.rag.retrieval.context_formatter.estimate_tokens`
    estimator (CJK ≈ 2 tokens/char, other ≈ 0.25 tokens/char) — accurate
    enough for window budget control and shared with the formatter so both
    layers agree.
    """
    return sum(estimate_tokens(message_text(message)) for message in messages)


def group_deletion_units(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """Split *messages* into atomic deletion units.

    An ``AIMessage`` carrying ``tool_calls`` is grouped with the
    ``ToolMessage`` replies that immediately follow it (matched by
    ``tool_call_id``), so a unit is always removed or kept as a whole.
    This guarantees a ``ToolMessage`` never loses the assistant turn that
    owns it — providers reject unpaired tool results (e.g. Anthropic 400).
    All other messages form singleton units.
    """
    units: list[list[BaseMessage]] = []
    index = 0
    total = len(messages)
    while index < total:
        message = messages[index]
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            unit: list[BaseMessage] = [message]
            expected = {
                call.get("id")
                for call in message.tool_calls
                if isinstance(call, dict) and call.get("id")
            }
            cursor = index + 1
            while cursor < total:
                candidate = messages[cursor]
                if not isinstance(candidate, ToolMessage):
                    break
                if expected and candidate.tool_call_id not in expected:
                    break
                unit.append(candidate)
                cursor += 1
            units.append(unit)
            index = cursor
        else:
            units.append([message])
            index += 1
    return units


def strip_thinking_blocks(message: AIMessage) -> AIMessage:
    """Return *message* with thinking/reasoning content blocks removed.

    After compression an assistant turn can end up at the head of the
    sequence; replaying stale thinking blocks without their signatures makes
    Anthropic return HTTP 400, so they are stripped defensively. Messages
    with plain-string content or without thinking blocks are returned
    unchanged (same object).
    """
    content = message.content
    if not isinstance(content, list):
        return message
    kept = [
        block
        for block in content
        if not (isinstance(block, dict) and block.get("type") in _THINKING_BLOCK_TYPES)
    ]
    if len(kept) == len(content):
        return message
    if not kept:
        return message.model_copy(update={"content": ""})
    return message.model_copy(update={"content": kept})


def leading_system_unit_count(units: list[list[BaseMessage]]) -> int:
    """Count leading deletion units that consist solely of ``SystemMessage``s.

    The session-level head (role prompt + first-turn user profile) must stay
    stable for the whole conversation, so every strategy protects this
    leading run from deletion/summarization.
    """
    count = 0
    while count < len(units) and all(isinstance(m, SystemMessage) for m in units[count]):
        count += 1
    return count


def flatten_units(units: list[list[BaseMessage]]) -> list[BaseMessage]:
    """Flatten deletion units back into a single message sequence."""
    return [message for unit in units for message in unit]


def truncate_text_to_tokens(text: str, budget_tokens: int, marker: str = "…") -> str:
    """Truncate *text* so it stays within *budget_tokens* estimated tokens.

    Appends *marker* when text was cut; the marker's own token cost is
    accounted for, so the result never exceeds the budget. Returns ``""``
    when even the marker cannot fit. Used as the hard input-truncation
    protection for LLM calls (summarization batches, oversized summaries).
    """
    if estimate_tokens(text) <= budget_tokens:
        return text
    if budget_tokens <= 0:
        return ""
    ratio = budget_tokens / max(estimate_tokens(text), 1)
    cutoff = max(1, int(len(text) * ratio))
    result = text[:cutoff]
    # The char-ratio cut is approximate for CJK/ASCII mixes (and the
    # estimator floors), so walk back while the marked result still exceeds
    # the budget — the returned string never does.
    while result and estimate_tokens(result + marker) > budget_tokens:
        result = result[:-1]
    return result + marker


def strip_first_assistant_thinking(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Strip thinking blocks from the first assistant message, if present.

    Compression can promote an ``AIMessage`` to (or near) the head of the
    sequence. Anthropic requires thinking blocks of replayed turns to stay
    intact, which cannot be guaranteed after deletions, so the first
    assistant message's thinking blocks are removed. Later assistant
    messages are untouched (their preceding tool/user turns still provide
    the required ordering guarantees as far as this defence is concerned).

    Returns the original list unchanged when nothing was stripped.
    """
    for position, message in enumerate(messages):
        if isinstance(message, AIMessage):
            stripped = strip_thinking_blocks(message)
            if stripped is message:
                break
            result = list(messages)
            result[position] = stripped
            return result
    return messages


@dataclass(frozen=True)
class CompressionResult:
    """Diagnostic outcome of one compression pass.

    Strategies return the compressed sequence directly; this container is
    available for callers (compress node, tests, metrics) that want the
    before/after usage figures alongside the payload.
    """

    messages: list[BaseMessage]
    tokens_before: int
    tokens_after: int

    @property
    def saved_tokens(self) -> int:
        """Tokens freed by the compression pass."""
        return self.tokens_before - self.tokens_after


class ContextCompressor(abc.ABC):
    """Base class for context compression strategies.

    Implementations compress an over-budget message sequence down to at most
    ``window_tokens × LOW_WATERMARK`` tokens while keeping
    ``AIMessage(tool_calls)``/``ToolMessage`` pairs intact. New strategies
    only need to subclass this and register via
    :func:`thumbelina.agent.compression.factory.register_compressor`.
    """

    #: Configuration name the strategy is registered under
    #: (``context.compress.strategy``).
    name: ClassVar[str] = ""

    @abc.abstractmethod
    async def compress(
        self, messages: Sequence[BaseMessage], window_tokens: int
    ) -> list[BaseMessage]:
        """Return the compressed replacement for *messages*.

        Parameters
        ----------
        messages:
            The full current message sequence from the graph state.
        window_tokens:
            Context window of the active model, in tokens. The returned
            sequence should occupy at most ``window_tokens × LOW_WATERMARK``.

        Returns
        -------
        list[BaseMessage]
            The compressed sequence. Kept messages must retain their
            original objects (and thus ids) so the state update can be a
            pure deletion; replacement messages (e.g. summaries) are new
            objects.
        """
        raise NotImplementedError


def compression_stats(
    before: Sequence[BaseMessage], after: Sequence[BaseMessage]
) -> CompressionResult:
    """Build a :class:`CompressionResult` for logging/metrics."""
    return CompressionResult(
        messages=list(after),
        tokens_before=estimate_messages_tokens(before),
        tokens_after=estimate_messages_tokens(after),
    )
