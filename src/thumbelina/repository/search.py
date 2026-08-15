"""Search engine for conversation history."""

from __future__ import annotations

import logging
from typing import Any

from thumbelina.repository.repository import ConversationRepository
from thumbelina.repository.vector.base import VectorStore

logger = logging.getLogger(__name__)


class SearchEngine:
    """Search engine for finding messages in conversation history.

    Parameters
    ----------
    repository:
        The conversation repository to search in.
    vector_store:
        Optional vector store for semantic search. When *None*,
        only keyword search is available.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store

    async def keyword_search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search messages by keyword using database-level LIKE.

        Parameters
        ----------
        query:
            Text to search for.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            List of matching message dicts.
        """
        return await self.repository.search_messages(query, limit=limit)

    async def semantic_search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search messages by semantic similarity using vector store.

        Parameters
        ----------
        query:
            Text to search for.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            List of matching results with id, text, score, and metadata.

        Raises
        ------
        RuntimeError
            If no vector store is configured.
        """
        if not self.vector_store:
            raise RuntimeError("Vector store not configured")
        return await self.vector_store.search(query, limit=limit)

    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Combine keyword and semantic search results.

        Keyword results appear first, followed by semantic results that
        are not already present (deduplicated by ``id``).

        Parameters
        ----------
        query:
            Text to search for.
        limit:
            Maximum number of combined results.

        Returns
        -------
        list[dict[str, Any]]
            Merged list of results.
        """
        keyword_results = await self.keyword_search(query, limit=limit)
        if not self.vector_store:
            return keyword_results
        try:
            semantic_results = await self.semantic_search(query, limit=limit)
        except Exception:
            logger.warning("Semantic search failed, falling back to keyword only")
            return keyword_results
        # Merge: keyword results first, then semantic (dedup by id)
        seen: set[str | None] = {r.get("id") for r in keyword_results}
        merged = list(keyword_results)
        for r in semantic_results:
            rid = r.get("id")
            if rid not in seen:
                seen.add(rid)
                merged.append(r)
        return merged[:limit]
