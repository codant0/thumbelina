"""SQLAlchemy models for the memory system."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Conversation(Base):
    """Conversation model representing a chat session.

    Attributes
    ----------
    id:
        Unique identifier for the conversation.
    created_at:
        Timestamp when the conversation was created.
    updated_at:
        Timestamp when the conversation was last updated.
    messages:
        List of messages in this conversation.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationship to messages
    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id!r})>"


class Message(Base):
    """Message model representing a single message in a conversation.

    Attributes
    ----------
    id:
        Unique identifier for the message.
    conversation_id:
        Foreign key to the conversation this message belongs to.
    role:
        Role of the message sender (user, assistant, system).
    content:
        Content of the message.
    created_at:
        Timestamp when the message was created.
    conversation:
        The conversation this message belongs to.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    role: Mapped[str] = mapped_column(
        String(20),
    )
    content: Mapped[str] = mapped_column(
        Text,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    # Relationship to conversation
    conversation: Mapped[Conversation] = relationship(
        "Conversation",
        back_populates="messages",
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id!r}, role={self.role!r})>"
