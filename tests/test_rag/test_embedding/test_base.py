"""Tests for RAG embedding model interfaces and ScoredChunk."""

from __future__ import annotations

import uuid

import pytest

from thumbelina.rag.embedding.base import EmbeddingModel, ScoredChunk, VectorStore
from thumbelina.rag.knowledge_base.models import Chunk


class TestScoredChunk:
    """Tests for ScoredChunk model."""

    def _make_scored_chunk(self, **kwargs):
        defaults = {
            "id": uuid.uuid4().hex,
            "document_id": "doc-1",
            "content": "test content",
            "metadata": '{"source": "test.md"}',
            "knowledge_base_id": "0",
            "score": 0.85,
        }
        defaults.update(kwargs)
        return ScoredChunk(**defaults)

    def test_create_scored_chunk(self):
        sc = self._make_scored_chunk()
        assert sc.content == "test content"
        assert sc.score == 0.85

    def test_default_score(self):
        sc = ScoredChunk(
            id="1",
            document_id="d1",
            content="text",
            metadata="{}",
            knowledge_base_id="0",
        )
        assert sc.score == 0.0

    def test_inherits_chunk_fields(self):
        sc = self._make_scored_chunk()
        assert hasattr(sc, "id")
        assert hasattr(sc, "document_id")
        assert hasattr(sc, "content")
        assert hasattr(sc, "metadata")
        assert hasattr(sc, "knowledge_base_id")

    def test_isinstance_chunk(self):
        sc = self._make_scored_chunk()
        assert isinstance(sc, Chunk)

    def test_score_can_be_zero(self):
        sc = self._make_scored_chunk(score=0.0)
        assert sc.score == 0.0

    def test_score_can_be_negative(self):
        # 距离度量可能导致负分数
        sc = self._make_scored_chunk(score=-0.5)
        assert sc.score == -0.5


class TestEmbeddingModelABC:
    """Tests for EmbeddingModel abstract interface."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            EmbeddingModel()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        class DummyEmbedding(EmbeddingModel):
            def embed(self, text: str) -> list[float]:
                return [0.1, 0.2, 0.3]

            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [self.embed(t) for t in texts]

        model = DummyEmbedding()
        assert model.embed("hello") == [0.1, 0.2, 0.3]
        assert model.embed_batch(["a", "b"]) == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]


class TestVectorStoreABC:
    """Tests for VectorStore abstract interface (rag.embedding.base)."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            VectorStore()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        class InMemoryVectorStore(VectorStore):
            def __init__(self):
                self._data: dict[str, tuple[Chunk, list[float]]] = {}

            def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
                for chunk, emb in zip(chunks, embeddings):
                    self._data[chunk.id] = (chunk, emb)

            def query(self, embedding: list[float], top_k: int = 5) -> list[ScoredChunk]:
                results = []
                for chunk, emb in self._data.values():
                    results.append(
                        ScoredChunk(
                            id=chunk.id,
                            document_id=chunk.document_id,
                            content=chunk.content,
                            metadata=chunk.metadata,
                            knowledge_base_id=chunk.knowledge_base_id,
                            score=0.9,
                        )
                    )
                return results[:top_k]

            def delete(self, ids: list[str]) -> None:
                for doc_id in ids:
                    self._data.pop(doc_id, None)

        store = InMemoryVectorStore()
        assert store is not None
        assert store.query([0.1], top_k=5) == []
