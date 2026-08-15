"""Compression-specific LLM summarizer (design doc 四.5.2/5.3).

:class:`ContextSummarizer` turns a chunk of conversation history into one
dense summary for the ``full_summary`` / ``summary_recent`` strategies.
Unlike the memory-layer ``TitleSummarizer`` (a 1-2 sentence naming summary),
this summarizer is built for context compression:

- a long prompt that preserves facts, decisions and unfinished items;
- batch-then-merge summarization (recursive) when a single input exceeds
  the per-call token cap, plus hard input truncation as a final guard;
- thinking blocks and overlong tool outputs are stripped/truncated before
  the LLM sees the text;
- any failure yields ``None`` so the strategy layer degrades to pure
  deletion — compression never blocks a conversation.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from thumbelina.agent.compression.base import (
    message_text,
    strip_thinking_blocks,
    truncate_text_to_tokens,
)
from thumbelina.llm.base import LLMProvider
from thumbelina.rag.retrieval.context_formatter import estimate_tokens

logger = logging.getLogger(__name__)

#: Prefix prepended to the summary ``SystemMessage`` the strategies emit, so
#: the model can tell the condensed history apart from live turns.
SUMMARY_MESSAGE_PREFIX = "【对话历史摘要】\n"

#: Tool outputs longer than this (chars) are truncated before summarization.
DEFAULT_MAX_TOOL_CHARS = 2_000

#: Per-LLM-call input cap (tokens). Larger inputs are split into batches
#: that are summarized independently and then merged.
DEFAULT_MAX_INPUT_TOKENS = 12_000

#: Recursion depth cap for batch-then-merge; at the cap the input is hard
#: truncated instead of split again (guaranteed termination).
DEFAULT_MAX_DEPTH = 4

SUMMARY_PROMPT = (
    "你是一名对话上下文压缩助手。请将下面的对话历史压缩成一份结构化的中文摘要，"
    "这份摘要将替换原文进入后续对话，因此必须自包含、尽量无信息损耗。要求：\n"
    "1. 保留所有关键事实与细节：时间、日期、数字、名称、路径、参数、报错信息等不得丢失；\n"
    "2. 保留用户的需求、约束与偏好，以及已做出的决策、达成的结论及其理由；\n"
    "3. 保留未完成事项、待办任务、后续计划与承诺；\n"
    "4. 保留进行中的工作状态：已创建的资源、工具调用结果、文件改动等；\n"
    "5. 忽略寒暄、重复内容与格式噪声；\n"
    "6. 按时间顺序组织，使用要点形式，尽量简明；\n"
    "7. 直接输出摘要正文，不要任何前言、说明或 Markdown 代码块。"
)

MERGE_PROMPT = (
    "你是一名对话上下文压缩助手。下面是同一段对话历史被分批压缩后得到的多份摘要，"
    "请将它们归并成一份完整、连贯的中文摘要：去除重复、保持时间顺序、不丢失任何要点，"
    "输出格式与单独压缩时一致（要点形式），直接输出摘要正文，"
    "不要任何前言、说明或 Markdown 代码块。"
)

_ROLE_LABELS: dict[type[BaseMessage], str] = {
    HumanMessage: "用户",
    AIMessage: "助手",
    ToolMessage: "工具",
    SystemMessage: "系统",
}


def build_summary_message(
    summary: str, reserved_tokens: int, target_tokens: int
) -> SystemMessage | None:
    """Build the summary ``SystemMessage`` sized to fit the remaining budget.

    ``reserved_tokens`` is the estimated usage of the messages kept alongside
    the summary (protected head, kept recent turns, current-turn tail).
    Returns ``None`` when no summary can fit under ``target_tokens`` — the
    caller should degrade to pure deletion.
    """
    budget = target_tokens - reserved_tokens - estimate_tokens(SUMMARY_MESSAGE_PREFIX)
    if budget <= 0:
        return None
    content = SUMMARY_MESSAGE_PREFIX + truncate_text_to_tokens(summary, budget)
    return SystemMessage(content=content)


class ContextSummarizer:
    """Summarize a message range into a single dense text via the LLM.

    Parameters
    ----------
    llm_provider:
        The LLM provider used for the summarization calls. ``None`` (e.g.
        a strategy constructed without a provider) makes every call fail
        gracefully with ``None``.
    max_input_tokens:
        Per-call input cap in estimated tokens; larger inputs are split
        into batches and summarized recursively.
    max_tool_chars:
        Tool outputs longer than this many chars are truncated before
        summarization (overlong tool noise contributes little signal).
    max_depth:
        Recursion cap for batch-then-merge; past it the input is hard
        truncated to ``max_input_tokens`` instead of split again.
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        *,
        max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
        max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        self.llm_provider = llm_provider
        self.max_input_tokens = max_input_tokens
        self.max_tool_chars = max_tool_chars
        self.max_depth = max_depth

    async def summarize(self, messages: Sequence[BaseMessage]) -> str | None:
        """Return a summary for *messages*, or ``None`` on failure.

        Failures (missing provider, LLM error, empty result) must never
        raise: strategies fall back to pure deletion on ``None``.
        """
        entries = self._to_entries(messages)
        if not entries:
            return None
        text = "\n\n".join(entries)
        if not text.strip():
            return None
        try:
            return await self._summarize_text(text, depth=0)
        except Exception:
            logger.warning("Context summarization failed", exc_info=True)
            return None

    def _to_entries(self, messages: Sequence[BaseMessage]) -> list[str]:
        """Render messages as labeled text entries, stripped for the LLM.

        Thinking blocks are removed and overlong tool outputs truncated so
        the model spends its budget on signal instead of noise.
        """
        entries: list[str] = []
        for message in messages:
            if isinstance(message, AIMessage):
                message = strip_thinking_blocks(message)
            content = message_text(message)
            if isinstance(message, ToolMessage) and len(content) > self.max_tool_chars:
                content = content[: self.max_tool_chars] + "\n[工具输出过长，已截断]"
            label = _ROLE_LABELS.get(type(message), type(message).__name__)
            entries.append(f"{label}: {content}")
        return entries

    async def _summarize_text(self, text: str, depth: int) -> str | None:
        """Summarize *text*, batching and merging recursively when oversized.

        Each level splits over-budget input into batches that fit
        ``max_input_tokens``, summarizes every batch, then merges the
        partials (recursively again if the merge is still oversized). The
        depth cap guarantees termination via hard truncation.
        """
        if estimate_tokens(text) > self.max_input_tokens and depth < self.max_depth:
            batches = self._split_batches(text)
            if len(batches) > 1:
                partials: list[str] = []
                for batch in batches:
                    partial = await self._summarize_text(batch, depth + 1)
                    if partial is None:
                        return None
                    partials.append(partial)
                merged = "\n\n".join(partials)
                if estimate_tokens(merged) > self.max_input_tokens:
                    return await self._summarize_text(merged, depth + 1)
                return await self._call_llm(merged, merge=True)
            text = batches[0]
        return await self._call_llm(truncate_text_to_tokens(text, self.max_input_tokens))

    def _split_batches(self, text: str) -> list[str]:
        """Split *text* into batches that each fit ``max_input_tokens``.

        Splits on paragraph boundaries; a single paragraph larger than the
        cap is hard truncated first (input truncation protection).
        """
        paragraphs = [part for part in text.split("\n\n") if part.strip()]
        if not paragraphs:
            return [text]
        batches: list[str] = []
        current: list[str] = []
        for paragraph in paragraphs:
            if estimate_tokens(paragraph) > self.max_input_tokens:
                paragraph = truncate_text_to_tokens(paragraph, self.max_input_tokens)
            if current and estimate_tokens("\n\n".join(current + [paragraph])) > (
                self.max_input_tokens
            ):
                batches.append("\n\n".join(current))
                current = [paragraph]
            else:
                current.append(paragraph)
        if current:
            batches.append("\n\n".join(current))
        return batches or [text]

    async def _call_llm(self, text: str, *, merge: bool = False) -> str | None:
        """Call the LLM once; ``None`` on failure (never raises)."""
        if self.llm_provider is None:
            logger.warning("ContextSummarizer has no LLM provider; summarization unavailable")
            return None
        prompt = [
            {"role": "system", "content": MERGE_PROMPT if merge else SUMMARY_PROMPT},
            {"role": "user", "content": text},
        ]
        try:
            response = await self.llm_provider.chat(prompt)
        except Exception:
            logger.warning("Context summarization LLM call failed", exc_info=True)
            return None
        summary = (response or "").strip()
        if not summary:
            logger.warning("Context summarization LLM returned an empty summary")
            return None
        return summary
