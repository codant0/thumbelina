"""Tests for RAG indexing pipeline.

注意：indexer.py 顶层 import torch，在无 GPU 环境可能崩溃，
因此在导入前先将 torch 注入 sys.modules。
"""

from __future__ import annotations

import json
import sys
import threading
import types
import uuid

import pytest

# 在导入 indexer 之前 mock torch，避免 DLL 加载崩溃
if "torch" not in sys.modules:
    sys.modules["torch"] = types.ModuleType("torch")


from thumbelina.rag.common.models import Chunk, Document, DocumentType
from thumbelina.rag.embedding.base import EmbeddingModel, ScoredChunk, VectorStore
from thumbelina.rag.ingestion.chunker import Chunker
from thumbelina.rag.ingestion.loader import Loader
from thumbelina.rag.pipeline.indexer import (
    EMBED_BATCH_SIZE,
    IndexCancelledError,
    Indexer,
    IndexStats,
    ProgressEvent,
)

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
    def __init__(self, raise_exc: bool = False, fail_after_n_adds: int | None = None):
        self.added_chunks: list[Chunk] = []
        self.added_embeddings: list[list[float]] = []
        self.deleted_ids: list[str] = []
        self._raise = raise_exc
        self._fail_after_n_adds = fail_after_n_adds
        self._add_calls = 0

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self._add_calls += 1
        if self._raise:
            raise RuntimeError("store failed")
        if self._fail_after_n_adds is not None and self._add_calls > self._fail_after_n_adds:
            raise RuntimeError("store failed")
        self.added_chunks.extend(chunks)
        self.added_embeddings.extend(embeddings)

    def query(self, embedding: list[float], top_k: int = 5) -> list[ScoredChunk]:
        return []

    def delete(self, ids: list[str]) -> None:
        self.deleted_ids.extend(ids)

    def query_by_metadata(self, where: dict[str, str], limit: int = 100) -> list[Chunk]:
        return []

    def delete_by_metadata(self, where: dict[str, str]) -> int:
        return 0


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
        sha256=b"\x00" * 32,
        sim_hash_64=b"\x00" * 8,
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


class TestDocumentDedup:
    """文档级去重命中时应记为 skipped 而非 error。"""

    def _make_indexer_with_dedup(self, action, store: FakeVectorStore) -> Indexer:
        from thumbelina.rag.ingestion.document_dedup import DedupResult

        class FixedDedup:
            def check(self, document):
                return DedupResult(action=action, message="存在相同文件 [test.md]")

        return Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker([_make_chunk()]),
            embedder=FakeEmbedding(),
            vector_store=store,
            doc_deduplicator=FixedDedup(),
        )

    @pytest.mark.parametrize(
        "action_name",
        ["EXACT_DUPLICATE", "IDENTICAL_SIMHASH"],
    )
    def test_duplicate_document_skipped_not_indexed(self, action_name):
        from thumbelina.rag.ingestion.document_dedup import DedupAction

        store = FakeVectorStore()
        indexer = self._make_indexer_with_dedup(getattr(DedupAction, action_name), store)
        stats = indexer.index("/tmp/test.md")

        assert stats.documents == []
        assert stats.skipped_count == 1
        assert stats.errors == []
        assert stats.indexed_count == 0
        assert store.added_chunks == []


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


def _make_chunks(n: int) -> list[Chunk]:
    return [_make_chunk(f"chunk {i}") for i in range(n)]


