"""Tests for RAG retrieval strategies.

注意：strategies.py 顶层 import torch，在无 GPU 环境可能崩溃，
因此在导入前先将 torch 注入 sys.modules。
"""

from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import MagicMock

# 在导入 strategies 之前 mock torch，避免 DLL 加载崩溃
if "torch" not in sys.modules:
    sys.modules["torch"] = types.ModuleType("torch")

from thumbelina.rag.embedding.base import EmbeddingModel, ScoredChunk, VectorStore
from thumbelina.rag.retrieval.strategies import SimpleRetriever


class FakeEmbedding(EmbeddingModel):
    """返回固定向量的 mock embedding。"""

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class FakeVectorStore(VectorStore):
    """可控返回值的 mock vector store。"""

    def __init__(self, results: list[ScoredChunk] | None = None):
        self._results = results or []
        self.query_calls: list[dict] = []

    def add(self, chunks, embeddings):
        pass

    def query(self, embedding: list[float], top_k: int = 5) -> list[ScoredChunk]:
        self.query_calls.append({"embedding": embedding, "top_k": top_k})
        return self._results[:top_k]

    def delete(self, ids):
        pass

    def query_by_metadata(self, where: dict[str, str], limit: int = 100) -> list:
        return []

    def delete_by_metadata(self, where: dict[str, str]) -> int:
        return 0


def _make_scored_chunk(content: str, score: float = 0.9) -> ScoredChunk:
    return ScoredChunk(
        id=uuid.uuid4().hex,
        document_id="doc-1",
        content=content,
        metadata="{}",
        knowledge_base_id="0",
        score=score,
    )


class TestSimpleRetriever:
    """Tests for SimpleRetriever."""

    def test_class_exists(self):
        assert SimpleRetriever is not None

    def test_retrieve_calls_embed(self):
        embedder = MagicMock(spec=EmbeddingModel)
        embedder.embed.return_value = [0.1, 0.2, 0.3]
        store = FakeVectorStore()

        retriever = SimpleRetriever(embedding_model=embedder, vector_store=store)
        retriever.retrieve("test query")

        embedder.embed.assert_called_once_with("test query")

    def test_retrieve_calls_query_with_embedding(self):
        embedder = MagicMock(spec=EmbeddingModel)
        embedder.embed.return_value = [0.1, 0.2, 0.3]
        store = FakeVectorStore()

        retriever = SimpleRetriever(embedding_model=embedder, vector_store=store)
        retriever.retrieve("query", top_k=3)

        assert len(store.query_calls) == 1
        assert store.query_calls[0]["embedding"] == [0.1, 0.2, 0.3]
        assert store.query_calls[0]["top_k"] == 3

    def test_retrieve_returns_scored_chunks(self):
        expected = [
            _make_scored_chunk("result 1", 0.95),
            _make_scored_chunk("result 2", 0.80),
        ]
        embedder = MagicMock(spec=EmbeddingModel)
        embedder.embed.return_value = [0.1]
        store = FakeVectorStore(results=expected)

        retriever = SimpleRetriever(embedding_model=embedder, vector_store=store)
        results = retriever.retrieve("query")

        assert len(results) == 2
        assert results[0].score == 0.95
        assert results[1].score == 0.80

    def test_retrieve_default_top_k(self):
        embedder = MagicMock(spec=EmbeddingModel)
        embedder.embed.return_value = [0.1]
        store = FakeVectorStore()

        retriever = SimpleRetriever(embedding_model=embedder, vector_store=store)
        retriever.retrieve("query")

        assert store.query_calls[0]["top_k"] == 5

    def test_retrieve_empty_results(self):
        embedder = MagicMock(spec=EmbeddingModel)
        embedder.embed.return_value = [0.1]
        store = FakeVectorStore(results=[])

        retriever = SimpleRetriever(embedding_model=embedder, vector_store=store)
        results = retriever.retrieve("query")

        assert results == []
