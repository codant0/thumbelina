"""ChromaDB vector store implementation."""

from __future__ import annotations

import asyncio
from typing import Any

import chromadb

from thumbelina.repository.vector.base import VectorStore


class ChromaVectorStore(VectorStore):
    """Vector store backed by ChromaDB.

    Parameters
    ----------
    collection_name:
        Name of the ChromaDB collection.
    persist_directory:
        Directory to persist data. None for in-memory.
    """

    def __init__(
        self,
        collection_name: str = "thumbelina",
        persist_directory: str | None = None,
    ) -> None:
        if persist_directory:
            self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
        )

    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or update a document."""
        kwargs: dict[str, Any] = {
            "ids": [doc_id],
            "documents": [text],
        }
        if metadata:
            kwargs["metadatas"] = [metadata]
        await asyncio.to_thread(self._collection.upsert, **kwargs)

    async def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for similar documents."""
        total = self._collection.count()
        limit = min(limit, total) if total > 0 else 0
        if limit == 0:
            return []

        result = await asyncio.to_thread(
            self._collection.query,
            query_texts=[query],
            n_results=limit,
        )

        results = []
        ids = result.get("ids")
        documents = result.get("documents")
        distances = result.get("distances")
        metadatas = result.get("metadatas")
        if not ids or not documents:
            return []

        for i, doc_id in enumerate(ids[0]):
            results.append(
                {
                    "id": doc_id,
                    "text": documents[0][i],
                    "score": distances[0][i] if distances else 0.0,
                    "metadata": metadatas[0][i] if metadatas else {},
                }
            )
        return results

    async def delete(self, doc_id: str) -> bool:
        """Delete a document."""
        try:
            existing = await asyncio.to_thread(
                self._collection.get,
                ids=[doc_id],
            )
            if not existing["ids"]:
                return False

            await asyncio.to_thread(
                self._collection.delete,
                ids=[doc_id],
            )
            return True
        except Exception:
            return False
