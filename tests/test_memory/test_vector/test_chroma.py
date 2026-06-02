"""Tests for ChromaDB vector store implementation."""

from __future__ import annotations

import pytest

from thumbelina.memory.vector.chroma import ChromaVectorStore


@pytest.fixture
def store():
    """Create a ChromaVectorStore with in-memory storage."""
    return ChromaVectorStore(collection_name="test_collection")


class TestChromaVectorStore:
    """Tests for ChromaVectorStore."""

    def test_store_class_exists(self):
        """ChromaVectorStore should be importable."""
        assert ChromaVectorStore is not None

    def test_store_creates_instance(self):
        """Should be able to create a ChromaVectorStore."""
        store = ChromaVectorStore(collection_name="test")
        assert store is not None

    @pytest.mark.asyncio
    async def test_add_document(self, store: ChromaVectorStore):
        """Should be able to add a document."""
        await store.add(
            doc_id="doc1",
            text="Hello world",
            metadata={"source": "test"},
        )

    @pytest.mark.asyncio
    async def test_search_returns_results(self, store: ChromaVectorStore):
        """Search should return results."""
        await store.add(doc_id="doc1", text="Hello world")
        await store.add(doc_id="doc2", text="Goodbye world")

        results = await store.search(query="hello", limit=2)

        assert len(results) > 0
        assert all("id" in r for r in results)
        assert all("text" in r for r in results)
        assert all("score" in r for r in results)

    @pytest.mark.asyncio
    async def test_search_relevance_order(self, store: ChromaVectorStore):
        """Search results should be ordered by relevance."""
        await store.add(doc_id="doc1", text="Python programming language")
        await store.add(doc_id="doc2", text="Cooking recipe for pasta")
        await store.add(doc_id="doc3", text="Python web development")

        results = await store.search(query="Python coding", limit=3)

        # Python-related docs should rank higher
        assert len(results) >= 2
        top_ids = [r["id"] for r in results[:2]]
        assert "doc1" in top_ids or "doc3" in top_ids

    @pytest.mark.asyncio
    async def test_search_with_limit(self, store: ChromaVectorStore):
        """Search should respect limit parameter."""
        for i in range(10):
            await store.add(doc_id=f"doc{i}", text=f"Document number {i}")

        results = await store.search(query="document", limit=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_delete_document(self, store: ChromaVectorStore):
        """Should be able to delete a document."""
        await store.add(doc_id="doc1", text="To be deleted")

        result = await store.delete(doc_id="doc1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: ChromaVectorStore):
        """Deleting non-existent document should return False."""
        result = await store.delete(doc_id="nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_search_after_delete(self, store: ChromaVectorStore):
        """Deleted documents should not appear in search results."""
        await store.add(doc_id="doc1", text="Hello world")
        await store.add(doc_id="doc2", text="Goodbye world")

        await store.delete(doc_id="doc1")

        results = await store.search(query="hello", limit=10)
        result_ids = [r["id"] for r in results]
        assert "doc1" not in result_ids

    @pytest.mark.asyncio
    async def test_metadata_stored(self, store: ChromaVectorStore):
        """Metadata should be stored and returned."""
        await store.add(
            doc_id="doc1",
            text="Hello",
            metadata={"source": "test", "category": "greeting"},
        )

        results = await store.search(query="hello", limit=1)
        assert results[0]["metadata"]["source"] == "test"
        assert results[0]["metadata"]["category"] == "greeting"

    @pytest.mark.asyncio
    async def test_update_document(self, store: ChromaVectorStore):
        """Adding with same ID should update the document."""
        await store.add(doc_id="doc1", text="Old text")
        await store.add(doc_id="doc1", text="New text")

        results = await store.search(query="new text", limit=1)
        assert results[0]["text"] == "New text"
