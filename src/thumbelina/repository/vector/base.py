"""Abstract base class for vector stores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """Abstract interface for vector storage and semantic search."""

    @abstractmethod
    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or update a document in the vector store.

        Parameters
        ----------
        doc_id:
            Unique identifier for the document.
        text:
            Text content to embed and store.
        metadata:
            Optional metadata to store with the document.
        """

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for documents similar to the query.

        Parameters
        ----------
        query:
            Text to search for.
        limit:
            Maximum number of results to return.

        Returns
        -------
        list[dict[str, Any]]
            List of results with 'id', 'text', 'score', and 'metadata' keys.
        """

    @abstractmethod
    async def delete(self, doc_id: str) -> bool:
        """Delete a document from the vector store.

        Parameters
        ----------
        doc_id:
            ID of the document to delete.

        Returns
        -------
        bool
            True if deleted, False if not found.
        """
