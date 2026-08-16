"""策略 3：摘要 + 最近 K 轮（默认策略）。

行为依据设计文档 四.5.3：最旧的历史替换为摘要 ``SystemMessage``，
而最近的 ``recent_turns`` 轮原样保留。前导 system 序列（会话头部）与
当前轮受到与
:class:`~thumbelina.agent.compression.sliding_window.SlidingWindowCompressor`
相同的保护。

K 收缩边界：当最近 K 轮本身就超过 50% 低水位时，K 自动收缩
（不低于 1 —— 当前轮永远保留），超出的轮次并入待摘要区域。
轮次由原子单元组成，因此
``AIMessage(tool_calls)``/``ToolMessage`` 配对绝不会被拆开。
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
    group_atomic_units,
)
from thumbelina.agent.compression.sliding_window import SlidingWindowCompressor
from thumbelina.agent.compression.summarizer_context import (
    ContextSummarizer,
    build_summary_message,
    flatten_turns,
    leading_protected_head_count,
    resolve_input_cap,
    split_turns,
)
from thumbelina.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class SummaryRecentCompressor(ContextCompressor):
    """汇总旧历史，原样保留最近的 K 轮。"""

    name = "summary_recent"

    def __init__(
        self,
        recent_turns: int = 6,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        """Parameters
        ----------
        recent_turns:
            原样保留的最近轮数（``context.compress.recent_turns``）。
            即使 K 轮也超过低水位时会自动收缩。
        llm_provider:
            供 :class:`ContextSummarizer` 使用的 LLM provider。
            ``None`` 会使摘要在压缩时降级为纯删除。
        """
        self.recent_turns = recent_turns
        self._summarizer = ContextSummarizer(llm_provider)

    @property
    def llm_provider(self) -> LLMProvider | None:
        """用于摘要的 LLM provider（热切换时保持同步）。"""
        return self._summarizer.llm_provider

    @llm_provider.setter
    def llm_provider(self, value: LLMProvider | None) -> None:
        self._summarizer.llm_provider = value

    async def compress(
        self, messages: Sequence[BaseMessage], window_tokens: int
    ) -> list[BaseMessage]:
        """汇总最近 K 轮之外的所有内容；那些轮次原样保留。"""
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_atomic_units(messages)
        head_count = leading_protected_head_count(units)
        head = flatten_units(units[:head_count])
        work = units[head_count:]
        if not work:
            return list(messages)

        turns = split_turns(work)
        k = min(self.recent_turns, len(turns))
        kept = turns[-k:]
        reserved = estimate_messages_tokens(head) + estimate_messages_tokens(flatten_turns(kept))
        # K 收缩边界：若最近 K 轮本身就超过低水位，
        # 则收缩 K —— 至少当前轮永远保留。
        while k > 1 and reserved > target:
            k -= 1
            kept = turns[-k:]
            reserved = estimate_messages_tokens(head) + estimate_messages_tokens(
                flatten_turns(kept)
            )

        middle = flatten_turns(turns[: len(turns) - k])
        if not middle:
            # 没有比保留轮次更旧的内容：无法压缩。
            return list(messages)

        # 单次摘要调用的输入上限与模型窗口联动（50%，封顶 12K），
        # 小窗口模型也能安全完成摘要。
        summary = await self._summarizer.summarize(
            middle, max_input_tokens=resolve_input_cap(window_tokens)
        )
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
        return head + [summary_message] + flatten_turns(kept)
