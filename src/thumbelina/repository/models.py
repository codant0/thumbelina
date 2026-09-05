"""SQLAlchemy models for the memory system."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def ensure_schema(engine: Engine) -> None:
    """Add any missing columns to existing tables.

    ``Base.metadata.create_all`` only creates tables that do not yet exist.
    When a new column is added to an ORM model after the database file was
    first created, ``create_all`` silently skips it.  This function inspects
    every table defined on ``Base.metadata`` and issues ``ALTER TABLE ADD
    COLUMN`` for each column that is present in the model but absent from the
    live schema.
    """
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)

    for table_name, table_obj in Base.metadata.tables.items():
        try:
            existing = {col["name"] for col in inspector.get_columns(table_name)}
        except Exception:
            # Table doesn't exist yet — ``create_all`` will handle it.
            continue

        for column in table_obj.columns:
            if column.name in existing:
                continue

            col_type = column.type.compile(dialect=engine.dialect)
            nullable = ""
            default = ""

            if column.server_default is not None and hasattr(column.server_default, "arg"):
                arg = column.server_default.arg
                if hasattr(arg, "text"):
                    # TextClause exposes the raw SQL via .text — use verbatim.
                    default_val = arg.text
                elif isinstance(arg, str):
                    # String literals must be quoted; bare `DEFAULT ` (e.g. for
                    # server_default="") is invalid SQL and the ALTER silently
                    # fails, leaving the column missing from the live schema.
                    default_val = f"'{arg}'"
                else:
                    default_val = str(arg)
                default = f" DEFAULT {default_val}"
                if not column.nullable:
                    nullable = " NOT NULL"
            elif column.default is not None:
                # Python-side default — derive a SQL DEFAULT so existing rows
                # get a sensible value instead of NULL.
                default_arg = column.default.arg if hasattr(column.default, "arg") else None
                if default_arg is not None and not callable(default_arg):
                    # Literal value (e.g. False, 0, "")
                    type_str = col_type.upper()
                    if "BOOL" in type_str:
                        default = f" DEFAULT {1 if default_arg else 0}"
                    elif isinstance(default_arg, str):
                        default = f" DEFAULT '{default_arg}'"
                    else:
                        default = f" DEFAULT {default_arg}"
                    nullable = " NOT NULL"
                else:
                    # Callable default — leave NULL for existing rows.
                    nullable = " NULL"
            elif not column.nullable:
                # NOT NULL with no default: provide a type-appropriate
                # fallback so existing rows don't cause the ALTER to fail.
                type_str = col_type.upper()
                if "INT" in type_str:
                    default = " DEFAULT 0"
                elif "FLOAT" in type_str or "REAL" in type_str:
                    default = " DEFAULT 0.0"
                elif "BOOL" in type_str:
                    default = " DEFAULT 0"
                else:
                    default = " DEFAULT ''"
                nullable = " NOT NULL"

            ddl = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{nullable}{default}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("Schema migration: added %s.%s", table_name, column.name)
            except Exception:
                # Column may have been added by a concurrent process.
                logger.debug(
                    "Skipped adding %s.%s (already exists?)",
                    table_name,
                    column.name,
                )


class Conversation(Base):
    """Conversation model representing a chat session.

    Attributes
    ----------
    id:
        Unique identifier for the conversation.
    name:
        Human-readable name (e.g. "微信Clawbot").
    pinned:
        Whether this conversation is pinned to the top of the list.
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
    name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        default=None,
    )
    pinned: Mapped[bool] = mapped_column(
        default=False,
    )
    endpoint_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        default=None,
        comment="ID of the configured LLM endpoint for per-conversation model selection",
    )
    model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        default=None,
        comment="Specific model name selected for this conversation (within the endpoint's models)",
    )
    knowledge_base_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        default=None,
        comment="ID of the RAG knowledge base bound to this conversation",
    )
    role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        default=None,
        comment="Agent persona role for this conversation; None uses the global default",
    )
    mode: Mapped[str] = mapped_column(
        String(20),
        default="chat",
        comment="Conversation mode: 'chat' (normal) or 'coder' (workspace-bound code agent)",
    )
    workspace: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
        comment="Absolute workspace directory path for coder conversations; NULL for chat mode",
    )
    thinking_enabled: Mapped[bool] = mapped_column(
        default=False,
        comment="Whether thinking/reasoning mode is enabled for this conversation",
    )
    thinking_effort: Mapped[str] = mapped_column(
        String(10),
        default="medium",
        comment="Thinking intensity: low, medium, or high",
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
    reasoning_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Model thinking/reasoning content captured before the final answer",
    )
    attachments: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment=(
            "JSON-encoded list of attachment refs; shape: [{id, mime, width?, height?, alt?}]"
        ),
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


class Attachment(Base):
    """附件元数据记录(设计文档 §3.2 / Task B1)。

    只存元数据,字节由上传路由写入附件根目录下的 ``relative_path``
    (如 ``2026/09/<uuid>.png``)。个人单用户免鉴权:无 user_id /
    FK 归属列,无软删(deleted_at),删除即物理删除。
    """

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    mime: Mapped[str] = mapped_column(
        String(64),
        comment="MIME type, e.g. image/png",
    )
    size: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="File size in bytes",
    )
    width: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    height: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        comment="Hex digest for dedup; NULL when not computed",
    )
    relative_path: Mapped[str] = mapped_column(
        String(500),
        comment="Path relative to the attachment root directory",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Attachment(id={self.id!r}, mime={self.mime!r})>"


class TrajectoryEvent(Base):
    """单条轨迹审计事件(设计文档 §3.1)。

    轮次概念:一条用户消息开启一个轮次(turn_id),到该次助手最终
    响应结束;同一轮次内 seq 从 0 递增保证回放顺序。
    """

    __tablename__ = "trajectory_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    turn_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
    )
    seq: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    event_type: Mapped[str] = mapped_column(
        String(20),
    )
    payload: Mapped[str] = mapped_column(
        Text,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )


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


class SystemConfig(Base):
    """SQLAlchemy model for system configuration storage.

    Stores key-value configuration pairs with category grouping.
    Sensitive fields (api_key, app_secret, etc.) are NOT stored here —
    they continue to be managed via environment variables.
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        comment="Dotted config path, e.g. 'llm.provider'",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Serialized config value",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Config category: llm, channel, auth, rate_limit, etc.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key!r}, category={self.category!r})>"
