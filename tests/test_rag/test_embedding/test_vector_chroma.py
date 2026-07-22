"""Tests for ChromaDB vector store (RAG layer)."""

from __future__ import annotations

import json
import uuid

import chromadb
import pytest

from thumbelina.rag.embedding.vector_chroma import ChromaVectorStore
from thumbelina.rag.knowledge_base.models import Chunk


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
