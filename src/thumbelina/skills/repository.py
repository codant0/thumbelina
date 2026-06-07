"""Skill repository for storing and managing skills."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from sqlalchemy import select

from thumbelina.memory.models import Base, SkillRecord
from thumbelina.skills.models import Skill


class SkillRepository:
    """Repository for storing and managing skills.

    Parameters
    ----------
    db_url:
        Database URL. Use ":memory:" for in-memory SQLite.
    """

    def __init__(self, db_url: str = "sqlite:///thumbelina.db") -> None:
        from thumbelina.memory.db import create_db_engine, init_db

        self.engine = create_db_engine(db_url)
        self.SessionLocal = init_db(self.engine)

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

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
            created_at=record.created_at if record.created_at else datetime.now(),
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
                stmt = select(SkillRecord)
                records = session.execute(stmt).scalars().all()
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
                stmt = select(SkillRecord).where(
                    SkillRecord.name.contains(query) | SkillRecord.description.contains(query)
                )
                records = session.execute(stmt).scalars().all()
                return [self._record_to_skill(r) for r in records]

        return await asyncio.to_thread(_search)
