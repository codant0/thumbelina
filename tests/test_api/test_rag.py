"""Tests for RAG API routes."""

from __future__ import annotations

import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.rag.common.orm_models import (
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

    async def _kb_update(kb_id: str, name: str | None = None, description: str | None = None):
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
        doc_id: str | None = None,
        **_kwargs,
    ):
        nonlocal _doc_counter
        _doc_counter += 1
        resolved_id = doc_id or f"doc-{_doc_counter}"
        doc = _make_doc(resolved_id, kb_id, name, doc_type, chunk_count)
        doc_store[resolved_id] = doc
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
        to_delete = [did for did, d in doc_store.items() if d.knowledge_base_id == kb_id]
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
    app.state.engine = MagicMock()

    from thumbelina.rag.pipeline.upload_tasks import UploadTaskManager

    app.state.rag_upload_tasks = UploadTaskManager()

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


def _wait_task_done(client, task_id: str, timeout: float = 5.0) -> dict:
    """轮询任务状态直至终态。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/rag/upload-tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s")


def _wait_no_tmp_files(pattern: str, timeout: float = 5.0) -> list[Path]:
    """轮询直至 /tmp_file 下无匹配文件，返回最终匹配结果。"""
    tmp_dir = Path("/tmp_file")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = list(tmp_dir.glob(pattern))
        if not matches:
            return matches
        time.sleep(0.05)
    return list(tmp_dir.glob(pattern))


@pytest.fixture(autouse=False)
def mock_rag_pipeline():
    """Patch Indexer/Loaders in the rag route module to avoid importing torch."""
    mock_indexer_cls = MagicMock()
    mock_stats = MagicMock()
    mock_stats.indexed_count = 0
    mock_stats.errors = []
    default_doc = MagicMock()
    default_doc.id = uuid.uuid4().hex
    default_doc.name = "test.md"
    default_doc.source_uri = "/tmp/test.md"
    default_doc.sha256 = b"\x00" * 32
    default_doc.sim_hash_64 = b"\x00" * 8
    mock_stats.documents = [default_doc]
    mock_indexer_cls.return_value.index.return_value = mock_stats
    mock_indexer_cls.return_value.index_documents.return_value = mock_stats
    mock_indexer_cls.return_value.index_batch.return_value = mock_stats

    mock_text_loader_cls = MagicMock()
    mock_chunker_cls = MagicMock()
    mock_dedup_cls = MagicMock()

    with (
        patch("thumbelina.api.routes.rag.Indexer", mock_indexer_cls),
        patch("thumbelina.api.routes.rag.TextLoader", mock_text_loader_cls),
        patch("thumbelina.api.routes.rag.RecursiveChunker", mock_chunker_cls),
        patch("thumbelina.api.routes.rag.DocumentDeduplicator", mock_dedup_cls),
    ):
        yield mock_indexer_cls


@pytest.fixture(autouse=False)
def mock_rag_retrieval():
    """Patch SimpleRetriever in the rag route module to avoid importing torch."""
    mock_retriever_cls = MagicMock()
    mock_retriever_cls.return_value.retrieve.return_value = []

    with patch("thumbelina.rag.retrieval.strategies.SimpleRetriever", mock_retriever_cls):
        yield mock_retriever_cls


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
        resp = rag_client.post("/api/v1/rag/knowledge-bases", json={"name": "A"})
        assert resp.status_code == 200

    def test_update_knowledge_base(self, rag_client):
        create_resp = rag_client.post("/api/v1/rag/knowledge-bases", json={"name": "A"})
        kb_id = create_resp.json()["id"]
        resp = rag_client.put(
            f"/api/v1/rag/knowledge-bases/{kb_id}",
            json={"name": "B", "description": "updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "B"

    def test_delete_knowledge_base(self, rag_client):
        create_resp = rag_client.post("/api/v1/rag/knowledge-bases", json={"name": "X"})
        kb_id = create_resp.json()["id"]
        resp = rag_client.delete(f"/api/v1/rag/knowledge-bases/{kb_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_default_kb_fails(self, rag_client):
        resp = rag_client.delete("/api/v1/rag/knowledge-bases/0")
        assert resp.status_code == 400

    def test_update_nonexistent_kb_returns_404(self, rag_client):
        resp = rag_client.put("/api/v1/rag/knowledge-bases/no-such", json={"name": "X"})
        assert resp.status_code == 404


# ---------- Document Management Tests ----------


class TestDocumentManagement:
    def test_list_documents_empty(self, rag_client):
        resp = rag_client.get("/api/v1/rag/knowledge-bases/0/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_document(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 2
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "a.md"
        fake_doc.source_uri = "/tmp/a.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        upload_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("a.md", b"content", "text/markdown")},
        )
        task = _wait_task_done(rag_client, upload_resp.json()["task_id"])
        doc_id = task["result"]["uploaded"][0]["id"]
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


# ---------- Document Chunks Tests ----------


class TestDocumentChunks:
    def test_list_document_chunks(self, rag_client, mock_rag_pipeline):
        """GET /documents/{doc_id}/chunks 应返回该文档的所有 chunks。"""
        mock_stats = MagicMock()
        mock_stats.indexed_count = 2
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "test.md"
        fake_doc.source_uri = "/tmp/test.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        upload_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.md", b"# Test\nHello", "text/markdown")},
        )
        task = _wait_task_done(rag_client, upload_resp.json()["task_id"])
        doc_id = task["result"]["uploaded"][0]["id"]

        # Mock the vector store's query_by_metadata
        mock_store = MagicMock()
        mock_chunk1 = MagicMock()
        mock_chunk1.id = "chunk-1"
        mock_chunk1.document_id = doc_id
        mock_chunk1.content = "chunk content 1"
        mock_chunk1.metadata = "{}"
        mock_chunk2 = MagicMock()
        mock_chunk2.id = "chunk-2"
        mock_chunk2.document_id = doc_id
        mock_chunk2.content = "chunk content 2"
        mock_chunk2.metadata = "{}"
        mock_store.query_by_metadata.return_value = [mock_chunk1, mock_chunk2]

        store_manager = rag_client.app.state.rag_store_manager
        store_manager.get_or_create_store.return_value = mock_store

        resp = rag_client.get(f"/api/v1/rag/documents/{doc_id}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "chunk-1"
        assert data[0]["content"] == "chunk content 1"
        assert data[1]["id"] == "chunk-2"

        # Verify query_by_metadata was called with correct filter
        mock_store.query_by_metadata.assert_called_once_with(where={"document_id": doc_id})

    def test_list_chunks_nonexistent_document_returns_404(self, rag_client):
        resp = rag_client.get("/api/v1/rag/documents/no-such/chunks")
        assert resp.status_code == 404

    def test_list_chunks_empty(self, rag_client, mock_rag_pipeline):
        """文档存在但没有 chunks 时返回空列表。"""
        mock_stats = MagicMock()
        mock_stats.indexed_count = 0
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "empty.md"
        fake_doc.source_uri = "/tmp/empty.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        upload_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("empty.md", b"", "text/markdown")},
        )
        task = _wait_task_done(rag_client, upload_resp.json()["task_id"])
        doc_id = task["result"]["uploaded"][0]["id"]

        mock_store = MagicMock()
        mock_store.query_by_metadata.return_value = []
        store_manager = rag_client.app.state.rag_store_manager
        store_manager.get_or_create_store.return_value = mock_store

        resp = rag_client.get(f"/api/v1/rag/documents/{doc_id}/chunks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_document_cleans_vectors(self, rag_client, mock_rag_pipeline):
        """DELETE /documents/{doc_id} 应同时清理向量库中的 chunks。"""
        mock_stats = MagicMock()
        mock_stats.indexed_count = 1
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "del.md"
        fake_doc.source_uri = "/tmp/del.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        upload_resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("del.md", b"content", "text/markdown")},
        )
        task = _wait_task_done(rag_client, upload_resp.json()["task_id"])
        doc_id = task["result"]["uploaded"][0]["id"]

        mock_store = MagicMock()
        store_manager = rag_client.app.state.rag_store_manager
        store_manager.get_or_create_store.return_value = mock_store

        resp = rag_client.delete(f"/api/v1/rag/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify vector cleanup was called
        mock_store.delete_by_metadata.assert_called_once_with(where={"document_id": doc_id})


# ---------- Async Upload Tests ----------


class TestAsyncUpload:
    def test_upload_returns_202_and_task_id(self, rag_client, mock_rag_pipeline):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.md", b"# Test\nHello", "text/markdown")},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data

        task = _wait_task_done(rag_client, data["task_id"])
        assert task["status"] == "completed"
        assert task["kind"] == "file"
        assert task["label"] == "test.md"
        assert task["result"]["uploaded"][0]["name"] == "test.md"

    def test_upload_indexes_document_record(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 3
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "test.md"
        fake_doc.source_uri = "/tmp/test.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.md", b"# Test", "text/markdown")},
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"

        docs = rag_client.get("/api/v1/rag/knowledge-bases/0/documents").json()
        assert len(docs) == 1
        assert docs[0]["chunk_count"] == 3

    def test_upload_unsupported_type_returns_400(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.docx", b"PK fake", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_failure_marks_task_failed(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 0
        mock_stats.errors = ["加载失败: 文件损坏"]
        mock_stats.documents = []
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("bad.md", b"x", "text/markdown")},
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "failed"
        assert "加载失败" in task["error"]

    def test_upload_to_missing_kb_returns_404(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/no-such/documents",
            files={"file": ("a.md", b"x", "text/markdown")},
        )
        assert resp.status_code == 404


# ---------- Upload Task Endpoint Tests ----------


class TestUploadTaskEndpoints:
    def test_get_unknown_task_returns_404(self, rag_client):
        resp = rag_client.get("/api/v1/rag/upload-tasks/nope")
        assert resp.status_code == 404

    def test_list_tasks_by_kb(self, rag_client, mock_rag_pipeline):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("a.md", b"x", "text/markdown")},
        )
        task_id = resp.json()["task_id"]
        _wait_task_done(rag_client, task_id)
        listing = rag_client.get("/api/v1/rag/knowledge-bases/0/upload-tasks").json()
        assert any(t["id"] == task_id for t in listing)

    def test_cancel_terminal_task_removes_it(self, rag_client, mock_rag_pipeline):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("a.md", b"x", "text/markdown")},
        )
        task_id = resp.json()["task_id"]
        _wait_task_done(rag_client, task_id)
        del_resp = rag_client.delete(f"/api/v1/rag/upload-tasks/{task_id}")
        assert del_resp.status_code == 200
        assert rag_client.get(f"/api/v1/rag/upload-tasks/{task_id}").status_code == 404

    def test_cancel_unknown_task_returns_404(self, rag_client):
        resp = rag_client.delete("/api/v1/rag/upload-tasks/nope")
        assert resp.status_code == 404

    def test_cancel_running_or_queued_task_and_tmp_cleanup(self, rag_client, mock_rag_pipeline):
        """取消排队中的任务：状态置 cancelled，且临时文件不泄漏。"""
        release = threading.Event()
        default_stats = mock_rag_pipeline.return_value.index.return_value

        def blocking_index(path, progress_cb=None, cancel_event=None):
            assert release.wait(timeout=5), "index blocked timed out"
            return default_stats

        mock_rag_pipeline.return_value.index.side_effect = blocking_index

        suffix = uuid.uuid4().hex[:8]
        name_a = f"cancel_a_{suffix}.md"
        name_b = f"cancel_b_{suffix}.md"
        try:
            # A 先上传：占用信号量保持 running（index 阻塞在 threading.Event）
            resp_a = rag_client.post(
                "/api/v1/rag/knowledge-bases/0/documents",
                files={"file": (name_a, b"aaa", "text/markdown")},
            )
            assert resp_a.status_code == 202
            task_a = resp_a.json()["task_id"]

            # B 后上传：信号量被占用，排队 pending
            resp_b = rag_client.post(
                "/api/v1/rag/knowledge-bases/0/documents",
                files={"file": (name_b, b"bbb", "text/markdown")},
            )
            assert resp_b.status_code == 202
            task_b = resp_b.json()["task_id"]

            # 取消排队中的 B：pending 快速路径立即置 cancelled
            cancel_resp = rag_client.delete(f"/api/v1/rag/upload-tasks/{task_b}")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json() == {"cancelled": True}
            b_data = rag_client.get(f"/api/v1/rag/upload-tasks/{task_b}").json()
            assert b_data["status"] == "cancelled"
        finally:
            release.set()

        # A 完成后 B 的 run() 走 skip 路径，cleanup 仍须删除 B 的临时文件
        a_final = _wait_task_done(rag_client, task_a)
        assert a_final["status"] == "completed"
        assert not _wait_no_tmp_files(f"upload_*_{name_b}"), "cancelled task tmp file leaked"
        assert not _wait_no_tmp_files(f"upload_*_{name_a}"), "completed task tmp file leaked"

    def test_successful_upload_cleans_tmp_file(self, rag_client, mock_rag_pipeline):
        """成功上传完成后，临时文件应被清理。"""
        suffix = uuid.uuid4().hex[:8]
        name = f"clean_{suffix}.md"
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": (name, b"# Test", "text/markdown")},
        )
        assert resp.status_code == 202
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert not _wait_no_tmp_files(f"upload_*_{name}"), "completed task tmp file leaked"


# ---------- Async Batch / URL Upload Tests ----------


class TestAsyncBatchAndUrlUpload:
    def test_batch_upload_returns_202_and_completes(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 1
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "a.md"
        fake_doc.source_uri = "/tmp/a.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/batch",
            files=[
                ("files", ("a.md", b"aaa", "text/markdown")),
                ("files", ("b.md", b"bbb", "text/markdown")),
            ],
        )
        assert resp.status_code == 202
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert task["kind"] == "batch"
        assert task["total_files"] == 2
        assert len(task["result"]["uploaded"]) == 2

    def test_batch_unsupported_files_recorded_as_skipped(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 1
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "a.md"
        fake_doc.source_uri = "/tmp/a.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/batch",
            files=[
                ("files", ("a.md", b"aaa", "text/markdown")),
                ("files", ("c.docx", b"PK", "application/octet-stream")),
            ],
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert task["result"]["skipped"] == ["c.docx"]

    def test_url_upload_returns_202_and_completes(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 4
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "example.com"
        fake_doc.source_uri = "https://example.com/a"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/url",
            json={"url": "https://example.com/a"},
        )
        assert resp.status_code == 202
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert task["kind"] == "url"
        assert task["label"] == "https://example.com/a"

    def test_url_upload_invalid_scheme_returns_400(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/url",
            json={"url": "ftp://example.com"},
        )
        assert resp.status_code == 400

    def test_url_upload_no_content_marks_failed(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 0
        mock_stats.errors = []
        mock_stats.documents = []
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/url",
            json={"url": "https://example.com/empty"},
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "failed"