class TestProgressCallback:
    """progress_cb / cancel_event 支持。"""

    def test_progress_event_stages_and_chunk_counts(self):
        events: list[ProgressEvent] = []
        chunks = _make_chunks(70)
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(chunks),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )
        stats = indexer.index(
            "/tmp/a.md",
            progress_cb=lambda ev: events.append(ev),
        )
        assert stats.indexed_count == 70
        stages = [ev.stage for ev in events]
        assert "loading" in stages
        assert "chunking" in stages
        assert "embedding" in stages
        assert "storing" in stages
        embedding_events = [ev for ev in events if ev.stage == "embedding"]
        # 70 chunks / 每批 32 → 3 批：32, 64, 70
        assert [ev.chunk_done for ev in embedding_events] == [32, 64, 70]
        assert all(ev.chunk_total == 70 for ev in embedding_events)
        assert all(ev.filename == "test.md" for ev in embedding_events)

    def test_no_callback_behavior_unchanged(self):
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(_make_chunks(3)),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )
        stats = indexer.index("/tmp/a.md")
        assert stats.indexed_count == 3
        assert not stats.errors

    def test_cancel_event_raises(self):
        cancel = threading.Event()

        class CancellingEmbedding(FakeEmbedding):
            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                cancel.set()  # 第一批完成后取消
                return super().embed_batch(texts)

        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(_make_chunks(EMBED_BATCH_SIZE * 2)),
            embedder=CancellingEmbedding(),
            vector_store=FakeVectorStore(),
        )
        with pytest.raises(IndexCancelledError):
            indexer.index("/tmp/a.md", cancel_event=cancel)

    def test_index_batch_reports_file_progress(self):
        events: list[ProgressEvent] = []
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(_make_chunks(2)),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )
        indexer.index_batch(
            ["/tmp/a.md", "/tmp/b.md"],
            progress_cb=lambda ev: events.append(ev),
        )
        loading_events = [ev for ev in events if ev.stage == "loading"]
        assert [ev.file_index for ev in loading_events] == [0, 1]
        assert all(ev.total_files == 2 for ev in loading_events)


class TestRollbackAndCancel:
    """失败/取消时的回滚语义（单文件全有或全无）。"""

    def test_store_failure_rolls_back_previous_batches(self):
        """向量库第 2 批写入失败 → 第 1 批已写入的 chunk 被删除。"""
        chunks = _make_chunks(EMBED_BATCH_SIZE * 2)
        store = FakeVectorStore(fail_after_n_adds=1)
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(chunks),
            embedder=FakeEmbedding(),
            vector_store=store,
        )

        stats = indexer.index("/tmp/a.md")

        first_batch_ids = [c.id for c in chunks[:EMBED_BATCH_SIZE]]
        assert set(first_batch_ids) <= set(store.deleted_ids)
        # 失败批的 id 也在回滚列表中（从未写入，删除无副作用）
        assert store.deleted_ids == [c.id for c in chunks]
        assert stats.indexed_count == 0
        assert stats.errors
        assert "写入向量库失败" in stats.errors[0]

    def test_cancel_rolls_back_stored_batches(self):
        """第一批处理期间置位取消 → 抛 IndexCancelledError，已写入批次被回滚。"""
        cancel = threading.Event()

        class CancelAfterFirstBatch(FakeEmbedding):
            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                result = super().embed_batch(texts)
                cancel.set()  # 第一批完成后取消，下一批边界生效
                return result

        chunks = _make_chunks(EMBED_BATCH_SIZE * 2)
        store = FakeVectorStore()
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(chunks),
            embedder=CancelAfterFirstBatch(),
            vector_store=store,
        )

        stats = IndexStats()
        with pytest.raises(IndexCancelledError):
            indexer._embed_and_store(chunks, stats, cancel_event=cancel)

        assert store.deleted_ids == [c.id for c in chunks[:EMBED_BATCH_SIZE]]
        assert stats.indexed_count == 0

    def test_pre_cancelled_raises_before_load(self):
        """index() 前置位取消 → 加载前即抛出 IndexCancelledError。"""
        cancel = threading.Event()
        cancel.set()
        # 若 cancel 检查晚于加载，loader 会抛 FileNotFoundError
        loader = FakeLoader(documents=[_make_document()], raise_on="/tmp/a.md")
        indexer = Indexer(
            loader=loader,
            chunker=FakeChunker(),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )

        with pytest.raises(IndexCancelledError):
            indexer.index("/tmp/a.md", cancel_event=cancel)
