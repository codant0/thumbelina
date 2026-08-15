"""策略 2：全量摘要 —— 用一条摘要替换可丢弃的历史。

行为依据设计文档 四.5.3：受保护边界之间的全部内容交给
:class:`~thumbelina.agent.compression.summarizer_context.ContextSummarizer`，
并替换为单条摘要 ``SystemMessage``。边界与
:class:`~thumbelina.agent.compression.sliding_window.SlidingWindowCompressor`
一致：

- 前导的 ``SystemMessage`` 单元序列（会话头部：角色提示词 +
  首轮用户画像）原样保留；
- 最后一个删除单元（当前轮的输入）原样保留。

当摘要失败（LLM 错误、结果为空、或没有给摘要留下预算）时，
该策略降级为纯删除，压缩永远不会阻塞会话。
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
    """把旧历史汇总为一条消息，保留头部与当前轮。"""

    name = "full_summary"

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
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
        """把 *messages* 中可丢弃的中间部分汇总为一条消息。"""
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_deletion_units(messages)
        head_count = leading_system_unit_count(units)

        # 最后一个单元承载当前轮的输入，必须保留。
        # 若头部与尾部之间没有内容，则无可压缩。
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
