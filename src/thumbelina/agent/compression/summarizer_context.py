"""专用于压缩的 LLM 摘要器（设计文档 四.5.2/5.3）。

:class:`ContextSummarizer` 把一段对话历史转成一条高密度摘要，
供 ``full_summary`` / ``summary_recent`` 策略使用。与 memory 层的
``TitleSummarizer``（1-2 句的命名摘要）不同，本摘要器为上下文压缩打造：

- 长提示词，保留事实、决策与未完成事项；
- 单次输入超过单次调用 token 上限时，先分批再合并（递归），
  另有硬性输入截断作为最后防线；
- thinking 块与过长的工具输出在 LLM 看到文本之前先剥离/截断；
- 任何失败都返回 ``None``，使策略层降级为纯删除 ——
  压缩永远不会阻塞会话。
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

#: 加在策略产出的摘要 ``SystemMessage`` 前面的前缀，
#: 让模型能把浓缩历史与实时轮次区分开。
SUMMARY_MESSAGE_PREFIX = "【对话历史摘要】\n"

#: 工具输出超过该长度（字符）时，在摘要前截断。
DEFAULT_MAX_TOOL_CHARS = 2_000

#: 单次 LLM 调用的输入上限（token）。更大的输入拆成分批，
#: 各自独立摘要后再合并。作为按窗口解析前的封顶值使用。
DEFAULT_MAX_INPUT_TOKENS = 12_000

#: 单次摘要调用的输入上限占模型窗口的比例 —— 为输出预留另一半空间，
#: 避免小窗口模型上的摘要调用直接溢出。
INPUT_CAP_WINDOW_RATIO = 0.5

#: 分批后合并的递归深度上限；到达上限时输入改为硬性截断，
#: 而不再继续拆分（保证终止）。
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


def resolve_input_cap(window_tokens: int, default: int = DEFAULT_MAX_INPUT_TOKENS) -> int:
    """按模型窗口计算单次摘要调用的输入上限。

    上限封顶 ``default``（默认 12K）以控制单次调用成本，同时随窗口
    收缩到 ``window_tokens × INPUT_CAP_WINDOW_RATIO``（默认 50%），
    为输出预留空间，避免小窗口模型上的摘要调用直接溢出。
    """
    return min(default, max(1, int(window_tokens * INPUT_CAP_WINDOW_RATIO)))


def build_summary_message(
    summary: str, reserved_tokens: int, target_tokens: int
) -> SystemMessage | None:
    """构建尺寸适配剩余预算的摘要 ``SystemMessage``。

    ``reserved_tokens`` 是与摘要一同保留的消息（受保护的头部、保留的
    最近轮次、当前轮尾部）的预估用量。当没有摘要能在 ``target_tokens``
    之内放下时返回 ``None`` —— 调用方应降级为纯删除。
    """
    budget = target_tokens - reserved_tokens - estimate_tokens(SUMMARY_MESSAGE_PREFIX)
    if budget <= 0:
        return None
    content = SUMMARY_MESSAGE_PREFIX + truncate_text_to_tokens(summary, budget)
    return SystemMessage(content=content)


class ContextSummarizer:
    """通过 LLM 把一段消息区间汇总为单段高密度文本。

    Parameters
    ----------
    llm_provider:
        用于摘要调用的 LLM provider。``None``（例如未提供 provider 就
        构造的策略）会使每次调用都以 ``None`` 优雅失败。
    max_input_tokens:
        单次调用的输入上限（预估 token）；更大的输入拆成分批，
        递归摘要。
    max_tool_chars:
        超过该字符数的工具输出在摘要前截断（过长的工具噪声
        几乎不贡献有效信号）。
    max_depth:
        分批后合并的递归上限；超过后输入改为硬性截断到
        ``max_input_tokens``，而不再继续拆分。
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

    async def summarize(
        self, messages: Sequence[BaseMessage], max_input_tokens: int | None = None
    ) -> str | None:
        """返回 *messages* 的摘要；失败时返回 ``None``。

        ``max_input_tokens`` 覆盖本次调用的单次输入上限；为 ``None``
        时使用构造时配置的默认值。调用方（压缩策略）应传入按模型窗口
        解析出的上限（见 :func:`resolve_input_cap`）。

        失败（缺少 provider、LLM 错误、结果为空）绝不允许抛出：
        策略在收到 ``None`` 时回退到纯删除。
        """
        entries = self._to_entries(messages)
        if not entries:
            return None
        text = "\n\n".join(entries)
        if not text.strip():
            return None
        try:
            return await self._summarize_text(
                text, depth=0, max_input_tokens=max_input_tokens or self.max_input_tokens
            )
        except Exception:
            logger.warning("Context summarization failed", exc_info=True)
            return None

    def _to_entries(self, messages: Sequence[BaseMessage]) -> list[str]:
        """把消息渲染为带标签的文本条目，并在送入 LLM 前剥离。

        thinking 块被移除、过长的工具输出被截断，
        让模型把预算花在有效信号而非噪声上。
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

    async def _summarize_text(self, text: str, depth: int, max_input_tokens: int) -> str | None:
        """摘要 *text*；超限时递归分批再合并。

        每一层把超预算的输入拆成适配 ``max_input_tokens`` 的分批，
        逐批摘要，再合并各部分（若合并后仍超限则再次递归）。
        深度上限通过硬性截断保证终止。
        """
        if estimate_tokens(text) > max_input_tokens and depth < self.max_depth:
            batches = self._split_batches(text, max_input_tokens)
            if len(batches) > 1:
                partials: list[str] = []
                for batch in batches:
                    partial = await self._summarize_text(batch, depth + 1, max_input_tokens)
                    if partial is None:
                        return None
                    partials.append(partial)
                merged = "\n\n".join(partials)
                if estimate_tokens(merged) > max_input_tokens:
                    return await self._summarize_text(merged, depth + 1, max_input_tokens)
                return await self._call_llm(merged, merge=True)
            text = batches[0]
        return await self._call_llm(truncate_text_to_tokens(text, max_input_tokens))

    def _split_batches(self, text: str, max_input_tokens: int) -> list[str]:
        """把 *text* 拆成每批都适配 ``max_input_tokens`` 的分批。

        按段落边界拆分；单个段落超过上限时先硬性截断
        （输入截断保护）。
        """
        paragraphs = [part for part in text.split("\n\n") if part.strip()]
        if not paragraphs:
            return [text]
        batches: list[str] = []
        current: list[str] = []
        for paragraph in paragraphs:
            if estimate_tokens(paragraph) > max_input_tokens:
                paragraph = truncate_text_to_tokens(paragraph, max_input_tokens)
            if current and estimate_tokens("\n\n".join(current + [paragraph])) > (max_input_tokens):
                batches.append("\n\n".join(current))
                current = [paragraph]
            else:
                current.append(paragraph)
        if current:
            batches.append("\n\n".join(current))
        return batches or [text]

    async def _call_llm(self, text: str, *, merge: bool = False) -> str | None:
        """调用一次 LLM；失败返回 ``None``（绝不抛出）。"""
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
