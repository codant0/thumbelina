"""Repository for conversation and message data access."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from thumbelina.memory.models import Conversation, Message

# Valid roles for messages
VALID_ROLES = {"user", "assistant", "system"}


class ConversationRepository:
    """Repository for managing conversations and messages.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL (e.g., "sqlite:///thumbelina.db").
    """

    def __init__(self, db_url: str) -> None:
        from thumbelina.memory.db import create_db_engine, init_db

        self.engine = create_db_engine(db_url)
        self.SessionLocal = init_db(self.engine)

    def _get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

    def _ping_sync(self) -> bool:
        """Synchronous implementation of ping."""
        with self._get_session() as session:
            session.execute(text("SELECT 1"))
            return True

    async def ping(self) -> bool:
        """Check if database connection is alive.

        Returns
        -------
        bool
            True if connection is alive.
        """
        return await asyncio.to_thread(self._ping_sync)

    def _create_conversation_sync(self, name: str | None = None, pinned: bool = False) -> str:
        """Synchronous implementation of create_conversation."""
        with self._get_session() as session:
            conversation = Conversation(name=name, pinned=pinned)
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation.id

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
        return await asyncio.to_thread(self._create_conversation_sync, name, pinned)

    def _add_message_sync(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """Synchronous implementation of add_message."""
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {role!r}. Must be one of: {VALID_ROLES}")

        with self._get_session() as session:
            # Verify conversation exists
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
            )
            session.add(message)
            session.commit()

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
            If the conversation does not exist or role is invalid.
        """
        return await asyncio.to_thread(self._add_message_sync, conversation_id, role, content)

    def _get_messages_sync(self, conversation_id: str) -> list[dict[str, Any]]:
        """Synchronous implementation of get_messages."""
        with self._get_session() as session:
            # Verify conversation exists
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

            # Get messages ordered by creation time
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            result = session.execute(stmt)
            messages = result.scalars().all()

            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]

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
        return await asyncio.to_thread(self._get_messages_sync, conversation_id)

    def _get_conversations_sync(self) -> list[dict[str, Any]]:
        """Synchronous implementation of get_conversations."""
        with self._get_session() as session:
            stmt = select(Conversation).order_by(
                Conversation.pinned.desc(),
                Conversation.updated_at.desc(),
            )
            result = session.execute(stmt)
            conversations = result.scalars().all()

            return [
                {
                    "id": conv.id,
                    "name": conv.name,
                    "pinned": conv.pinned or False,
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "summary": conv.summary,
                }
                for conv in conversations
            ]

    async def get_conversations(self) -> list[dict[str, Any]]:
        """Get all conversations.

        Returns
        -------
        list[dict[str, Any]]
            List of conversation dictionaries.
        """
        return await asyncio.to_thread(self._get_conversations_sync)

    def _get_all_conversations_with_messages_sync(self) -> list[dict[str, Any]]:
        """Synchronous implementation of get_all_conversations_with_messages."""
        with self._get_session() as session:
            stmt = (
                select(Conversation)
                .options(joinedload(Conversation.messages))
                .order_by(Conversation.created_at.desc())
            )
            result = session.execute(stmt)
            conversations = result.unique().scalars().all()

            return [
                {
                    "id": conv.id,
                    "name": conv.name,
                    "pinned": conv.pinned or False,
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "summary": conv.summary,
                    "messages": [
                        {
                            "id": msg.id,
                            "conversation_id": msg.conversation_id,
                            "role": msg.role,
                            "content": msg.content,
                            "created_at": msg.created_at.isoformat(),
                        }
                        for msg in conv.messages
                    ],
                }
                for conv in conversations
            ]

    async def get_all_conversations_with_messages(self) -> list[dict[str, Any]]:
        """Get all conversations with their messages in a single query."""
        return await asyncio.to_thread(self._get_all_conversations_with_messages_sync)

    def _get_conversation_sync(self, conversation_id: str) -> dict[str, Any] | None:
        """Synchronous implementation of get_conversation."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)

            if conversation is None:
                return None

            return {
                "id": conversation.id,
                "name": conversation.name,
                "pinned": conversation.pinned or False,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "summary": conversation.summary,
            }

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
        return await asyncio.to_thread(self._get_conversation_sync, conversation_id)

    def _delete_conversation_sync(self, conversation_id: str) -> bool:
        """Synchronous implementation of delete_conversation."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)

            if conversation is None:
                return False

            session.delete(conversation)
            session.commit()
            return True

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
        return await asyncio.to_thread(self._delete_conversation_sync, conversation_id)

    def _set_summary_sync(self, conversation_id: str, summary: str) -> bool:
        """Synchronous implementation of set_summary."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            conversation.summary = summary
            session.commit()
            return True

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
        return await asyncio.to_thread(self._set_summary_sync, conversation_id, summary)

    def _search_messages_sync(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Synchronous implementation of search_messages."""
        with self._get_session() as session:
            # 使用参数化查询防止 SQL 注入，转义 LIKE 通配符
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search_pattern = f"%{escaped}%"
            stmt = (
                select(Message)
                .where(Message.content.like(search_pattern, escape="\\"))
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            result = session.execute(stmt)
            messages = result.scalars().all()

            return [
                {
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]

    async def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search messages by keyword using SQL LIKE.

        Parameters
        ----------
        query:
            Text to search for in message content.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            List of matching message dicts.
        """
        return await asyncio.to_thread(self._search_messages_sync, query, limit)
