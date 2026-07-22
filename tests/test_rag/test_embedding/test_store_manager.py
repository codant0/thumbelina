"""Tests for ChromaStoreManager."""

from __future__ import annotations

import chromadb
import pytest

from thumbelina.rag.embedding.store_manager import ChromaStoreManager
from thumbelina.rag.embedding.vector_chroma import ChromaVectorStore


class TestChromaStoreManager:
    @pytest.fixture
    def manager(self):
        client = chromadb.EphemeralClient()
        return ChromaStoreManager(client)

    def test_get_or_create_store(self, manager):
        store = manager.get_or_create_store("0")
        assert isinstance(store, ChromaVectorStore)

    def test_get_same_store_returns_same(self, manager):
        store1 = manager.get_or_create_store("0")
        store2 = manager.get_or_create_store("0")
        assert store1.collection.name == store2.collection.name

    def test_different_kb_different_collection(self, manager):
        store0 = manager.get_or_create_store("0")
        store1 = manager.get_or_create_store("kb-1")
        assert store0.collection.name != store1.collection.name

    def test_collection_naming(self, manager):
        store = manager.get_or_create_store("kb-42")
        assert store.collection.name == "rag_kb_kb-42"

    def test_delete_store(self, manager):
        manager.get_or_create_store("kb-1")
        manager.delete_store("kb-1")
        store = manager.get_or_create_store("kb-1")
        assert store is not None

    def test_list_stores(self, manager):
        manager.get_or_create_store("0")
        manager.get_or_create_store("kb-1")
        names = manager.list_stores()
        assert "rag_kb_0" in names
        assert "rag_kb_kb-1" in names
