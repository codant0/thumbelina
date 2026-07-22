"""Tests for RAG context formatter."""

from __future__ import annotations

import json
import uuid

import pytest

from thumbelina.rag.embedding.base import ScoredChunk
from thumbelina.rag.knowledge_base.models import Chunk
from thumbelina.rag.retrieval.context_formatter import (
    ContextFormatter,
    _default_token_counter,
)


def _make_chunk(content: str = "test text", metadata: str = "{}") -> Chunk:
    return Chunk(
        id=uuid.uuid4().hex,
        document_id="doc-1",
        content=content,
        metadata=metadata,
        knowledge_base_id="0",
    )


def _make_scored_chunk(content: str, score: float = 0.9, metadata: str = "{}") -> ScoredChunk:
    return ScoredChunk(
        id=uuid.uuid4().hex,
        document_id="doc-1",
        content=content,
        metadata=metadata,
        knowledge_base_id="0",
        score=score,
    )


class TestDefaultTokenCounter:
    """Tests for _default_token_counter."""

    def test_ascii_text(self):
        # 英文约 0.25 token/字符
        count = _default_token_counter("hello")
        assert count == int(5 * 0.25)

    def test_cjk_text(self):
        # CJK 约 2 token/字
        count = _default_token_counter("你好")
        assert count == int(2 * 2)

    def test_empty_string(self):
        assert _default_token_counter("") == 0

    def test_mixed_text(self):
        text = "hi你好"
        # 'h','i' = 2 ascii, '你','好' = 2 CJK
        expected = int(2 * 0.25 + 2 * 2)
        assert _default_token_counter(text) == expected


class TestContextFormatter:
    """Tests for ContextFormatter."""

    def test_format_empty_returns_empty(self):
        formatter = ContextFormatter()
        assert formatter.format([]) == ""

    def test_format_single_chunk(self):
        chunk = _make_chunk("Hello world")
        formatter = ContextFormatter(with_citation=True)
        result = formatter.format(chunk)

        assert "[1]" in result
        assert "Hello world" in result

    def test_format_single_chunk_no_citation(self):
        chunk = _make_chunk("Hello world")
        formatter = ContextFormatter(with_citation=False)
        result = formatter.format(chunk)

        assert "[1]" not in result
        assert "Hello world" in result

    def test_format_multiple_chunks(self):
        chunks = [_make_chunk(f"chunk {i}") for i in range(3)]
        formatter = ContextFormatter(with_citation=True)
        result = formatter.format(chunks)

        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result
        assert "chunk 0" in result
        assert "chunk 1" in result
        assert "chunk 2" in result

    def test_format_scored_chunk_with_score(self):
        meta = json.dumps({"source": "doc.md"})
        sc = _make_scored_chunk("content", score=0.8765, metadata=meta)
        formatter = ContextFormatter(with_citation=True, include_score=True)
        result = formatter.format(sc)

        assert "[1]" in result
        assert "content" in result
        assert "0.8765" in result

    def test_format_scored_chunk_without_score_display(self):
        sc = _make_scored_chunk("content", score=0.8765)
        formatter = ContextFormatter(with_citation=True, include_score=False)
        result = formatter.format(sc)

        assert "0.8765" not in result

    def test_format_chunk_with_source_metadata(self):
        meta = json.dumps({"source": "readme.md", "page": 3})
        chunk = _make_chunk("text", metadata=meta)
        formatter = ContextFormatter(with_citation=True)
        result = formatter.format(chunk)

        assert "来源: readme.md" in result
        assert "第 3 页" in result

    def test_format_chunk_with_section_metadata(self):
        meta = json.dumps({"title": "doc.md", "section": "引言"})
        chunk = _make_chunk("text", metadata=meta)
        formatter = ContextFormatter(with_citation=True)
        result = formatter.format(chunk)

        assert "章节: 引言" in result

    def test_format_chunk_with_invalid_metadata(self):
        chunk = _make_chunk("text", metadata="not json")
        formatter = ContextFormatter()
        # 不应抛异常
        result = formatter.format(chunk)
        assert "text" in result

    def test_format_chunk_with_empty_metadata(self):
        chunk = _make_chunk("text", metadata="")
        formatter = ContextFormatter()
        result = formatter.format(chunk)
        assert "text" in result

    def test_custom_separator(self):
        chunks = [_make_chunk("A"), _make_chunk("B")]
        formatter = ContextFormatter(separator="---")
        result = formatter.format(chunks)

        assert "---" in result

    def test_token_budget_truncation(self):
        # 使用非常小的 token 预算来触发截断
        # 自定义计数器：1 token/字符
        formatter = ContextFormatter(
            token_budget=10,
            token_counter=lambda t: len(t),
        )
        chunks = [_make_chunk("A" * 100), _make_chunk("B" * 100)]
        result = formatter.format(chunks)

        # 被截断后应该比原始文本短
        assert len(result) < 200

    def test_truncate_keeps_first_fragment(self):
        formatter = ContextFormatter(
            token_budget=10,
            token_counter=lambda t: len(t),
        )
        fragments = ["FIRST", "MIDDLE", "LAST"]
        result = formatter._truncate(fragments, budget=10)

        assert "FIRST" in result

    def test_truncate_empty_fragments(self):
        formatter = ContextFormatter()
        result = formatter._truncate([], budget=100)
        assert result == ""

    def test_format_preserves_order(self):
        chunks = [_make_chunk("alpha"), _make_chunk("beta"), _make_chunk("gamma")]
        formatter = ContextFormatter(with_citation=True)
        result = formatter.format(chunks)

        pos_alpha = result.index("alpha")
        pos_beta = result.index("beta")
        pos_gamma = result.index("gamma")
        assert pos_alpha < pos_beta < pos_gamma

    def test_extract_source_info_with_document_id(self):
        meta = json.dumps({"document_id": "doc-123"})
        chunk = _make_chunk("text", metadata=meta)
        formatter = ContextFormatter()
        result = formatter.format(chunk)

        assert "文档ID: doc-123" in result

    def test_format_mixed_chunk_types(self):
        items = [
            _make_scored_chunk("scored", score=0.9),
            _make_chunk("plain"),
        ]
        formatter = ContextFormatter(with_citation=True)
        result = formatter.format(items)

        assert "scored" in result
        assert "plain" in result
