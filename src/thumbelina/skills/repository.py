"""Skill repository for storing and managing skills."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import Column, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from thumbelina.skills.models import Skill

Base = declarative_base()


class SkillRecord(Base):
    """SQLAlchemy model for skill storage."""

    __tablename__ = "skills"

    id = Column(String(36), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    trigger_conditions = Column(Text, nullable=False)  # JSON array
    steps = Column(Text, nullable=False)  # JSON array
    version = Column(Integer, default=1)
    success_rate = Column(Float, default=0.0)


class SkillRepository:
    """Repository for storing and managing skills.

    Parameters
    ----------
    db_url:
        Database URL. Use ":memory:" for in-memory SQLite.
    """

    def __init__(self, db_url: str = "sqlite:///thumbelina.db") -> None:
        if db_url == ":memory:" or db_url == "sqlite:///:memory:" or db_url.startswith("sqlite:///:memory:"):
            self.engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine = create_engine(db_url, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _record_to_skill(self, record: SkillRecord) -> Skill:
        """Convert a database record to a Skill object."""
        return Skill(
            id=record.id,
            name=record.name,
            description=record.description,
            trigger_conditions=json.loads(record.trigger_conditions),
            steps=json.loads(record.steps),
            version=record.version,
            success_rate=record.success_rate,
        )

    async def save(self, skill: Skill) -> None:
        """Save or update a skill."""
        def _save():
            with self.SessionLocal() as session:
                record = session.get(SkillRecord, skill.id)
                if record:
                    record.name = skill.name
                    record.description = skill.description
                    record.trigger_conditions = json.dumps(skill.trigger_conditions)
                    record.steps = json.dumps(skill.steps)
                    record.version = skill.version
                    record.success_rate = skill.success_rate
                else:
                    record = SkillRecord(
                        id=skill.id,
                        name=skill.name,
                        description=skill.description,
                        trigger_conditions=json.dumps(skill.trigger_conditions),
                        steps=json.dumps(skill.steps),
                        version=skill.version,
                        success_rate=skill.success_rate,
                    )
                    session.add(record)
                session.commit()

        await asyncio.to_thread(_save)

    async def get(self, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        def _get():
            with self.SessionLocal() as session:
                record = session.get(SkillRecord, skill_id)
                return self._record_to_skill(record) if record else None

        return await asyncio.to_thread(_get)

    async def list_all(self) -> list[Skill]:
        """List all skills."""
        def _list():
            with self.SessionLocal() as session:
                records = session.query(SkillRecord).all()
                return [self._record_to_skill(r) for r in records]

        return await asyncio.to_thread(_list)

    async def delete(self, skill_id: str) -> bool:
        """Delete a skill."""
        def _delete():
            with self.SessionLocal() as session:
                record = session.get(SkillRecord, skill_id)
                if not record:
                    return False
                session.delete(record)
                session.commit()
                return True

        return await asyncio.to_thread(_delete)

    async def search(self, query: str) -> list[Skill]:
        """Search skills by name or description."""
        def _search():
            with self.SessionLocal() as session:
                records = session.query(SkillRecord).filter(
                    SkillRecord.name.contains(query)
                    | SkillRecord.description.contains(query)
                ).all()
                return [self._record_to_skill(r) for r in records]

        return await asyncio.to_thread(_search)
