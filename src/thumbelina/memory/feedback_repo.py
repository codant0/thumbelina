"""Repository for user feedback data access."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from thumbelina.memory.models import Base, FeedbackRecord


@dataclass
class Feedback:
    """Data class representing a user feedback record.

    Attributes
    ----------
    id:
        Unique identifier for the feedback.
    conversation_id:
        ID of the conversation this feedback relates to.
    message_index:
        Index of the message within the conversation.
    rating:
        User rating from 1 (worst) to 5 (best).
    comment:
        Optional free-text comment.
    skill_id:
        Optional skill ID if feedback is about a specific skill.
    created_at:
        When the feedback was created.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_index: int = 0
    rating: int = 0
    comment: str | None = None
    skill_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


class FeedbackRepository:
    """Repository for managing user feedback records.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL (e.g., "sqlite:///thumbelina.db").
    """

    def __init__(self, db_url: str = "sqlite:///thumbelina.db") -> None:
        from thumbelina.memory.db import create_db_engine, init_db

        self.engine = create_db_engine(db_url)
        self.SessionLocal = init_db(self.engine)

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

    def _record_to_feedback(self, record: FeedbackRecord) -> Feedback:
        """Convert a database record to a Feedback dataclass."""
        return Feedback(
            id=record.id,
            conversation_id=record.conversation_id,
            message_index=record.message_index,
            rating=record.rating,
            comment=record.comment,
            skill_id=record.skill_id,
            created_at=record.created_at if record.created_at else datetime.now(),
        )

    def _save_sync(self, feedback: Feedback) -> Feedback:
        """Synchronous implementation of save."""
        with self.SessionLocal() as session:
            record = session.get(FeedbackRecord, feedback.id)
            if record:
                record.conversation_id = feedback.conversation_id
                record.message_index = feedback.message_index
                record.rating = feedback.rating
                record.comment = feedback.comment
                record.skill_id = feedback.skill_id
            else:
                record = FeedbackRecord(
                    id=feedback.id,
                    conversation_id=feedback.conversation_id,
                    message_index=feedback.message_index,
                    rating=feedback.rating,
                    comment=feedback.comment,
                    skill_id=feedback.skill_id,
                )
                session.add(record)
            session.commit()
            session.refresh(record)
            return self._record_to_feedback(record)

    async def save(self, feedback: Feedback) -> Feedback:
        """Save or update a feedback record.

        Parameters
        ----------
        feedback:
            The feedback to save.

        Returns
        -------
        Feedback
            The saved feedback with populated fields.
        """
        return await asyncio.to_thread(self._save_sync, feedback)

    def _get_sync(self, feedback_id: str) -> Feedback | None:
        """Synchronous implementation of get."""
        with self.SessionLocal() as session:
            record = session.get(FeedbackRecord, feedback_id)
            return self._record_to_feedback(record) if record else None

    async def get(self, feedback_id: str) -> Feedback | None:
        """Get a feedback record by ID.

        Parameters
        ----------
        feedback_id:
            ID of the feedback to retrieve.

        Returns
        -------
        Feedback | None
            The feedback record, or None if not found.
        """
        return await asyncio.to_thread(self._get_sync, feedback_id)

    def _list_by_conversation_sync(self, conversation_id: str) -> list[Feedback]:
        """Synchronous implementation of list_by_conversation."""
        with self.SessionLocal() as session:
            stmt = (
                select(FeedbackRecord)
                .where(FeedbackRecord.conversation_id == conversation_id)
                .order_by(FeedbackRecord.message_index)
            )
            records = session.execute(stmt).scalars().all()
            return [self._record_to_feedback(r) for r in records]

    async def list_by_conversation(self, conversation_id: str) -> list[Feedback]:
        """List all feedback for a conversation.

        Parameters
        ----------
        conversation_id:
            ID of the conversation to list feedback for.

        Returns
        -------
        list[Feedback]
            List of feedback records ordered by message index.
        """
        return await asyncio.to_thread(self._list_by_conversation_sync, conversation_id)

    def _list_by_skill_sync(self, skill_id: str) -> list[Feedback]:
        """Synchronous implementation of list_by_skill."""
        with self.SessionLocal() as session:
            stmt = (
                select(FeedbackRecord)
                .where(FeedbackRecord.skill_id == skill_id)
                .order_by(FeedbackRecord.created_at.desc())
            )
            records = session.execute(stmt).scalars().all()
            return [self._record_to_feedback(r) for r in records]

    async def list_by_skill(self, skill_id: str) -> list[Feedback]:
        """List all feedback for a specific skill.

        Parameters
        ----------
        skill_id:
            ID of the skill to list feedback for.

        Returns
        -------
        list[Feedback]
            List of feedback records ordered by creation time (newest first).
        """
        return await asyncio.to_thread(self._list_by_skill_sync, skill_id)

    def _list_all_sync(self) -> list[Feedback]:
        """Synchronous implementation of list_all."""
        with self.SessionLocal() as session:
            stmt = select(FeedbackRecord).order_by(FeedbackRecord.created_at.desc())
            records = session.execute(stmt).scalars().all()
            return [self._record_to_feedback(r) for r in records]

    async def list_all(self) -> list[Feedback]:
        """List all feedback records.

        Returns
        -------
        list[Feedback]
            List of all feedback records ordered by creation time (newest first).
        """
        return await asyncio.to_thread(self._list_all_sync)

    def _get_average_rating_sync(self, skill_id: str | None = None) -> dict[str, Any]:
        """Synchronous implementation of get_average_rating."""
        with self.SessionLocal() as session:
            query = select(
                func.avg(FeedbackRecord.rating),
                func.count(FeedbackRecord.id),
            )
            if skill_id is not None:
                query = query.where(FeedbackRecord.skill_id == skill_id)

            result = session.execute(query).one()
            avg_rating = result[0]
            count = result[1]

            return {
                "average_rating": round(float(avg_rating), 2) if avg_rating else 0.0,
                "count": count,
                "skill_id": skill_id,
            }

    async def get_average_rating(self, skill_id: str | None = None) -> dict[str, Any]:
        """Get the average rating, optionally filtered by skill.

        Parameters
        ----------
        skill_id:
            Optional skill ID to filter by.

        Returns
        -------
        dict[str, Any]
            Dictionary with ``average_rating``, ``count``, and ``skill_id``.
        """
        return await asyncio.to_thread(self._get_average_rating_sync, skill_id)

    def _delete_sync(self, feedback_id: str) -> bool:
        """Synchronous implementation of delete."""
        with self.SessionLocal() as session:
            record = session.get(FeedbackRecord, feedback_id)
            if not record:
                return False
            session.delete(record)
            session.commit()
            return True

    async def delete(self, feedback_id: str) -> bool:
        """Delete a feedback record.

        Parameters
        ----------
        feedback_id:
            ID of the feedback to delete.

        Returns
        -------
        bool
            True if deleted, False if not found.
        """
        return await asyncio.to_thread(self._delete_sync, feedback_id)
