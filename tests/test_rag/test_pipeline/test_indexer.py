"""Tests for RAG indexing pipeline.

注意：indexer.py 顶层 import torch，在无 GPU 环境可能崩溃，
因此在导入前先将 torch 注入 sys.modules。
"""

from __future__ import annotations

import json
import sys
import types
import uuid

# 在导入 indexer 之前 mock torch，避免 DLL 加载崩溃
if "torch" not in sys.modules:
    sys.modules["torch"] = types.ModuleType("torch")


from thumbelina.rag.embedding.base import EmbeddingModel, ScoredChunk, VectorStore
from thumbelina.rag.ingestion.chunker import Chunker
from thumbelina.rag.ingestion.loader import Loader
from thumbelina.rag.knowledge_base.models import Chunk, Document, DocumentType
from thumbelina.rag.pipeline.indexer import Indexer, IndexStats

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLoader(Loader):
    def __init__(self, documents: list[Document] | None = None, raise_on: str | None = None):
        self._documents = documents or []
        self._raise_on = raise_on

    def load(self, path: str) -> list[Document]:
        if self._raise_on and path == self._raise_on:
            raise FileNotFoundError(f"not found: {path}")
        return self._documents


class FakeChunker(Chunker):
    def __init__(self, chunks: list[Chunk] | None = None, raise_exc: bool = False):
        self._chunks = chunks or []
        self._raise = raise_exc

    def chunk(self, document: Document) -> list[Chunk]:
        if self._raise:
            raise RuntimeError("chunking failed")
        return self._chunks


class FakeEmbedding(EmbeddingModel):
    def __init__(self, raise_exc: bool = False):
        self._raise = raise_exc

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._raise:
            raise RuntimeError("embedding failed")
        return [self.embed(t) for t in texts]


class FakeVectorStore(VectorStore):
    def __init__(self, raise_exc: bool = False):
        self.added_chunks: list[Chunk] = []
        self.added_embeddings: list[list[float]] = []
        self._raise = raise_exc

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if self._raise:
            raise RuntimeError("store failed")
        self.added_chunks.extend(chunks)
        self.added_embeddings.extend(embeddings)

    def query(self, embedding: list[float], top_k: int = 5) -> list[ScoredChunk]:
        return []

    def delete(self, ids: list[str]) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_document(content: str = "hello world") -> Document:
    return Document(
        id=uuid.uuid4().hex,
        name="test.md",
        source_uri="/tmp/test.md",
        document_type=DocumentType.MARKDOWN,
        content=content,
    )


def _make_chunk(content: str = "chunk text") -> Chunk:
    return Chunk(
        id=uuid.uuid4().hex,
        document_id="doc-1",
        content=content,
        metadata=json.dumps({}),
        knowledge_base_id="0",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIndexStats:
    """Tests for IndexStats dataclass."""

    def test_default_values(self):
        stats = IndexStats()
        assert stats.document_count == 0
        assert stats.chunk_count == 0
        assert stats.indexed_count == 0
        assert stats.skipped_count == 0
        assert stats.errors == []

    def test_errors_default_factory(self):
        s1 = IndexStats()
        s2 = IndexStats()
        s1.errors.append("err")
        assert s2.errors == []


class TestIndexer:
    """Tests for Indexer."""

    def test_class_exists(self):
        assert Indexer is not None

    def test_index_full_pipeline(self):
        doc = _make_document()
        chunk = _make_chunk()
        loader = FakeLoader(documents=[doc])
        chunker = FakeChunker(chunks=[chunk])
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/tmp/test.md")

        assert stats.document_count == 1
        assert stats.chunk_count == 1
        assert stats.indexed_count == 1
        assert stats.skipped_count == 0
        assert stats.errors == []
        assert len(store.added_chunks) == 1
        assert store.added_chunks[0].content == "chunk text"

    def test_index_nonexistent_file(self):
        loader = FakeLoader(documents=[], raise_on=None)
        chunker = FakeChunker()
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/nonexistent")

        assert stats.document_count == 0
        assert stats.skipped_count == 1

    def test_index_loader_exception(self):
        loader = FakeLoader(raise_on="/fail.txt")
        chunker = FakeChunker()
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/fail.txt")

        assert stats.document_count == 0
        assert len(stats.errors) == 1
        assert "加载失败" in stats.errors[0]

    def test_index_chunker_exception(self):
        doc = _make_document()
        loader = FakeLoader(documents=[doc])
        chunker = FakeChunker(raise_exc=True)
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/tmp/test.md")

        assert stats.document_count == 1
        assert len(stats.errors) == 1
        assert "分块失败" in stats.errors[0]

    def test_index_embedding_exception(self):
        doc = _make_document()
        chunk = _make_chunk()
        loader = FakeLoader(documents=[doc])
        chunker = FakeChunker(chunks=[chunk])
        embedder = FakeEmbedding(raise_exc=True)
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/tmp/test.md")

        assert stats.indexed_count == 0
        assert len(stats.errors) == 1
        assert "向量化失败" in stats.errors[0]

    def test_index_vector_store_exception(self):
        doc = _make_document()
        chunk = _make_chunk()
        loader = FakeLoader(documents=[doc])
        chunker = FakeChunker(chunks=[chunk])
        embedder = FakeEmbedding()
        store = FakeVectorStore(raise_exc=True)

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/tmp/test.md")

        assert stats.indexed_count == 0
        assert len(stats.errors) == 1
        assert "写入向量库失败" in stats.errors[0]

    def test_index_empty_chunks_skips(self):
        doc = _make_document()
        loader = FakeLoader(documents=[doc])
        chunker = FakeChunker(chunks=[])  # 分块为空
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index("/tmp/test.md")

        assert stats.document_count == 1
        assert stats.skipped_count == 1
        assert stats.indexed_count == 0


class TestIndexerBatch:
    """Tests for Indexer.index_batch."""

    def test_batch_multiple_files(self):
        doc1 = _make_document("file 1")
        chunk1 = _make_chunk("chunk 1")

        loader = FakeLoader(documents=[doc1])
        chunker = FakeChunker(chunks=[chunk1])
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index_batch(["/a.md", "/b.md"])

        assert stats.document_count == 2
        assert stats.chunk_count == 2
        assert stats.indexed_count == 2

    def test_batch_accumulates_errors(self):
        loader = FakeLoader(raise_on="/fail.txt")
        chunker = FakeChunker()
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index_batch(["/fail.txt", "/fail.txt"])

        assert len(stats.errors) == 2

    def test_batch_empty_paths(self):
        loader = FakeLoader()
        chunker = FakeChunker()
        embedder = FakeEmbedding()
        store = FakeVectorStore()

        indexer = Indexer(loader=loader, chunker=chunker, embedder=embedder, vector_store=store)
        stats = indexer.index_batch([])

        assert stats.document_count == 0
        assert stats.errors == []
