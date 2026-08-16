"""策略 2：全量摘要 —— 用一条摘要替换可丢弃的历史。

行为依据设计文档 四.5.3：受保护边界之间的全部内容交给
:class:`~thumbelina.agent.compression.summarizer_context.ContextSummarizer`，
并替换为单条摘要 ``SystemMessage``。边界：

- 前导的 ``SystemMessage`` 单元序列（会话头部：角色提示词 +
  首轮用户画像）原样保留；
- 最后一个轮次（当前轮的输入及其 RAG/技能系统消息注入）
  原样保留 —— 与
  :func:`~thumbelina.agent.compression.summarizer_context.split_turns`
  的划分一致。

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
        """把 *messages* 中可丢弃的历史汇总为一条消息。

        保护会话头部与最后一个轮次（当前轮的输入及其 RAG/技能系统消息
        注入）原样保留；两者之间的历史进入摘要区域。
        """
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_atomic_units(messages)
        head_count = leading_protected_head_count(units)

        head = flatten_units(units[:head_count])
        work = units[head_count:]
        if not work:
            return list(messages)

        # 按轮次划分并保护最后一个轮次：当前轮的输入连同其 RAG/技能
        # 系统消息注入都位于该轮内，绝不能被子摘要掉 —— 否则 agent
        # 回答当前问题时拿不到刚检索到的内容。
        turns = split_turns(work)
        tail = flatten_turns([turns[-1]])
        middle = flatten_turns(turns[:-1])
        if not middle:
            # 只有当前轮：没有可压缩的历史。
            return list(messages)

        # 单次摘要调用的输入上限与模型窗口联动（50%，封顶 12K），
        # 小窗口模型也能安全完成摘要。
        summary = await self._summarizer.summarize(
            middle, max_input_tokens=resolve_input_cap(window_tokens)
        )
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
