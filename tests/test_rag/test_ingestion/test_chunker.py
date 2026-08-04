"""Tests for RAG text chunking strategies."""

from __future__ import annotations

import json
import uuid

import pytest

from thumbelina.rag.common.models import Document, DocumentType, PageSpan
from thumbelina.rag.ingestion.chunker import FixedSizeChunker, RecursiveChunker


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

    def test_char_fallback_no_data_loss(self):
        # 一段没有分隔符的超长文本：字符级兜底切分，不能截断丢内容
        long_text = "A" * 1000
        doc = _make_document(long_text)
        chunker = RecursiveChunker(separators=["\n\n", "\n"], max_size=100)
        chunks = chunker.chunk(doc)

        assert len(chunks) > 1
        covered: set[int] = set()
        for chunk in chunks:
            meta = json.loads(chunk.metadata)
            assert len(chunk.content) <= 100
            assert long_text[meta["start"] : meta["end"]] == chunk.content
            covered.update(range(meta["start"], meta["end"]))
        # 原文每个字符都至少被一个块覆盖
        assert covered == set(range(len(long_text)))

    def test_custom_separators(self):
        # max_size=4 强制按分隔符切分（每段 4 字符 = max_size，分隔符保留在段尾）
        doc = _make_document("aaa|bbb|ccc")
        chunker = RecursiveChunker(separators=["|"], max_size=4)
        chunks = chunker.chunk(doc)

        assert [c.content for c in chunks] == ["aaa|", "bbb|", "ccc"]

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


class TestRecursiveChunkerBoundaries:
    """分隔符处理：保留、层级选择、误切防护、参数校验。"""

    def test_separator_kept_in_content(self):
        # 分隔符保留在前一段末尾，不丢失标点
        doc = _make_document("第一段。\n\n第二段。")
        chunks = RecursiveChunker(max_size=4, overlap=0).chunk(doc)
        assert [c.content for c in chunks] == ["第一段。", "第二段。"]

    def test_falls_through_to_next_separator(self):
        # 没有 \n，落到空格分隔符；max_size=1 强制切分
        doc = _make_document("a b c")
        chunks = RecursiveChunker(max_size=1).chunk(doc)
        assert [c.content for c in chunks] == ["a", "b", "c"]

    def test_decimal_not_split_by_period(self):
        # 英文句末分隔符必须带空格，"3.14" 不能被裸 "." 误切
        doc = _make_document("圆周率是3.14，约等于22/7。")
        chunks = RecursiveChunker(max_size=9, overlap=0).chunk(doc)
        assert [c.content for c in chunks] == ["圆周率是3.14，", "约等于22/7。"]

    def test_overlap_bridges_adjacent_chunks(self):
        # 每句 4 字符；相邻块共享尾部句子作为 overlap，且偏移可回溯
        text = "句子一。句子二。句子三。句子四。"
        doc = _make_document(text)
        chunks = RecursiveChunker(max_size=10, overlap=4).chunk(doc)

        assert len(chunks) > 1
        covered: set[int] = set()
        for chunk in chunks:
            meta = json.loads(chunk.metadata)
            assert len(chunk.content) <= 10
            assert text[meta["start"] : meta["end"]] == chunk.content
            covered.update(range(meta["start"], meta["end"]))
        assert covered == set(range(len(text)))
        # 第二块以第一块的尾句开头（overlap 生效）
        assert chunks[1].content.startswith(chunks[0].content[-4:])

    def test_metadata_contains_offsets_and_chunk_index(self):
        doc = _make_document("段落一\n\n段落二")
        chunks = RecursiveChunker(max_size=5, overlap=0).chunk(doc)

        assert len(chunks) == 2
        for i, chunk in enumerate(chunks):
            meta = json.loads(chunk.metadata)
            assert meta["chunk_index"] == i
            assert meta["end"] - meta["start"] == meta["length"]

    def test_invalid_params_raise(self):
        with pytest.raises(ValueError, match="overlap"):
            RecursiveChunker(max_size=10, overlap=10)
        with pytest.raises(ValueError, match="max_size"):
            RecursiveChunker(max_size=0)

    def test_separators_list_not_shared(self):
        # 实例不别名调用方列表，也不污染类属性默认值
        seps = ["|"]
        chunker = RecursiveChunker(separators=seps)
        chunker.separators.append("x")
        assert seps == ["|"]

        before = list(RecursiveChunker.default_separators)
        RecursiveChunker().separators.append("x")
        assert RecursiveChunker.default_separators == before


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
        # 分隔符 "\n" 保留在第一段末尾，第一块覆盖 [0, 14)
        assert chunks[0].content == "page one text\n"
        assert meta0["start"] == 0 and meta0["end"] == 14
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
            assert text[meta["start"] : meta["end"]] == chunk.content
