"""SQLAlchemy models for the memory system."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
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
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
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


class SkillRecord(Base):
    """SQLAlchemy model for skill storage."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_conditions: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    steps: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    version: Mapped[int] = mapped_column(Integer, default=1)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SkillRecord(id={self.id!r}, name={self.name!r})>"


class CompositionRecord(Base):
    """SQLAlchemy model for skill composition storage."""

    __tablename__ = "skill_compositions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    skill_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    trigger_patterns: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<CompositionRecord(id={self.id!r}, name={self.name!r})>"


class FeedbackRecord(Base):
    """SQLAlchemy model for user feedback on messages or skills.

    Attributes
    ----------
    id:
        Unique identifier for the feedback record.
    conversation_id:
        ID of the conversation this feedback relates to.
    message_index:
        Index of the message within the conversation (0-based).
    rating:
        User rating from 1 (worst) to 5 (best).
    comment:
        Optional free-text comment from the user.
    skill_id:
        Optional skill ID if the feedback is about a specific skill.
    created_at:
        Timestamp when the feedback was created.
    """

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    message_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    skill_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<FeedbackRecord(id={self.id!r}, conversation_id={self.conversation_id!r}, "
            f"rating={self.rating!r})>"
        )
