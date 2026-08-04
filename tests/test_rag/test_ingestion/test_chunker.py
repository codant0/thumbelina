"""Tests for RAG text chunking strategies."""

from __future__ import annotations

import json
import uuid

import pytest

from thumbelina.rag.ingestion.chunker import FixedSizeChunker, RecursiveChunker
from thumbelina.rag.common.models import Document, DocumentType, PageSpan


def _make_document(content: str, name: str = "test.md") -> Document:
    return Document(
        id=uuid.uuid4().hex,
        name=name,
        source_uri=f"/tmp/{name}",
        document_type=DocumentType.MARKDOWN,
        content=content,
        sha256=b"\x00" * 32,
        sim_hash_64=b"\x00" * 8,
    )


class TestFixedSizeChunker:
    """Tests for FixedSizeChunker."""

    def test_basic_chunking(self):
        doc = _make_document("A" * 100)
        chunker = FixedSizeChunker(chunk_size=50, overlap=0)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 2
        assert chunks[0].content == "A" * 50
        assert chunks[1].content == "A" * 50

    def test_with_overlap(self):
        doc = _make_document("ABCDEFGHIJ")
        chunker = FixedSizeChunker(chunk_size=5, overlap=2)
        chunks = chunker.chunk(doc)

        # step = 5 - 2 = 3: [0:5],[3:8],[6:10],[9:10]
        assert len(chunks) == 4
        assert chunks[0].content == "ABCDE"
        assert chunks[1].content == "DEFGH"
        assert chunks[2].content == "GHIJ"
        assert chunks[3].content == "J"

    def test_text_shorter_than_chunk_size(self):
        doc = _make_document("Short")
        chunker = FixedSizeChunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 1
        assert chunks[0].content == "Short"

    def test_overlap_greater_than_chunk_size_raises(self):
        with pytest.raises(ValueError, match="overlap"):
            FixedSizeChunker(chunk_size=10, overlap=10)

    def test_overlap_equal_to_chunk_size_raises(self):
        with pytest.raises(ValueError, match="overlap"):
            FixedSizeChunker(chunk_size=10, overlap=10)

    def test_metadata_contains_source_info(self):
        doc = _make_document("Hello world")
        chunker = FixedSizeChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        meta = json.loads(chunks[0].metadata)
        assert "source_uri" in meta
        assert "document_type" in meta
        assert meta["name"] == "test.md"
        assert meta["start"] == 0
        assert meta["end"] == 11
        assert meta["length"] == 11
        assert meta["chunk_index"] == 0

    def test_chunks_reference_document_id(self):
        doc = _make_document("Content")
        chunker = FixedSizeChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        for chunk in chunks:
            assert chunk.document_id == doc.id

    def test_chunks_have_unique_ids(self):
        doc = _make_document("A" * 200)
        chunker = FixedSizeChunker(chunk_size=50, overlap=0)
        chunks = chunker.chunk(doc)

        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_empty_content(self):
        doc = _make_document("")
        chunker = FixedSizeChunker(chunk_size=50, overlap=0)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 0

    def test_chunk_index_sequential(self):
        doc = _make_document("A" * 150)
        chunker = FixedSizeChunker(chunk_size=50, overlap=0)
        chunks = chunker.chunk(doc)

        for i, chunk in enumerate(chunks):
            meta = json.loads(chunk.metadata)
            assert meta["chunk_index"] == i


class TestRecursiveChunker:
    """Tests for RecursiveChunker."""

    def test_basic_split_by_paragraph(self):
        # max_size=5 强制按段落切分（每段 3 个中文字符 < 5）
        doc = _make_document("段落一\n\n段落二\n\n段落三")
        chunker = RecursiveChunker(max_size=5)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 3
        contents = [c.content for c in chunks]
        assert "段落一" in contents[0]
        assert "段落二" in contents[1]
        assert "段落三" in contents[2]

    def test_split_by_sentence_when_paragraph_too_long(self):
        # 每段都超过 max_size，需要按句子进一步切分
        long_para = "这是一段很长的文本。" * 100
        doc = _make_document(long_para)
        chunker = RecursiveChunker(max_size=50)
        chunks = chunker.chunk(doc)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.content) <= 50

    def test_empty_content_returns_empty(self):
        doc = _make_document("")
        chunker = RecursiveChunker()
        chunks = chunker.chunk(doc)

        assert len(chunks) == 0

    def test_whitespace_only_content(self):
        # 空白字符非空，应该能产生一个 chunk（如果 len <= max_size）
        doc = _make_document("   ")
        chunker = RecursiveChunker(max_size=10)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 1
        assert chunks[0].content == "   "

    def test_single_chunk_within_max_size(self):
        doc = _make_document("短文本")
        chunker = RecursiveChunker(max_size=512)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 1
        assert chunks[0].content == "短文本"

    def test_fallback_truncation(self):
        # 一段没有分隔符的超长文本
        long_text = "A" * 1000
        doc = _make_document(long_text)
        chunker = RecursiveChunker(separators=["\n\n", "\n"], max_size=100)
        chunks = chunker.chunk(doc)

        # 兜底截断到 max_size
        assert len(chunks) == 1
        assert len(chunks[0].content) == 100

    def test_custom_separators(self):
        # max_size=3 强制按分隔符切分（每段 3 字符 = max_size）
        doc = _make_document("aaa|bbb|ccc")
        chunker = RecursiveChunker(separators=["|"], max_size=3)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 3
        contents = [c.content for c in chunks]
        assert "aaa" in contents
        assert "bbb" in contents
        assert "ccc" in contents

    def test_metadata_contains_source_info(self):
        doc = _make_document("Hello world")
        chunker = RecursiveChunker(max_size=100)
        chunks = chunker.chunk(doc)

        meta = json.loads(chunks[0].metadata)
        assert "source_uri" in meta
        assert "document_type" in meta
        assert meta["name"] == "test.md"
        assert meta["length"] == len("Hello world")

    def test_chunks_reference_document_id(self):
        doc = _make_document("段落一\n\n段落二")
        chunker = RecursiveChunker(max_size=100)
        chunks = chunker.chunk(doc)

        for chunk in chunks:
            assert chunk.document_id == doc.id

    def test_chunks_have_unique_ids(self):
        doc = _make_document("A\n\nB\n\nC\n\nD")
        chunker = RecursiveChunker(max_size=100)
        chunks = chunker.chunk(doc)

        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunks_have_knowledge_base_id(self):
        doc = _make_document("Text")
        doc.knowledge_base_id = "kb-42"
        chunker = RecursiveChunker(max_size=100)
        chunks = chunker.chunk(doc)

        assert chunks[0].knowledge_base_id == "kb-42"

    def test_mixed_separators(self):
        # max_size=4 强制按段落切分
        text = "第一段。\n\n第二段！\n\n第三段？"
        doc = _make_document(text)
        chunker = RecursiveChunker(max_size=4)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 3


