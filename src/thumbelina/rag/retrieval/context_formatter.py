"""将检索结果格式化为 LLM 可直接使用的上下文字符串。

职责
----
- 合并多个文档片段，附带来源元数据
- 按 token 预算截断（保留首尾片段，优先保留高分结果）
- 可选地插入引用标记 ``[1]``，便于 LLM 追溯来源

典型用法::

    formatter = ContextFormatter(token_budget=3000, include_score=True)
    context = formatter.format(scored_chunks)

输出示例::

    [1]
    哆啦A梦拿出了时光布、缩小灯和记忆面包三个秘密道具……
    来源: doc.md | 第 3 页 (相似度: 0.8721)

    [2]
    时光布可以让物体回到过去的状态……
    来源: doc.md | 章节: 秘密道具 (相似度: 0.8456)
"""

from __future__ import annotations

import json
import logging
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any

from thumbelina.rag.common.models import Chunk
from thumbelina.rag.embedding.base import ScoredChunk

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """基于字符类型的 token 数估算。

    CJK 字符按约 2 token/字估算，其余字符按约 0.25 token/字符
    （英文平均每个 token 约 4 字符）。足够用于上下文截断的预算控制；
    agent 侧的上下文压缩占用估算（``agent/compression``）同样复用本函数。
    """
    cjk = sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))
    return int(cjk * 2 + (len(text) - cjk) * 0.25)


# 兼容旧私有名称（既有调用与测试仍可直接引用）。
_default_token_counter = estimate_tokens


class ContextFormatter:
    """将检索到的文档片段格式化为 LLM 上下文。

    Parameters
    ----------
    token_budget:
        上下文的最大 token 数。超出时保留首尾片段，中间按分数降序填充。
    separator:
        片段之间的分隔符。
    with_citation:
        是否在每个片段前插入 ``[N]`` 引用标记。
    include_score:
        是否在来源行显示相似度分数。
    token_counter:
        自定义 token 计数器。默认使用字符类型估算。
    """

    def __init__(
        self,
        token_budget: int = 3000,
        separator: str = "\n\n",
        with_citation: bool = True,
        include_score: bool = False,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.token_budget = token_budget
        self.separator = separator
        self.with_citation = with_citation
        self.include_score = include_score
        self._count_tokens = token_counter or estimate_tokens

    def format(
        self,
        chunks: ScoredChunk | Chunk | Sequence[ScoredChunk | Chunk],
    ) -> str:
        """将召回结果格式化为 LLM 上下文。

        Parameters
        ----------
        chunks:
            单个 ``ScoredChunk`` / ``Chunk``，或它们的列表。
            ``ScoredChunk`` 会保留分数信息；``Chunk`` 分数视为不可用。

        Returns
        -------
        str
            格式化后的上下文字符串。无结果时返回空字符串。
        """
        if isinstance(chunks, (ScoredChunk, Chunk)):
            chunks = [chunks]
        if not chunks:
            return ""

        fragments: list[str] = []
        for i, item in enumerate(chunks, start=1):
            if isinstance(item, ScoredChunk):
                fragments.append(self._format_chunk(item, index=i, score=item.score))
            elif isinstance(item, Chunk):
                fragments.append(self._format_chunk(item, index=i))
            else:
                logger.warning("跳过不支持的类型: %s", type(item).__name__)

        result = self.separator.join(fragments)

        if self._count_tokens(result) > self.token_budget:
            result = self._truncate(fragments, self.token_budget)

        return result

    def _truncate(self, fragments: list[str], budget: int) -> str:
        """按 token 预算截断，保留首尾片段。

        策略：保留第一个（最相关）和最后一个片段，中间片段按列表顺序
        尽量填充。如果连第一个片段都超限，则直接截断该片段的文本。
        """
        if not fragments:
            return ""

        selected: list[str] = [fragments[0]]
        used = self._count_tokens(fragments[0])

        # 尝试加入尾部片段
        if len(fragments) > 1:
            tail = fragments[-1]
            tail_tokens = self._count_tokens(tail)
            if used + tail_tokens + self._count_tokens(self.separator) <= budget:
                selected.append(tail)
                used += tail_tokens + self._count_tokens(self.separator)

        # 按顺序尝试加入中间片段（跳过首尾）
        for frag in fragments[1:-1]:
            frag_tokens = self._count_tokens(frag)
            sep_tokens = self._count_tokens(self.separator)
            if used + frag_tokens + sep_tokens <= budget:
                selected.append(frag)
                used += frag_tokens + sep_tokens
            else:
                break

        result = self.separator.join(selected)

        # 如果连第一个片段都超限，强制截断
        if not selected or (len(selected) == 1 and self._count_tokens(result) > budget):
            text = fragments[0]
            # 按比例截断字符数
            ratio = budget / max(self._count_tokens(text), 1)
            cutoff = max(1, int(len(text) * ratio))
            result = text[:cutoff].rstrip() + " …"

        return result

    def _format_chunk(
        self,
        chunk: Chunk,
        index: int,
        score: float | None = None,
    ) -> str:
        """将单个 Chunk 格式化为带引用的文本片段。"""
        parts: list[str] = []

        if self.with_citation:
            parts.append(f"[{index}]")
        parts.append(chunk.content)

        source_info = self._extract_source_info(chunk.metadata)
        if source_info:
            source_line = f"来源: {source_info}"
            if score is not None and self.include_score:
                source_line += f" (相似度: {score:.4f})"
            parts.append(source_line)

        return "\n".join(parts)

    def _extract_source_info(self, metadata: str) -> str:
        """从 Chunk.metadata JSON 字符串中提取可读的来源描述。"""
        try:
            meta: dict[str, Any] = json.loads(metadata) if metadata else {}
        except (json.JSONDecodeError, TypeError):
            return ""

        if not meta:
            return ""

        source_parts: list[str] = []
        # 常见来源字段
        source = meta.get("source") or meta.get("file_name") or meta.get("title")
        if source:
            source_parts.append(str(source))

        doc_id = meta.get("document_id")
        if doc_id and (not source or str(doc_id) not in source):
            source_parts.append(f"文档ID: {doc_id}")

        page = meta.get("page") or meta.get("page_number")
        page_start = meta.get("page_start")
        page_end = meta.get("page_end")
        section = meta.get("section") or meta.get("heading")
        if page_start is not None:
            if page_end is not None and page_end != page_start:
                source_parts.append(f"第 {page_start}-{page_end} 页")
            else:
                source_parts.append(f"第 {page_start} 页")
        elif page is not None:
            source_parts.append(f"第 {page} 页")
        if section:
            source_parts.append(f"章节: {section}")

        return " | ".join(source_parts)
