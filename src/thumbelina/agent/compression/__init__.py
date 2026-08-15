"""上下文压缩框架（设计文档 四.5）。

压缩节点在检查点消息历史的预估 token 用量达到
``window × context.compress.threshold`` 时对其进行裁剪：

- :class:`ContextCompressor` —— 策略抽象（共享契约）；
- :class:`SlidingWindowCompressor` —— 内置的纯删除策略；
- :class:`FullSummaryCompressor` —— 汇总所有可丢弃的历史；
- :class:`SummaryRecentCompressor` —— 汇总旧历史，原样保留最近
  K 轮（默认策略）；
- :class:`ContextSummarizer` —— 专用于压缩的 LLM 摘要器
  （长提示词、分批后合并的递归、thinking/工具输出剥离）；
- :func:`create_compressor` / :func:`register_compressor` —— 注册表，
  让新策略只需通过配置名即可添加。
"""

from thumbelina.agent.compression.base import (
    LOW_WATERMARK,
    CompressionResult,
    ContextCompressor,
    compression_stats,
    estimate_messages_tokens,
    flatten_units,
    group_atomic_units,
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
    "group_atomic_units",
    "leading_system_unit_count",
    "message_text",
    "register_compressor",
    "strip_first_assistant_thinking",
    "strip_thinking_blocks",
    "truncate_text_to_tokens",
]
