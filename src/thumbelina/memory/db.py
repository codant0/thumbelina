"""Shared database engine and session factory creation."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from thumbelina.memory.models import Base, ensure_schema


def create_db_engine(db_url: str) -> Engine:
    """Create a SQLAlchemy engine with appropriate pool settings.

    For SQLite in-memory databases, uses StaticPool to allow cross-thread access.
    For all other databases, uses pool_pre_ping for connection health checks.
    """
    if (
        db_url == ":memory:"
        or db_url == "sqlite:///:memory:"
        or db_url.startswith("sqlite:///:memory:")
    ):
        return create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(db_url, pool_pre_ping=True)


def init_db(engine: Engine) -> sessionmaker[Session]:
    """Create all tables, run schema migrations, and return a session factory."""
    Base.metadata.create_all(engine)
    ensure_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
