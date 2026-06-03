"""Tests for vector store base class."""

from __future__ import annotations

import pytest

from thumbelina.memory.vector.base import VectorStore


class TestVectorStore:
    """Tests for the VectorStore abstract base class."""

    def test_vector_store_is_abstract(self):
        """VectorStore should not be instantiable directly."""
        with pytest.raises(TypeError):
            VectorStore()  # type: ignore[abstract]

    def test_vector_store_has_add_method(self):
        """VectorStore should define an add method."""
        assert hasattr(VectorStore, "add")

    def test_vector_store_has_search_method(self):
        """VectorStore should define a search method."""
        assert hasattr(VectorStore, "search")

    def test_vector_store_has_delete_method(self):
        """VectorStore should define a delete method."""
        assert hasattr(VectorStore, "delete")
