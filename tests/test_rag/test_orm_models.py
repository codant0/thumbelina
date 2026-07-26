"""Tests for RAG SQLAlchemy ORM models."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from thumbelina.rag.knowledge_base.orm_models import (
    DocumentRecord,
    KnowledgeBaseRecord,
    RagBase,
)


class TestRagBase:
    def test_independent_from_memory_base(self):
        from thumbelina.memory.models import Base as MemoryBase

        assert RagBase is not MemoryBase

    def test_tables_created(self):
        engine = create_engine("sqlite:///:memory:")
        RagBase.metadata.create_all(engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        assert "knowledge_bases" in table_names
        assert "rag_documents" in table_names


class TestKnowledgeBaseRecord:
    def test_create_default(self):
        engine = create_engine("sqlite:///:memory:")
        RagBase.metadata.create_all(engine)
        with Session(engine) as session:
            kb = KnowledgeBaseRecord(id="0", name="通用知识库")
            session.add(kb)
            session.commit()
            assert kb.created_at is not None
            assert kb.updated_at is not None

    def test_fields(self):
        kb = KnowledgeBaseRecord(id="kb-1", name="技术文档", description="技术相关")
        assert kb.id == "kb-1"
        assert kb.name == "技术文档"
        assert kb.description == "技术相关"


class TestDocumentRecord:
    def test_create(self):
        engine = create_engine("sqlite:///:memory:")
        RagBase.metadata.create_all(engine)
        with Session(engine) as session:
            kb = KnowledgeBaseRecord(id="0", name="通用知识库")
            session.add(kb)
            doc = DocumentRecord(
                id="doc-1",
                knowledge_base_id="0",
                name="test.md",
                source_uri="/tmp/test.md",
                doc_type=".md",
                sha256=b"\x00" * 32,
                sim_hash_64=b"\x00" * 8,
                chunk_count=5,
            )
            session.add(doc)
            session.commit()
            assert doc.created_at is not None

    def test_default_chunk_count(self):
        doc = DocumentRecord(
            id="doc-2",
            knowledge_base_id="0",
            name="a.txt",
            source_uri="/a.txt",
            doc_type=".txt",
        )
        assert doc.chunk_count == 0
