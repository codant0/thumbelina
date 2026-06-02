"""Search engine for conversation history."""

from __future__ import annotations

import logging
from typing import Any

from thumbelina.memory.repository import ConversationRepository

logger = logging.getLogger(__name__)


class SearchEngine:
    """Search engine for finding messages in conversation history.

    Parameters
    ----------
    repository:
        The conversation repository to search in.
    """

    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

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
