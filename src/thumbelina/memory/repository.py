"""Repository for conversation and message data access."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from thumbelina.memory.models import Base, Conversation, Message

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
        # For SQLite in-memory databases, use StaticPool to share the connection
        # and allow cross-thread access
        if db_url == "sqlite:///:memory:" or db_url.startswith("sqlite:///:memory:"):
            self.engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine = create_engine(db_url, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

    def _create_conversation_sync(self) -> str:
        """Synchronous implementation of create_conversation."""
        with self._get_session() as session:
            conversation = Conversation()
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation.id

    async def create_conversation(self) -> str:
        """Create a new conversation.

        Returns
        -------
        str
            The ID of the newly created conversation.
        """
        return await asyncio.to_thread(self._create_conversation_sync)

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
        return await asyncio.to_thread(
            self._add_message_sync, conversation_id, role, content
        )

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
            stmt = select(Conversation).order_by(Conversation.created_at.desc())
            result = session.execute(stmt)
            conversations = result.scalars().all()

            return [
                {
                    "id": conv.id,
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
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

    def _get_conversation_sync(self, conversation_id: str) -> dict[str, Any] | None:
        """Synchronous implementation of get_conversation."""
        with self._get_session() as session:
            conversation = session.get(Conversation, conversation_id)

            if conversation is None:
                return None

            return {
                "id": conversation.id,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
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
