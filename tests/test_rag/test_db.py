"""Tests for RAG database initialization."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from thumbelina.rag.common.db import init_rag_db
from thumbelina.rag.common.orm_models import KnowledgeBaseRecord


class TestRagDb:
    def test_init_creates_tables(self):
        engine = create_engine("sqlite:///:memory:")
        init_rag_db(engine)
        inspector = inspect(engine)
        assert "knowledge_bases" in inspector.get_table_names()
        assert "rag_documents" in inspector.get_table_names()

    def test_init_seeds_default_knowledge_base(self):
        engine = create_engine("sqlite:///:memory:")
        init_rag_db(engine)
        with Session(engine) as session:
            kb = session.get(KnowledgeBaseRecord, "0")
            assert kb is not None
            assert kb.name == "通用知识库"
            assert kb.description == "通用知识库，默认使用该知识库"

    def test_init_returns_session_factory(self):
        engine = create_engine("sqlite:///:memory:")
        sf = init_rag_db(engine)
        assert sf is not None
        with sf() as session:
            assert session is not None

    def test_init_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        init_rag_db(engine)
        init_rag_db(engine)  # 第二次不应报错
        with Session(engine) as session:
            kbs = session.execute(select(KnowledgeBaseRecord)).scalars().all()
            assert len(kbs) == 1  # 不应重复创建
