"""RAG 模块独立的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class RagBase(DeclarativeBase):
    """RAG 模块专用的 Base，独立于 memory 模块。"""

    pass


class KnowledgeBaseRecord(RagBase):
    """知识库表。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBaseRecord(id={self.id!r}, name={self.name!r})>"


class DocumentRecord(RagBase):
    """文档元数据表。"""

    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # SQLAlchemy 2.0 ``mapped_column(default=…)`` only provides an INSERT-time
    # default.  Override ``__init__`` so that ``chunk_count`` defaults to ``0``
    # at Python object construction time as well.
    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("chunk_count", 0)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<DocumentRecord(id={self.id!r}, name={self.name!r})>"
