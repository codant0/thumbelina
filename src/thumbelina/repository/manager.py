"""Repository manager for conversation and message management."""

from __future__ import annotations

from typing import Any

from thumbelina.repository.repository import ConversationRepository
from thumbelina.repository.search import SearchEngine
from thumbelina.repository.vector.base import VectorStore

# Maximum content length for messages (100KB)
MAX_CONTENT_LENGTH = 100_000


class RepositoryManager:
    """High-level manager for conversation storage.

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
        self.conversation_repository = ConversationRepository(db_url)
        self._vector_store = vector_store
        self._search_engine = SearchEngine(self.conversation_repository, vector_store)

    def close(self) -> None:
        """Close the repository and release resources."""
        self.conversation_repository.close()

    async def create_conversation(self, name: str | None = None, pinned: bool = False) -> str:
        """Create a new conversation.

        Parameters
        ----------
        name:
            Optional human-readable name for the conversation.
        pinned:
            Whether to pin the conversation to the top of the list.

        Returns
        -------
        str
            The ID of the newly created conversation.
        """
        return await self.conversation_repository.create_conversation(name=name, pinned=pinned)

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        reasoning_content: str | None = None,
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
        reasoning_content:
            Optional captured thinking/reasoning text for assistant messages.

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

        await self.conversation_repository.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            reasoning_content=reasoning_content,
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
        return await self.conversation_repository.get_messages(conversation_id)

    async def get_conversations(self) -> list[dict[str, Any]]:
        """Get all conversations.

        Returns
        -------
        list[dict[str, Any]]
            List of conversation dictionaries.
        """
        return await self.conversation_repository.get_conversations()

    async def get_all_conversations_with_messages(self) -> list[dict[str, Any]]:
        """Get all conversations with their messages."""
        return await self.conversation_repository.get_all_conversations_with_messages()

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
        return await self.conversation_repository.get_conversation(conversation_id)

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
        return await self.conversation_repository.delete_conversation(conversation_id)

    async def clear_messages(self, conversation_id: str) -> bool:
        """Clear all messages of a conversation while keeping the conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation whose messages should be cleared.

        Returns
        -------
        bool
            True if messages were cleared, False if the conversation was not found.
        """
        return await self.conversation_repository.clear_messages(conversation_id)

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
        return await self.conversation_repository.set_summary(conversation_id, summary)

    async def rename_conversation(self, conversation_id: str, name: str) -> bool:
        """Update the human-readable name of a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to rename.
        name:
            New name. Pass an empty string to clear the name.

        Returns
        -------
        bool
            True if renamed successfully, False if conversation not found.
        """
        return await self.conversation_repository.rename_conversation(conversation_id, name)

    async def set_conversation_endpoint(
        self, conversation_id: str, endpoint_id: str | None
    ) -> bool:
        """Associate a conversation with a configured LLM endpoint.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        endpoint_id:
            ID of the configured endpoint, or None to revert to the default.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await self.conversation_repository.set_conversation_endpoint(
            conversation_id, endpoint_id
        )

    async def set_conversation_model(self, conversation_id: str, model: str | None) -> bool:
        """Set the specific model used for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        model:
            Model name within the conversation's endpoint, or None to use the
            endpoint's active/default model.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await self.conversation_repository.set_conversation_model(conversation_id, model)

    async def set_conversation_knowledge_base(
        self, conversation_id: str, knowledge_base_id: str | None
    ) -> bool:
        """Bind (or unbind) a RAG knowledge base to a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        knowledge_base_id:
            ID of the knowledge base, or None to unbind.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await self.conversation_repository.set_conversation_knowledge_base(
            conversation_id, knowledge_base_id
        )

    async def set_conversation_role(self, conversation_id: str, role: str | None) -> bool:
        """Set the agent persona role for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        role:
            Role name matching a ``prompts/roles/<role>.md`` file, or None
            to revert to the global default role.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await self.conversation_repository.set_conversation_role(conversation_id, role)

    async def set_conversation_thinking(
        self, conversation_id: str, enabled: bool, effort: str
    ) -> bool:
        """Set thinking-mode settings for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to update.
        enabled:
            Whether thinking mode is enabled.
        effort:
            Thinking intensity: ``low``, ``medium``, or ``high``.

        Returns
        -------
        bool
            True if set successfully, False if conversation not found.
        """
        return await self.conversation_repository.set_conversation_thinking(
            conversation_id, enabled, effort
        )

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
