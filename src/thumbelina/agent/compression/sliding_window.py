"""策略 1：滑动窗口 —— 丢弃最旧的消息，不做摘要。"""

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
    """丢弃最旧的消息，直到用量降到低水位。

    零 LLM 成本、零延迟；被丢弃的信息彻底丢失。
    有两段边界受到删除保护：

    - 前导的 ``SystemMessage`` 单元序列 —— 会话级头部（角色提示词 +
      首轮用户画像）必须在整个会话期间保持稳定；
    - 最后一个删除单元 —— 它承载着当前轮的输入，agent 仍需作答。

    中间部分按删除单元从旧到新整体丢弃，
    因此 ``AIMessage(tool_calls)``/``ToolMessage`` 配对绝不会被拆开。
    """

    name = "sliding_window"

    async def compress(
        self, messages: Sequence[BaseMessage], window_tokens: int
    ) -> list[BaseMessage]:
        """返回移除了最旧可删单元的 *messages*。"""
        target = max(1, int(window_tokens * LOW_WATERMARK))
        units = group_deletion_units(messages)

        # 保护前导的 system 消息序列（会话级头部）。
        head = leading_system_unit_count(units)

        total = estimate_messages_tokens(messages)
        # 绝不丢弃最后一个单元：它承载着当前轮的输入。
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
