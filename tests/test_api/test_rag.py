"""Tests for RAG API routes."""

from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.rag.knowledge_base.orm_models import (
    DocumentRecord,
    KnowledgeBaseRecord,
)

# ---------- Fixtures ----------

_FAKE_NOW = datetime(2026, 7, 22, 12, 0, 0)


def _make_kb(id: str, name: str, description: str | None = None) -> MagicMock:
    kb = MagicMock(spec=KnowledgeBaseRecord)
    kb.id = id
    kb.name = name
    kb.description = description
    kb.created_at = _FAKE_NOW
    kb.updated_at = _FAKE_NOW
    return kb


def _make_doc(
    id: str,
    kb_id: str,
    name: str,
    doc_type: str = ".md",
    chunk_count: int = 0,
) -> MagicMock:
    doc = MagicMock(spec=DocumentRecord)
    doc.id = id
    doc.knowledge_base_id = kb_id
    doc.name = name
    doc.source_uri = f"/tmp/{name}"
    doc.doc_type = doc_type
    doc.chunk_count = chunk_count
    doc.created_at = _FAKE_NOW
    return doc


@pytest.fixture
def rag_client(client):
    """Extend the base test client with mock RAG components."""
    default_kb = _make_kb("0", "通用知识库", "通用知识库，默认使用该知识库")

    # --- KnowledgeBaseRepository mock ---
    kb_store: dict[str, MagicMock] = {"0": default_kb}

    async def _kb_list_all():
        return list(kb_store.values())

    async def _kb_get(kb_id: str):
        return kb_store.get(kb_id)

    async def _kb_create(kb_id: str, name: str, description: str | None = None):
        if kb_id in kb_store:
            raise ValueError(f"知识库 {kb_id} 已存在")
        kb = _make_kb(kb_id, name, description)
        kb_store[kb_id] = kb
        return kb

    async def _kb_update(
        kb_id: str, name: str | None = None, description: str | None = None
    ):
        kb = kb_store.get(kb_id)
        if kb is None:
            raise ValueError(f"知识库 {kb_id} 不存在")
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        return kb

    async def _kb_delete(kb_id: str) -> bool:
        if kb_id == "0":
            raise ValueError("通用知识库不可删除")
        if kb_id not in kb_store:
            return False
        del kb_store[kb_id]
        return True

    kb_repo = MagicMock()
    kb_repo.list_all = AsyncMock(side_effect=_kb_list_all)
    kb_repo.get = AsyncMock(side_effect=_kb_get)
    kb_repo.create = AsyncMock(side_effect=_kb_create)
    kb_repo.update = AsyncMock(side_effect=_kb_update)
    kb_repo.delete = AsyncMock(side_effect=_kb_delete)

    # --- DocumentRepository mock ---
    doc_store: dict[str, MagicMock] = {}
    _doc_counter = 0

    async def _doc_create(
        kb_id: str,
        name: str,
        source_uri: str,
        doc_type: str,
        chunk_count: int = 0,
    ):
        nonlocal _doc_counter
        _doc_counter += 1
        doc_id = f"doc-{_doc_counter}"
        doc = _make_doc(doc_id, kb_id, name, doc_type, chunk_count)
        doc_store[doc_id] = doc
        return doc

    async def _doc_get(doc_id: str):
        return doc_store.get(doc_id)

    async def _doc_list_by_kb(kb_id: str):
        return [d for d in doc_store.values() if d.knowledge_base_id == kb_id]

    async def _doc_delete(doc_id: str) -> bool:
        if doc_id not in doc_store:
            return False
        del doc_store[doc_id]
        return True

    async def _doc_delete_by_kb(kb_id: str) -> int:
        to_delete = [
            did for did, d in doc_store.items() if d.knowledge_base_id == kb_id
        ]
        for did in to_delete:
            del doc_store[did]
        return len(to_delete)

    doc_repo = MagicMock()
    doc_repo.create = AsyncMock(side_effect=_doc_create)
    doc_repo.get = AsyncMock(side_effect=_doc_get)
    doc_repo.list_by_kb = AsyncMock(side_effect=_doc_list_by_kb)
    doc_repo.delete = AsyncMock(side_effect=_doc_delete)
    doc_repo.delete_by_kb = AsyncMock(side_effect=_doc_delete_by_kb)

    # --- Store manager mock ---
    store_manager = MagicMock()
    store_manager.get_or_create_store = MagicMock()
    store_manager.delete_store = MagicMock()

    # --- Embedding registry mock ---
    embedding_registry = MagicMock()
    embedding_registry.create = MagicMock()

    # Attach to app.state
    app = client.app
    app.state.rag_kb_repo = kb_repo
    app.state.rag_doc_repo = doc_repo
    app.state.rag_store_manager = store_manager
    app.state.rag_embedding_registry = embedding_registry

    return client


# ---------- Helpers for mocking heavy imports ----------


def _install_mock_module(module_path: str, attrs: dict | None = None) -> None:
    """Install a fake module in sys.modules to avoid importing torch/chromadb."""
    if module_path not in sys.modules:
        mod = ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod


@pytest.fixture(autouse=False)
def mock_rag_pipeline():
    """Fake thumbelina.rag.pipeline.indexer to avoid importing torch."""
    saved = {}
    try:
        # Install fake modules for the import chain
        for mod_path in [
            "torch",
            "thumbelina.rag.embedding.provider_hf",
            "thumbelina.rag.pipeline.indexer",
        ]:
            saved[mod_path] = sys.modules.get(mod_path)
            if mod_path not in sys.modules:
                sys.modules[mod_path] = ModuleType(mod_path)

        mock_indexer_cls = MagicMock()
        mock_stats = MagicMock()
        mock_stats.indexed_count = 0
        mock_indexer_cls.return_value.index.return_value = mock_stats
        sys.modules["thumbelina.rag.pipeline.indexer"].Indexer = mock_indexer_cls

        yield mock_indexer_cls
    finally:
        for mod_path, original in saved.items():
            if original is None:
                sys.modules.pop(mod_path, None)
            else:
                sys.modules[mod_path] = original


@pytest.fixture(autouse=False)
def mock_rag_retrieval():
    """Fake thumbelina.rag.retrieval.strategies to avoid importing torch."""
    saved = {}
    try:
        for mod_path in [
            "torch",
            "thumbelina.rag.embedding.provider_hf",
            "thumbelina.rag.retrieval.strategies",
        ]:
            saved[mod_path] = sys.modules.get(mod_path)
            if mod_path not in sys.modules:
                sys.modules[mod_path] = ModuleType(mod_path)

        mock_retriever_cls = MagicMock()
        mock_retriever_cls.return_value.retrieve.return_value = []
        sys.modules["thumbelina.rag.retrieval.strategies"].SimpleRetriever = (
            mock_retriever_cls
        )

        yield mock_retriever_cls
    finally:
        for mod_path, original in saved.items():
            if original is None:
                sys.modules.pop(mod_path, None)
            else:
                sys.modules[mod_path] = original


# ---------- Knowledge Base CRUD Tests ----------


class TestKnowledgeBaseCRUD:
    def test_list_knowledge_bases(self, rag_client):
        resp = rag_client.get("/api/v1/rag/knowledge-bases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(kb["id"] == "0" for kb in data)

    def test_create_knowledge_base(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases",
            json={"name": "技术文档", "description": "技术相关文档"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "技术文档"
        assert "id" in data

    def test_create_duplicate_name_allowed(self, rag_client):
        """不同知识库可以同名。"""
        rag_client.post("/api/v1/rag/knowledge-bases", json={"name": "A"})
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases", json={"name": "A"}
        )
        assert resp.status_code == 200

    def test_update_knowledge_base(self, rag_client):
        create_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases", json={"name": "A"}
        )
        kb_id = create_resp.json()["id"]
        resp = rag_client.put(
            f"/api/v1/rag/knowledge-bases/{kb_id}",
            json={"name": "B", "description": "updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "B"

    def test_delete_knowledge_base(self, rag_client):
        create_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases", json={"name": "X"}
        )
        kb_id = create_resp.json()["id"]
        resp = rag_client.delete(f"/api/v1/rag/knowledge-bases/{kb_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_default_kb_fails(self, rag_client):
        resp = rag_client.delete("/api/v1/rag/knowledge-bases/0")
        assert resp.status_code == 400

    def test_update_nonexistent_kb_returns_404(self, rag_client):
        resp = rag_client.put(
            "/api/v1/rag/knowledge-bases/no-such", json={"name": "X"}
        )
        assert resp.status_code == 404


# ---------- Document Management Tests ----------


class TestDocumentManagement:
    def test_list_documents_empty(self, rag_client):
        resp = rag_client.get("/api/v1/rag/knowledge-bases/0/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_upload_document(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 3
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.md", b"# Test\nHello", "text/markdown")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test.md"
        assert data["knowledge_base_id"] == "0"
        assert data["chunk_count"] == 3

    def test_upload_unsupported_type_returns_400(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.docx", b"PK fake", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_delete_document(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 2
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        upload_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("a.md", b"content", "text/markdown")},
        )
        doc_id = upload_resp.json()["id"]
        resp = rag_client.delete(f"/api/v1/rag/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_nonexistent_document_returns_404(self, rag_client):
        resp = rag_client.delete("/api/v1/rag/documents/no-such")
        assert resp.status_code == 404


# ---------- RAG Query Tests ----------


class TestRAGQuery:
    def test_query_returns_results(self, rag_client, mock_rag_retrieval):
        mock_chunk = MagicMock()
        mock_chunk.content = "test content"
        mock_chunk.score = 0.95
        mock_chunk.metadata = "source: test.md"
        mock_rag_retrieval.return_value.retrieve.return_value = [mock_chunk]

        resp = rag_client.post(
            "/api/v1/rag/query",
            json={
                "query": "测试问题",
                "knowledge_base_id": "0",
                "top_k": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["content"] == "test content"
        assert data["results"][0]["score"] == 0.95

    def test_query_empty_results(self, rag_client, mock_rag_retrieval):
        """空知识库查询应返回空列表。"""
        mock_rag_retrieval.return_value.retrieve.return_value = []
        resp = rag_client.post(
            "/api/v1/rag/query",
            json={"query": "任意问题", "knowledge_base_id": "0"},
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == []
