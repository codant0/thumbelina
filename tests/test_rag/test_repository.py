"""Tests for RAG knowledge base and document repositories."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thumbelina.rag.knowledge_base.db import init_rag_db
from thumbelina.rag.knowledge_base.repository import (
    DocumentRepository,
    KnowledgeBaseRepository,
)


class TestKnowledgeBaseRepository:
    @pytest.fixture
    def repo(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        sf = init_rag_db(engine)
        return KnowledgeBaseRepository(session_factory=sf)

    @pytest.mark.asyncio
    async def test_list_all_includes_default(self, repo):
        kbs = await repo.list_all()
        assert len(kbs) == 1
        assert kbs[0].id == "0"
        assert kbs[0].name == "通用知识库"

    @pytest.mark.asyncio
    async def test_create_and_get(self, repo):
        kb = await repo.create("kb-1", "技术文档", "技术相关文档")
        assert kb.id == "kb-1"
        fetched = await repo.get("kb-1")
        assert fetched is not None
        assert fetched.name == "技术文档"
        assert fetched.description == "技术相关文档"

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, repo):
        await repo.create("kb-1", "A", "")
        with pytest.raises(ValueError, match="已存在"):
            await repo.create("kb-1", "B", "")

    @pytest.mark.asyncio
    async def test_update_name_and_description(self, repo):
        await repo.create("kb-1", "A", "desc")
        updated = await repo.update("kb-1", name="B", description="new desc")
        assert updated.name == "B"
        assert updated.description == "new desc"

    @pytest.mark.asyncio
    async def test_update_name_only(self, repo):
        await repo.create("kb-1", "A", "desc")
        updated = await repo.update("kb-1", name="B")
        assert updated.name == "B"
        assert updated.description == "desc"

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, repo):
        with pytest.raises(ValueError, match="不存在"):
            await repo.update("no-such", name="X")

    @pytest.mark.asyncio
    async def test_delete(self, repo):
        await repo.create("kb-1", "A", "")
        result = await repo.delete("kb-1")
        assert result is True
        assert await repo.get("kb-1") is None

    @pytest.mark.asyncio
    async def test_delete_default_raises(self, repo):
        with pytest.raises(ValueError, match="不可删除"):
            await repo.delete("0")

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo):
        result = await repo.delete("no-such")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, repo):
        result = await repo.get("no-such")
        assert result is None


class TestDocumentRepository:
    @pytest.fixture
    def repos(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        sf = init_rag_db(engine)
        return KnowledgeBaseRepository(session_factory=sf), DocumentRepository(session_factory=sf)

    @pytest.mark.asyncio
    async def test_create_and_get(self, repos):
        _, doc_repo = repos
        doc = await doc_repo.create(
            "0", "test.md", "/tmp/test.md", ".md",
            sha256=b"\x00" * 32, sim_hash_64=b"\x00" * 8, chunk_count=10,
        )
        fetched = await doc_repo.get(doc.id)
        assert fetched is not None
        assert fetched.name == "test.md"
        assert fetched.source_uri == "/tmp/test.md"
        assert fetched.doc_type == ".md"
        assert fetched.chunk_count == 10

    @pytest.mark.asyncio
    async def test_create_default_chunk_count(self, repos):
        _, doc_repo = repos
        doc = await doc_repo.create(
            "0", "a.txt", "/a.txt", ".txt",
            sha256=b"\x00" * 32, sim_hash_64=b"\x00" * 8,
        )
        assert doc.chunk_count == 0

    @pytest.mark.asyncio
    async def test_list_by_kb(self, repos):
        _, doc_repo = repos
        await doc_repo.create(
            "0", "a.md", "/a.md", ".md",
            sha256=b"\x00" * 32, sim_hash_64=b"\x00" * 8,
        )
        await doc_repo.create(
            "0", "b.txt", "/b.txt", ".txt",
            sha256=b"\x01" * 32, sim_hash_64=b"\x01" * 8,
        )
        docs = await doc_repo.list_by_kb("0")
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_list_by_kb_empty(self, repos):
        _, doc_repo = repos
        docs = await doc_repo.list_by_kb("0")
        assert len(docs) == 0

    @pytest.mark.asyncio
    async def test_delete(self, repos):
        _, doc_repo = repos
        doc = await doc_repo.create(
            "0", "a.md", "/a.md", ".md",
            sha256=b"\x00" * 32, sim_hash_64=b"\x00" * 8,
        )
        result = await doc_repo.delete(doc.id)
        assert result is True
        assert await doc_repo.get(doc.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repos):
        _, doc_repo = repos
        result = await doc_repo.delete("no-such")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_by_kb(self, repos):
        _, doc_repo = repos
        await doc_repo.create(
            "0", "a.md", "/a.md", ".md",
            sha256=b"\x00" * 32, sim_hash_64=b"\x00" * 8,
        )
        await doc_repo.create(
            "0", "b.txt", "/b.txt", ".txt",
            sha256=b"\x01" * 32, sim_hash_64=b"\x01" * 8,
        )
        count = await doc_repo.delete_by_kb("0")
        assert count == 2
        assert len(await doc_repo.list_by_kb("0")) == 0

    @pytest.mark.asyncio
    async def test_delete_by_kb_empty(self, repos):
        _, doc_repo = repos
        count = await doc_repo.delete_by_kb("0")
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, repos):
        _, doc_repo = repos
        result = await doc_repo.get("no-such")
        assert result is None
