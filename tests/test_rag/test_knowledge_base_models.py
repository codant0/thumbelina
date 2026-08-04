"""Tests for RAG knowledge base data models."""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from thumbelina.rag.common.models import (
    Chunk,
    Document,
    DocumentType,
    KnowledgeBase,
)


class TestDocumentType:
    """Tests for DocumentType enum."""

    def test_txt_value(self):
        assert DocumentType.TXT.value == ".txt"

    def test_markdown_value(self):
        assert DocumentType.MARKDOWN.value == ".md"

    def test_pdf_value(self):
        assert DocumentType.PDF.value == ".pdf"

    def test_from_value_txt(self):
        assert DocumentType.from_value(".txt") is DocumentType.TXT

    def test_from_value_md(self):
        assert DocumentType.from_value(".md") is DocumentType.MARKDOWN

    def test_from_value_pdf(self):
        assert DocumentType.from_value(".pdf") is DocumentType.PDF

    def test_from_value_case_insensitive(self):
        assert DocumentType.from_value(".TXT") is DocumentType.TXT
        assert DocumentType.from_value(".MD") is DocumentType.MARKDOWN
        assert DocumentType.from_value(".Pdf") is DocumentType.PDF

    def test_from_value_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid value"):
            DocumentType.from_value(".docx")

    def test_from_value_empty_raises(self):
        with pytest.raises(ValueError, match="invalid value"):
            DocumentType.from_value("")


class TestKnowledgeBase:
    """Tests for KnowledgeBase model."""

    def test_default_values(self):
        kb = KnowledgeBase()
        assert kb.id == "0"
        assert kb.name == "通用知识库"
        assert kb.description == "通用知识库，默认使用该知识库"

    def test_custom_values(self):
        kb = KnowledgeBase(id="1", name="技术文档", description="技术相关文档")
        assert kb.id == "1"
        assert kb.name == "技术文档"


class TestDocument:
    """Tests for Document model."""

    def _make_doc(self, **kwargs):
        defaults = {
            "id": uuid.uuid4().hex,
            "name": "test.md",
            "source_uri": "/tmp/test.md",
            "document_type": DocumentType.MARKDOWN,
            "content": "Hello world",
            "sha256": b"\x00" * 32,
            "sim_hash_64": b"\x00" * 8,
        }
        defaults.update(kwargs)
        return Document(**defaults)

    def test_create_document(self):
        doc = self._make_doc()
        assert doc.name == "test.md"
        assert doc.content == "Hello world"
        assert doc.document_type is DocumentType.MARKDOWN

    def test_default_knowledge_base_id(self):
        doc = self._make_doc()
        assert doc.knowledge_base_id == "0"

    def test_custom_knowledge_base_id(self):
        doc = self._make_doc(knowledge_base_id="kb-42")
        assert doc.knowledge_base_id == "kb-42"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Document(name="test.md", source_uri="/tmp", document_type=DocumentType.TXT)


class TestChunk:
    """Tests for Chunk model."""

    def _make_chunk(self, **kwargs):
        defaults = {
            "id": uuid.uuid4().hex,
            "document_id": "doc-1",
            "content": "chunk text",
            "metadata": json.dumps({"source": "test.md"}),
            "knowledge_base_id": "0",
        }
        defaults.update(kwargs)
        return Chunk(**defaults)

    def test_create_chunk(self):
        chunk = self._make_chunk()
        assert chunk.content == "chunk text"
        assert chunk.document_id == "doc-1"
        assert chunk.knowledge_base_id == "0"

    def test_metadata_is_json_string(self):
        meta = {"source": "a.txt", "length": 100}
        chunk = self._make_chunk(metadata=json.dumps(meta))
        parsed = json.loads(chunk.metadata)
        assert parsed["source"] == "a.txt"
        assert parsed["length"] == 100

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Chunk(id="1", document_id="d1", content="text")
