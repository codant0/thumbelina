"""Composition repository for storing and managing skill compositions."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from thumbelina.memory.models import Base, CompositionRecord
from thumbelina.skills.composition import SkillComposition


class CompositionRepository:
    """Repository for storing and managing skill compositions.

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

    def _record_to_composition(self, record: CompositionRecord) -> SkillComposition:
        """Convert a database record to a SkillComposition object."""
        return SkillComposition(
            id=record.id,
            name=record.name,
            description=record.description,
            skill_ids=json.loads(record.skill_ids),
            trigger_patterns=json.loads(record.trigger_patterns),
            usage_count=record.usage_count,
        )

    async def save(self, composition: SkillComposition) -> None:
        """Save or update a composition."""

        def _save() -> None:
            with self.SessionLocal() as session:
                record = session.get(CompositionRecord, composition.id)
                if record:
                    record.name = composition.name
                    record.description = composition.description
                    record.skill_ids = json.dumps(composition.skill_ids)
                    record.trigger_patterns = json.dumps(composition.trigger_patterns)
                    record.usage_count = composition.usage_count
                else:
                    record = CompositionRecord(
                        id=composition.id,
                        name=composition.name,
                        description=composition.description,
                        skill_ids=json.dumps(composition.skill_ids),
                        trigger_patterns=json.dumps(composition.trigger_patterns),
                        usage_count=composition.usage_count,
                    )
                    session.add(record)
                session.commit()

        await asyncio.to_thread(_save)

    async def get(self, composition_id: str) -> SkillComposition | None:
        """Get a composition by ID."""

        def _get() -> SkillComposition | None:
            with self.SessionLocal() as session:
                record = session.get(CompositionRecord, composition_id)
                return self._record_to_composition(record) if record else None

        return await asyncio.to_thread(_get)

    async def list_all(self) -> list[SkillComposition]:
        """List all compositions."""

        def _list() -> list[SkillComposition]:
            with self.SessionLocal() as session:
                stmt = select(CompositionRecord)
                records = session.execute(stmt).scalars().all()
                return [self._record_to_composition(r) for r in records]

        return await asyncio.to_thread(_list)

    async def delete(self, composition_id: str) -> bool:
        """Delete a composition."""

        def _delete() -> bool:
            with self.SessionLocal() as session:
                record = session.get(CompositionRecord, composition_id)
                if not record:
                    return False
                session.delete(record)
                session.commit()
                return True

        return await asyncio.to_thread(_delete)

    async def search_by_trigger(self, query: str) -> list[SkillComposition]:
        """Search compositions by trigger pattern or name."""

        def _search() -> list[SkillComposition]:
            with self.SessionLocal() as session:
                stmt = select(CompositionRecord).where(
                    CompositionRecord.name.contains(query)
                    | CompositionRecord.trigger_patterns.contains(query)
                )
                records = session.execute(stmt).scalars().all()
                return [self._record_to_composition(r) for r in records]

        return await asyncio.to_thread(_search)

    async def increment_usage(self, composition_id: str) -> None:
        """Increment the usage count for a composition."""

        def _increment() -> None:
            with self.SessionLocal() as session:
                record = session.get(CompositionRecord, composition_id)
                if record:
                    record.usage_count = (record.usage_count or 0) + 1
                    session.commit()

        await asyncio.to_thread(_increment)
