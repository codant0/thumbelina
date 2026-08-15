"""Tests for thumbelina.repository.models module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.repository.models import Base, Conversation, Message


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


class TestConversationModel:
    """Tests for the Conversation SQLAlchemy model."""

    def test_conversation_table_exists(self):
        """Conversation table should be defined."""
        assert Conversation.__tablename__ == "conversations"

    def test_conversation_has_id_column(self):
        """Conversation should have an id column."""
        assert hasattr(Conversation, "id")

    def test_conversation_has_created_at(self):
        """Conversation should have a created_at column."""
        assert hasattr(Conversation, "created_at")

    def test_conversation_has_updated_at(self):
        """Conversation should have an updated_at column."""
        assert hasattr(Conversation, "updated_at")

    def test_conversation_create(self, db_session: Session):
        """Should be able to create a conversation."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        assert conversation.id is not None
        assert isinstance(conversation.created_at, datetime)
        assert isinstance(conversation.updated_at, datetime)

    def test_conversation_default_timestamps(self, db_session: Session):
        """Conversation should have auto-generated timestamps."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        assert conversation.created_at is not None
        assert conversation.updated_at is not None

    def test_conversation_updated_at_changes(self, db_session: Session):
        """Conversation updated_at should change on update."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        original_updated = conversation.updated_at
        conversation.updated_at = datetime.now(UTC)
        db_session.commit()

        assert conversation.updated_at != original_updated


class TestMessageModel:
    """Tests for the Message SQLAlchemy model."""

    def test_message_table_exists(self):
        """Message table should be defined."""
        assert Message.__tablename__ == "messages"

    def test_message_has_id_column(self):
        """Message should have an id column."""
        assert hasattr(Message, "id")

    def test_message_has_conversation_id(self):
        """Message should have a conversation_id column."""
        assert hasattr(Message, "conversation_id")

    def test_message_has_role(self):
        """Message should have a role column."""
        assert hasattr(Message, "role")

    def test_message_has_content(self):
        """Message should have a content column."""
        assert hasattr(Message, "content")

    def test_message_has_created_at(self):
        """Message should have a created_at column."""
        assert hasattr(Message, "created_at")

    def test_message_create(self, db_session: Session):
        """Should be able to create a message."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="Hello, world!",
        )
        db_session.add(message)
        db_session.commit()

        assert message.id is not None
        assert message.conversation_id == conversation.id
        assert message.role == "user"
        assert message.content == "Hello, world!"
        assert isinstance(message.created_at, datetime)

    def test_message_roles(self, db_session: Session):
        """Message should support user, assistant, and system roles."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        for role in ["user", "assistant", "system"]:
            message = Message(
                conversation_id=conversation.id,
                role=role,
                content=f"Test {role} message",
            )
            db_session.add(message)

        db_session.commit()

        messages = db_session.query(Message).all()
        assert len(messages) == 3
        roles = {m.role for m in messages}
        assert roles == {"user", "assistant", "system"}

    def test_message_belongs_to_conversation(self, db_session: Session):
        """Message should be associated with a conversation."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="Test message",
        )
        db_session.add(message)
        db_session.commit()

        assert message.conversation == conversation
        assert message in conversation.messages


class TestModelRelationships:
    """Tests for model relationships."""

    def test_conversation_has_messages_relationship(self, db_session: Session):
        """Conversation should have a messages relationship."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        message1 = Message(
            conversation_id=conversation.id,
            role="user",
            content="First message",
        )
        message2 = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="Second message",
        )
        db_session.add_all([message1, message2])
        db_session.commit()

        assert len(conversation.messages) == 2
        assert message1 in conversation.messages
        assert message2 in conversation.messages

    def test_cascade_delete_messages(self, db_session: Session):
        """Deleting a conversation should cascade delete its messages."""
        conversation = Conversation()
        db_session.add(conversation)
        db_session.commit()

        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="Test message",
        )
        db_session.add(message)
        db_session.commit()

        db_session.delete(conversation)
        db_session.commit()

        messages = db_session.query(Message).all()
        assert len(messages) == 0
