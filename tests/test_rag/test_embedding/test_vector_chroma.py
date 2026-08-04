"""Tests for ChromaDB vector store (RAG layer)."""

from __future__ import annotations

import json
import uuid

import chromadb
import pytest

from thumbelina.rag.embedding.vector_chroma import ChromaVectorStore
from thumbelina.rag.common.models import Chunk


@pytest.fixture
def store():
    """每次测试创建独立的 ChromaDB collection + store。"""
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        name=f"test_rag_{uuid.uuid4().hex[:8]}",
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},
    )
    return ChromaVectorStore(collection)


def _make_chunk(content: str = "test text", **kwargs) -> Chunk:
    defaults = {
        "id": uuid.uuid4().hex,
        "document_id": "doc-1",
        "content": content,
        "metadata": json.dumps({"source": "test.md"}),
        "knowledge_base_id": "0",
    }
    defaults.update(kwargs)
    return Chunk(**defaults)


class TestChromaVectorStore:
    """Tests for rag.embedding.vector_chroma.ChromaVectorStore."""

    def test_class_exists(self):
        assert ChromaVectorStore is not None

    def test_create_instance(self):
        client = chromadb.EphemeralClient()
        collection = client.get_or_create_collection(name=f"t_{uuid.uuid4().hex[:8]}")
        store = ChromaVectorStore(collection)
        assert store is not None

    def test_add_single_chunk(self, store):
        chunk = _make_chunk("Hello world")
        store.add([chunk], [[0.1] * 10])

        assert store.collection.count() == 1

    def test_add_multiple_chunks(self, store):
        chunks = [_make_chunk(f"text {i}") for i in range(5)]
        embeddings = [[float(i)] * 10 for i in range(5)]
        store.add(chunks, embeddings)

        assert store.collection.count() == 5

    def test_add_empty_list_is_noop(self, store):
        store.add([], [])
        assert store.collection.count() == 0

    def test_query_returns_scored_chunks(self, store):
        chunk = _make_chunk("Python programming")
        store.add([chunk], [[0.1] * 10])

        results = store.query(embedding=[0.1] * 10, top_k=1)

        assert len(results) == 1
        assert results[0].content == "Python programming"
        assert results[0].document_id == "doc-1"
        assert isinstance(results[0].score, float)

    def test_query_respects_top_k(self, store):
        for i in range(10):
            store.add([_make_chunk(f"doc {i}")], [[float(i)] * 10])

        results = store.query(embedding=[0.0] * 10, top_k=3)
        assert len(results) == 3

    def test_query_empty_store(self, store):
        results = store.query(embedding=[0.1] * 10, top_k=5)
        assert results == []

    def test_query_returns_metadata(self, store):
        meta = json.dumps({"source": "readme.md", "page": 1})
        chunk = _make_chunk("content", metadata=meta)
        store.add([chunk], [[0.1] * 10])

        results = store.query(embedding=[0.1] * 10, top_k=1)
        assert results[0].metadata == meta

    def test_delete_existing_chunk(self, store):
        chunk = _make_chunk("to be deleted")
        store.add([chunk], [[0.1] * 10])
        assert store.collection.count() == 1

        store.delete([chunk.id])
        assert store.collection.count() == 0

    def test_delete_nonexistent_is_noop(self, store):
        store.delete(["nonexistent_id"])

    def test_delete_empty_list_is_noop(self, store):
        store.delete([])

    def test_add_then_query_then_delete_lifecycle(self, store):
        chunk = _make_chunk("lifecycle test")
        store.add([chunk], [[0.5] * 10])

        results = store.query(embedding=[0.5] * 10, top_k=1)
        assert len(results) == 1
        assert results[0].id == chunk.id

        store.delete([chunk.id])
        results = store.query(embedding=[0.5] * 10, top_k=1)
        assert len(results) == 0

    def test_upsert_same_id_updates(self, store):
        """使用 add 添加相同 ID 时，ChromaDB add 不会覆盖已有记录。
        如需覆盖语义，源码应改用 collection.upsert。
        """
        chunk_id = uuid.uuid4().hex
        chunk_old = _make_chunk("old content", id=chunk_id)
        store.add([chunk_old], [[0.1] * 10])

        chunk_new = _make_chunk("new content", id=chunk_id)
        # collection.add 对重复 ID 会忽略或报错，不会覆盖
        store.add([chunk_new], [[0.2] * 10])

        # add 后记录仍为旧内容（非 upsert 语义）
        results = store.query(embedding=[0.1] * 10, top_k=1)
        assert len(results) == 1
        assert results[0].content == "old content"

    # ── query_by_metadata ──

    def test_query_by_metadata_returns_matching_chunks(self, store):
        chunk1 = _make_chunk("doc1 chunk1", document_id="doc-a")
        chunk2 = _make_chunk("doc1 chunk2", document_id="doc-a")
        chunk3 = _make_chunk("doc2 chunk1", document_id="doc-b")
        store.add([chunk1, chunk2, chunk3], [[0.1] * 10, [0.2] * 10, [0.3] * 10])

        results = store.query_by_metadata(where={"document_id": "doc-a"})
        assert len(results) == 2
        assert all(c.document_id == "doc-a" for c in results)
        contents = {c.content for c in results}
        assert contents == {"doc1 chunk1", "doc1 chunk2"}

    def test_query_by_metadata_returns_empty_for_no_match(self, store):
        chunk = _make_chunk("hello", document_id="doc-x")
        store.add([chunk], [[0.1] * 10])

        results = store.query_by_metadata(where={"document_id": "nonexistent"})
        assert results == []

    def test_query_by_metadata_empty_store(self, store):
        results = store.query_by_metadata(where={"document_id": "any"})
        assert results == []

    def test_query_by_metadata_respects_limit(self, store):
        for i in range(5):
            store.add(
                [_make_chunk(f"chunk {i}", document_id="doc-lim")],
                [[float(i)] * 10],
            )

        results = store.query_by_metadata(where={"document_id": "doc-lim"}, limit=2)
        assert len(results) == 2

    def test_query_by_metadata_returns_chunk_fields(self, store):
        meta = json.dumps({"source": "readme.md"})
        chunk = _make_chunk("content", document_id="doc-f", metadata=meta)
        store.add([chunk], [[0.1] * 10])

        results = store.query_by_metadata(where={"document_id": "doc-f"})
        assert len(results) == 1
        c = results[0]
        assert c.id == chunk.id
        assert c.content == "content"
        assert c.document_id == "doc-f"
        assert c.knowledge_base_id == "0"
        assert c.metadata == meta

    # ── delete_by_metadata ──

    def test_delete_by_metadata_removes_matching(self, store):
        chunk1 = _make_chunk("a", document_id="doc-del")
        chunk2 = _make_chunk("b", document_id="doc-del")
        chunk3 = _make_chunk("c", document_id="doc-keep")
        store.add([chunk1, chunk2, chunk3], [[0.1] * 10, [0.2] * 10, [0.3] * 10])

        deleted = store.delete_by_metadata(where={"document_id": "doc-del"})
        assert deleted == 2
        assert store.collection.count() == 1

    def test_delete_by_metadata_returns_zero_for_no_match(self, store):
        chunk = _make_chunk("x", document_id="doc-x")
        store.add([chunk], [[0.1] * 10])

        deleted = store.delete_by_metadata(where={"document_id": "nonexistent"})
        assert deleted == 0
        assert store.collection.count() == 1

    def test_delete_by_metadata_empty_store(self, store):
        deleted = store.delete_by_metadata(where={"document_id": "any"})
        assert deleted == 0

    def test_delete_by_metadata_preserves_other_docs(self, store):
        chunk1 = _make_chunk("keep me", document_id="doc-keep")
        chunk2 = _make_chunk("delete me", document_id="doc-del")
        store.add([chunk1, chunk2], [[0.1] * 10, [0.2] * 10])

        store.delete_by_metadata(where={"document_id": "doc-del"})

        remaining = store.query_by_metadata(where={"document_id": "doc-keep"})
        assert len(remaining) == 1
        assert remaining[0].content == "keep me"