class TestRecursiveSplitClassMethod:
    """Tests for RecursiveChunker.recursive_split classmethod."""

    def test_empty_text(self):
        doc = _make_document("")
        result = RecursiveChunker.recursive_split(doc, "", ["\n"], 100)
        assert result == []

    def test_text_within_limit(self):
        doc = _make_document("")
        result = RecursiveChunker.recursive_split(doc, "short", ["\n"], 100)
        assert len(result) == 1
        assert result[0].content == "short"

    def test_split_on_first_matching_separator(self):
        doc = _make_document("")
        # max_size=1 强制切分
        result = RecursiveChunker.recursive_split(doc, "a\nb", ["\n", " "], 1)
        assert len(result) == 2

    def test_falls_through_to_next_separator(self):
        doc = _make_document("")
        # 没有 \n，但有空格；max_size=1 强制切分
        result = RecursiveChunker.recursive_split(doc, "a b c", ["\n", " "], 1)
        assert len(result) == 3

    def test_truncation_when_no_separator_matches(self):
        doc = _make_document("")
        long_text = "A" * 200
        result = RecursiveChunker.recursive_split(doc, long_text, ["\n"], 50)
        assert len(result) == 1
        assert len(result[0].content) == 50


def _make_pdf_document(content: str, page_spans: list[PageSpan]) -> Document:
    return Document(
        id=uuid.uuid4().hex,
        name="doc.pdf",
        source_uri="/tmp/doc.pdf",
        document_type=DocumentType.PDF,
        content=content,
        page_count=max((s.page for s in page_spans), default=0),
        page_spans=page_spans,
        sha256=b"\x00" * 32,
        sim_hash_64=b"\x00" * 8,
    )


class TestChunkPageAttribution:
    """chunk 页码由偏移反查得到：正文不含页码标记，跨页语义不被割裂。"""

    def test_recursive_chunks_carry_page_metadata(self):
        # 两页各一句话，用 "\n" 连接；分块按语义边界切，页码由偏移反查
        content = "page one text\npage two text"
        doc = _make_pdf_document(
            content,
            [PageSpan(page=1, start=0, end=13), PageSpan(page=2, start=14, end=27)],
        )
        chunks = RecursiveChunker(max_size=15).chunk(doc)

        assert len(chunks) == 2
        meta0 = json.loads(chunks[0].metadata)
        meta1 = json.loads(chunks[1].metadata)
        assert (meta0["page_start"], meta0["page_end"]) == (1, 1)
        assert (meta1["page_start"], meta1["page_end"]) == (2, 2)
        assert meta0["start"] == 0 and meta0["end"] == 13
        assert meta1["start"] == 14 and meta1["end"] == 27

    def test_chunk_spanning_pages_records_range(self):
        content = "page one text\npage two text"
        doc = _make_pdf_document(
            content,
            [PageSpan(page=1, start=0, end=13), PageSpan(page=2, start=14, end=27)],
        )
        chunks = FixedSizeChunker(chunk_size=20, overlap=0).chunk(doc)

        # 第一个 chunk 覆盖 [0, 20)，横跨两页
        meta = json.loads(chunks[0].metadata)
        assert (meta["page_start"], meta["page_end"]) == (1, 2)

    def test_no_page_metadata_for_plain_text(self):
        doc = _make_document("plain text without pages")
        chunks = RecursiveChunker(max_size=100).chunk(doc)

        meta = json.loads(chunks[0].metadata)
        assert "page_start" not in meta
        assert "page_end" not in meta

    def test_recursive_chunk_offsets_consistent(self):
        text = ("para one. " * 5 + "\n\n") * 4 + "para end"
        doc = _make_document(text)
        chunks = RecursiveChunker(max_size=30).chunk(doc)

        assert len(chunks) > 1
        for chunk in chunks:
            meta = json.loads(chunk.metadata)
            assert text[meta["start"]:meta["end"]] == chunk.content
