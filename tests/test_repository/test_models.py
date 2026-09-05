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


class TestEnsureSchemaStringDefault:
    """ensure_schema 对带字符串 server_default 的缺失列必须生成合法 ALTER。

    回归（PR #21）：`server_default=""` 曾被渲染成裸 `DEFAULT `（非法 SQL），
    ALTER 失败被静默吞掉，遗留库上该列永远缺失（如 scheduled_tasks.content），
    导致写入整表失败。"""

    def test_adds_missing_string_default_column(self):
        from sqlalchemy import text

        import thumbelina.scheduler.store  # noqa: F401 - 在 Base 上注册 scheduled_tasks ORM
        from thumbelina.repository.models import ensure_schema

        engine = create_engine("sqlite:///:memory:")
        # 模拟遗留库：表已存在但缺 content 列（无该列时模型写入必然失败）。
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE scheduled_tasks ("
                    "id VARCHAR(36) PRIMARY KEY, description TEXT NOT NULL)"
                )
            )
            conn.execute(
                text("INSERT INTO scheduled_tasks (id, description) VALUES ('legacy', '老数据')")
            )

        ensure_schema(engine)

        with engine.begin() as conn:
            # 列已补齐，旧行拿到默认值，模型可正常读写。
            conn.execute(
                text(
                    "INSERT INTO scheduled_tasks (id, description, content) "
                    "VALUES ('new', '新数据', 'hello')"
                )
            )
            row = conn.execute(
                text("SELECT description, content FROM scheduled_tasks WHERE id='legacy'")
            ).fetchone()
            assert row.description == "老数据"
            assert row.content == ""


class TestEnsureSchemaMessagesAttachments:
    """ensure_schema 必须为遗留库补齐多模态增量(设计 §3.2)。

    回归:多模态分支在 messages 上新增 JSON 列 ``attachments``、并新增
    ``attachments`` 表。``Base.metadata.create_all`` 只建缺失的表、不补
    已有表的缺失列 —— 遗留库升级必须靠 ensure_schema 补列,否则带附件的
    user 消息写入整行失败。
    """

    def test_adds_attachments_column_and_attachments_table(self):
        from sqlalchemy import inspect as sa_inspect, text

        from thumbelina.repository.models import Attachment, ensure_schema

        engine = create_engine("sqlite:///:memory:")
        # 模拟多模态之前的遗留库:messages 表存在但没有 attachments 列
        # (reasoning_content 属于更早的迁移,已在),attachments 表不存在。
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE messages ("
                    "id VARCHAR(36) PRIMARY KEY, "
                    "conversation_id VARCHAR(36), "
                    "role VARCHAR(20), "
                    "content TEXT NOT NULL, "
                    "reasoning_content TEXT, "
                    "created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content) "
                    "VALUES ('legacy', 'conv', 'user', '老消息')"
                )
            )

        # create_all 补建缺失的表(attachments 等);ensure_schema 补齐已有表的缺失列。
        Base.metadata.create_all(engine)
        ensure_schema(engine)

        inspector = sa_inspect(engine)
        column_names = {col["name"] for col in inspector.get_columns("messages")}
        assert "attachments" in column_names
        assert inspector.has_table("attachments")

        # 补列后模型可正常写入:附件记录 + 带附件引用的 user 消息。
        with Session(engine) as session:
            session.add(
                Attachment(id="att-1", mime="image/png", size=1, relative_path="2026/09/a.png")
            )
            session.add(
                Message(
                    id="msg-1",
                    conversation_id="conv",
                    role="user",
                    content="新消息",
                    attachments='[{"id": "att-1", "mime": "image/png"}]',
                )
            )
            session.commit()

            row = session.execute(
                text("SELECT content, attachments FROM messages WHERE id='legacy'")
            ).fetchone()
            assert row.content == "老消息"
            assert row.attachments is None
            new_row = session.execute(
                text("SELECT attachments FROM messages WHERE id='msg-1'")
            ).fetchone()
            assert new_row.attachments == '[{"id": "att-1", "mime": "image/png"}]'
