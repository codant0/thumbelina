"""Repository for user profile and preference data access."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from thumbelina.memory.models import Base
from thumbelina.memory.user_profile import UserPreference, UserProfile


class UserProfileRepository:
    """Repository for managing user profiles and preferences.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL (e.g., "sqlite:///thumbelina.db").
    """

    def __init__(self, db_url: str) -> None:
        if db_url == "sqlite:///:memory:" or db_url.startswith("sqlite:///:memory:"):
            self.engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine = create_engine(db_url, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def _get_or_create_profile_sync(self, user_id: str) -> dict[str, Any]:
        """Synchronous implementation of get_or_create_profile."""
        with self._get_session() as session:
            stmt = select(UserProfile).where(UserProfile.user_id == user_id)
            profile = session.execute(stmt).scalars().first()

            if profile is None:
                profile = UserProfile(user_id=user_id)
                session.add(profile)
                session.commit()
                session.refresh(profile)

            return {
                "id": profile.id,
                "user_id": profile.user_id,
                "communication_style": profile.communication_style,
                "expertise_level": profile.expertise_level,
                "created_at": profile.created_at.isoformat(),
                "updated_at": profile.updated_at.isoformat(),
            }

    async def get_or_create_profile(self, user_id: str) -> dict[str, Any]:
        """Get an existing user profile or create a new one.

        Parameters
        ----------
        user_id:
            Identifier for the user.

        Returns
        -------
        dict[str, Any]
            The user profile dictionary.
        """
        return await asyncio.to_thread(self._get_or_create_profile_sync, user_id)

    def _get_profile_sync(self, user_id: str) -> dict[str, Any] | None:
        """Synchronous implementation of get_profile."""
        with self._get_session() as session:
            stmt = select(UserProfile).where(UserProfile.user_id == user_id)
            profile = session.execute(stmt).scalars().first()

            if profile is None:
                return None

            return {
                "id": profile.id,
                "user_id": profile.user_id,
                "communication_style": profile.communication_style,
                "expertise_level": profile.expertise_level,
                "created_at": profile.created_at.isoformat(),
                "updated_at": profile.updated_at.isoformat(),
            }

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        """Get a user profile by user ID.

        Parameters
        ----------
        user_id:
            Identifier for the user.

        Returns
        -------
        dict[str, Any] | None
            The user profile dictionary, or None if not found.
        """
        return await asyncio.to_thread(self._get_profile_sync, user_id)

    def _update_profile_sync(
        self,
        user_id: str,
        communication_style: str | None = None,
        expertise_level: str | None = None,
    ) -> dict[str, Any] | None:
        """Synchronous implementation of update_profile."""
        with self._get_session() as session:
            stmt = select(UserProfile).where(UserProfile.user_id == user_id)
            profile = session.execute(stmt).scalars().first()

            if profile is None:
                return None

            if communication_style is not None:
                profile.communication_style = communication_style
            if expertise_level is not None:
                profile.expertise_level = expertise_level

            session.commit()
            session.refresh(profile)

            return {
                "id": profile.id,
                "user_id": profile.user_id,
                "communication_style": profile.communication_style,
                "expertise_level": profile.expertise_level,
                "created_at": profile.created_at.isoformat(),
                "updated_at": profile.updated_at.isoformat(),
            }

    async def update_profile(
        self,
        user_id: str,
        communication_style: str | None = None,
        expertise_level: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a user profile.

        Parameters
        ----------
        user_id:
            Identifier for the user.
        communication_style:
            New communication style (formal, casual, technical).
        expertise_level:
            New expertise level (beginner, intermediate, advanced).

        Returns
        -------
        dict[str, Any] | None
            The updated profile, or None if not found.
        """
        return await asyncio.to_thread(
            self._update_profile_sync, user_id, communication_style, expertise_level
        )

    # ------------------------------------------------------------------
    # Preference CRUD
    # ------------------------------------------------------------------

    def _upsert_preference_sync(
        self,
        user_id: str,
        category: str,
        key: str,
        value: str,
        confidence_score: float = 0.5,
    ) -> dict[str, Any]:
        """Synchronous implementation of upsert_preference."""
        with self._get_session() as session:
            stmt = select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.category == category,
                UserPreference.key == key,
            )
            pref = session.execute(stmt).scalars().first()

            if pref is not None:
                # Update existing preference — take higher confidence
                if confidence_score >= pref.confidence_score:
                    pref.value = value
                    pref.confidence_score = confidence_score
                session.commit()
                session.refresh(pref)
            else:
                pref = UserPreference(
                    user_id=user_id,
                    category=category,
                    key=key,
                    value=value,
                    confidence_score=confidence_score,
                )
                session.add(pref)
                session.commit()
                session.refresh(pref)

            return {
                "id": pref.id,
                "user_id": pref.user_id,
                "category": pref.category,
                "key": pref.key,
                "value": pref.value,
                "confidence_score": pref.confidence_score,
                "created_at": pref.created_at.isoformat(),
                "updated_at": pref.updated_at.isoformat(),
            }

    async def upsert_preference(
        self,
        user_id: str,
        category: str,
        key: str,
        value: str,
        confidence_score: float = 0.5,
    ) -> dict[str, Any]:
        """Insert or update a user preference.

        If the preference already exists (same user_id + category + key),
        the value is updated only when the new confidence score is higher
        than the existing one.

        Parameters
        ----------
        user_id:
            Identifier for the user.
        category:
            Preference category (e.g. "topic", "language", "format").
        key:
            Preference key within the category.
        value:
            Preference value.
        confidence_score:
            Confidence score (0.0 to 1.0).

        Returns
        -------
        dict[str, Any]
            The created or updated preference dictionary.
        """
        return await asyncio.to_thread(
            self._upsert_preference_sync,
            user_id,
            category,
            key,
            value,
            confidence_score,
        )

    def _get_preferences_sync(
        self,
        user_id: str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronous implementation of get_preferences."""
        with self._get_session() as session:
            stmt = select(UserPreference).where(UserPreference.user_id == user_id)
            if category is not None:
                stmt = stmt.where(UserPreference.category == category)
            stmt = stmt.order_by(
                UserPreference.confidence_score.desc(),
                UserPreference.category,
                UserPreference.key,
            )
            prefs = session.execute(stmt).scalars().all()

            return [
                {
                    "id": p.id,
                    "user_id": p.user_id,
                    "category": p.category,
                    "key": p.key,
                    "value": p.value,
                    "confidence_score": p.confidence_score,
                    "created_at": p.created_at.isoformat(),
                    "updated_at": p.updated_at.isoformat(),
                }
                for p in prefs
            ]

    async def get_preferences(
        self,
        user_id: str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all preferences for a user, optionally filtered by category.

        Parameters
        ----------
        user_id:
            Identifier for the user.
        category:
            Optional category filter.

        Returns
        -------
        list[dict[str, Any]]
            List of preference dictionaries ordered by confidence score descending.
        """
        return await asyncio.to_thread(self._get_preferences_sync, user_id, category)

    def _delete_preference_sync(
        self,
        user_id: str,
        category: str,
        key: str,
    ) -> bool:
        """Synchronous implementation of delete_preference."""
        with self._get_session() as session:
            stmt = select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.category == category,
                UserPreference.key == key,
            )
            pref = session.execute(stmt).scalars().first()

            if pref is None:
                return False

            session.delete(pref)
            session.commit()
            return True

    async def delete_preference(
        self,
        user_id: str,
        category: str,
        key: str,
    ) -> bool:
        """Delete a specific user preference.

        Parameters
        ----------
        user_id:
            Identifier for the user.
        category:
            Preference category.
        key:
            Preference key.

        Returns
        -------
        bool
            True if the preference was deleted, False if not found.
        """
        return await asyncio.to_thread(self._delete_preference_sync, user_id, category, key)

    def _delete_all_preferences_sync(self, user_id: str) -> int:
        """Synchronous implementation of delete_all_preferences."""
        with self._get_session() as session:
            stmt = select(UserPreference).where(UserPreference.user_id == user_id)
            prefs = session.execute(stmt).scalars().all()
            count = len(prefs)
            for pref in prefs:
                session.delete(pref)
            session.commit()
            return count

    async def delete_all_preferences(self, user_id: str) -> int:
        """Delete all preferences for a user.

        Parameters
        ----------
        user_id:
            Identifier for the user.

        Returns
        -------
        int
            Number of deleted preferences.
        """
        return await asyncio.to_thread(self._delete_all_preferences_sync, user_id)
