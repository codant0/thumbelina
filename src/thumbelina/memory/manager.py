"""Memory manager for conversation and message management."""

from __future__ import annotations

from typing import Any

from thumbelina.memory.repository import ConversationRepository
from thumbelina.memory.search import SearchEngine
from thumbelina.memory.vector.base import VectorStore

# Maximum content length for messages (100KB)
MAX_CONTENT_LENGTH = 100_000


class MemoryManager:
    """High-level manager for conversation memory.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL (e.g., "sqlite:///thumbelina.db").
    vector_store:
        Optional vector store for semantic search capabilities.
    """

    def __init__(
        self,
        db_url: str,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.repository = ConversationRepository(db_url)
        self._vector_store = vector_store
        self._search_engine = SearchEngine(self.repository, vector_store)

    def close(self) -> None:
        """Close the repository and release resources."""
        self.repository.close()

    async def create_conversation(self) -> str:
        """Create a new conversation.

        Returns
        -------
        str
            The ID of the newly created conversation.
        """
        return await self.repository.create_conversation()

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """Add a message to a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to add the message to.
        role:
            Role of the message sender (user, assistant, system).
        content:
            Content of the message.

        Raises
        ------
        ValueError
            If the conversation does not exist, role is invalid,
            or content exceeds maximum length.
        """
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length ({len(content)}) exceeds maximum ({MAX_CONTENT_LENGTH})"
            )

        await self.repository.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """Get all messages in a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to get messages from.

        Returns
        -------
        list[dict[str, Any]]
            List of message dictionaries.

        Raises
        ------
        ValueError
            If the conversation does not exist.
        """
        return await self.repository.get_messages(conversation_id)

    async def get_conversations(self) -> list[dict[str, Any]]:
        """Get all conversations.

        Returns
        -------
        list[dict[str, Any]]
            List of conversation dictionaries.
        """
        return await self.repository.get_conversations()

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Get a single conversation by ID.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to get.

        Returns
        -------
        dict[str, Any] | None
            Conversation dictionary, or None if not found.
        """
        return await self.repository.get_conversation(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to delete.

        Returns
        -------
        bool
            True if the conversation was deleted, False if not found.
        """
        return await self.repository.delete_conversation(conversation_id)

    async def set_summary(self, conversation_id: str, summary: str) -> bool:
        """Set the summary for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to set summary for.
        summary:
            Summary text.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await self.repository.set_summary(conversation_id, summary)

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search messages using hybrid keyword + semantic search.

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
        return await self._search_engine.hybrid_search(query, limit=limit)
