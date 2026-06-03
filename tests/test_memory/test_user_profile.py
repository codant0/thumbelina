"""Tests for thumbelina.memory.user_profile and user_profile_repo modules."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.memory.models import Base
from thumbelina.memory.user_profile import UserPreference, UserProfile
from thumbelina.memory.user_profile_repo import UserProfileRepository


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    session = test_session()
    yield session
    session.close()


@pytest.fixture
def repo():
    """Create a UserProfileRepository with in-memory SQLite database."""
    return UserProfileRepository("sqlite:///:memory:")


class TestUserProfileModel:
    """Tests for the UserProfile SQLAlchemy model."""

    def test_table_name(self):
        assert UserProfile.__tablename__ == "user_profiles"

    def test_has_id_column(self):
        assert hasattr(UserProfile, "id")

    def test_has_user_id_column(self):
        assert hasattr(UserProfile, "user_id")

    def test_has_communication_style_column(self):
        assert hasattr(UserProfile, "communication_style")

    def test_has_expertise_level_column(self):
        assert hasattr(UserProfile, "expertise_level")

    def test_has_created_at_column(self):
        assert hasattr(UserProfile, "created_at")

    def test_has_updated_at_column(self):
        assert hasattr(UserProfile, "updated_at")

    def test_create_profile(self, db_session: Session):
        profile = UserProfile(user_id="user1")
        db_session.add(profile)
        db_session.commit()

        assert profile.id is not None
        assert profile.user_id == "user1"
        assert profile.communication_style == "casual"
        assert profile.expertise_level == "intermediate"

    def test_repr(self, db_session: Session):
        profile = UserProfile(user_id="user1", communication_style="formal")
        db_session.add(profile)
        db_session.commit()
        assert "user1" in repr(profile)
        assert "formal" in repr(profile)


class TestUserPreferenceModel:
    """Tests for the UserPreference SQLAlchemy model."""

    def test_table_name(self):
        assert UserPreference.__tablename__ == "user_preferences"

    def test_has_id_column(self):
        assert hasattr(UserPreference, "id")

    def test_has_user_id_column(self):
        assert hasattr(UserPreference, "user_id")

    def test_has_category_column(self):
        assert hasattr(UserPreference, "category")

    def test_has_key_column(self):
        assert hasattr(UserPreference, "key")

    def test_has_value_column(self):
        assert hasattr(UserPreference, "value")

    def test_has_confidence_score_column(self):
        assert hasattr(UserPreference, "confidence_score")

    def test_has_created_at_column(self):
        assert hasattr(UserPreference, "created_at")

    def test_has_updated_at_column(self):
        assert hasattr(UserPreference, "updated_at")

    def test_create_preference(self, db_session: Session):
        pref = UserPreference(
            user_id="user1",
            category="topic",
            key="programming",
            value="Python",
            confidence_score=0.8,
        )
        db_session.add(pref)
        db_session.commit()

        assert pref.id is not None
        assert pref.user_id == "user1"
        assert pref.category == "topic"
        assert pref.key == "programming"
        assert pref.value == "Python"
        assert pref.confidence_score == 0.8

    def test_repr(self, db_session: Session):
        pref = UserPreference(user_id="user1", category="topic", key="lang", value="Python")
        db_session.add(pref)
        db_session.commit()
        assert "topic" in repr(pref)
        assert "lang" in repr(pref)


class TestUserProfileRepository:
    """Tests for the UserProfileRepository class."""

    @pytest.mark.asyncio
    async def test_get_or_create_profile_new(self, repo: UserProfileRepository):
        profile = await repo.get_or_create_profile("user1")
        assert profile["user_id"] == "user1"
        assert profile["communication_style"] == "casual"
        assert profile["expertise_level"] == "intermediate"

    @pytest.mark.asyncio
    async def test_get_or_create_profile_existing(self, repo: UserProfileRepository):
        profile1 = await repo.get_or_create_profile("user1")
        profile2 = await repo.get_or_create_profile("user1")
        assert profile1["id"] == profile2["id"]

    @pytest.mark.asyncio
    async def test_get_profile_not_found(self, repo: UserProfileRepository):
        profile = await repo.get_profile("nonexistent")
        assert profile is None

    @pytest.mark.asyncio
    async def test_get_profile_found(self, repo: UserProfileRepository):
        await repo.get_or_create_profile("user1")
        profile = await repo.get_profile("user1")
        assert profile is not None
        assert profile["user_id"] == "user1"

    @pytest.mark.asyncio
    async def test_update_profile(self, repo: UserProfileRepository):
        await repo.get_or_create_profile("user1")
        updated = await repo.update_profile(
            "user1", communication_style="formal", expertise_level="advanced"
        )
        assert updated is not None
        assert updated["communication_style"] == "formal"
        assert updated["expertise_level"] == "advanced"

    @pytest.mark.asyncio
    async def test_update_profile_partial(self, repo: UserProfileRepository):
        await repo.get_or_create_profile("user1")
        updated = await repo.update_profile("user1", communication_style="technical")
        assert updated is not None
        assert updated["communication_style"] == "technical"
        assert updated["expertise_level"] == "intermediate"  # unchanged

    @pytest.mark.asyncio
    async def test_update_profile_not_found(self, repo: UserProfileRepository):
        updated = await repo.update_profile("nonexistent", communication_style="formal")
        assert updated is None

    @pytest.mark.asyncio
    async def test_upsert_preference_new(self, repo: UserProfileRepository):
        pref = await repo.upsert_preference("user1", "topic", "language", "Python", 0.9)
        assert pref["category"] == "topic"
        assert pref["key"] == "language"
        assert pref["value"] == "Python"
        assert pref["confidence_score"] == 0.9

    @pytest.mark.asyncio
    async def test_upsert_preference_higher_confidence(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "language", "Python", 0.5)
        updated = await repo.upsert_preference("user1", "topic", "language", "Rust", 0.8)
        assert updated["value"] == "Rust"
        assert updated["confidence_score"] == 0.8

    @pytest.mark.asyncio
    async def test_upsert_preference_lower_confidence_keeps_old(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "language", "Python", 0.8)
        updated = await repo.upsert_preference("user1", "topic", "language", "Rust", 0.3)
        assert updated["value"] == "Python"  # kept old value
        assert updated["confidence_score"] == 0.8  # kept old confidence

    @pytest.mark.asyncio
    async def test_get_preferences_all(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "t1", "v1", 0.5)
        await repo.upsert_preference("user1", "format", "f1", "v2", 0.8)
        prefs = await repo.get_preferences("user1")
        assert len(prefs) == 2
        # Ordered by confidence desc
        assert prefs[0]["confidence_score"] >= prefs[1]["confidence_score"]

    @pytest.mark.asyncio
    async def test_get_preferences_by_category(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "t1", "v1", 0.5)
        await repo.upsert_preference("user1", "format", "f1", "v2", 0.8)
        prefs = await repo.get_preferences("user1", category="topic")
        assert len(prefs) == 1
        assert prefs[0]["category"] == "topic"

    @pytest.mark.asyncio
    async def test_get_preferences_empty(self, repo: UserProfileRepository):
        prefs = await repo.get_preferences("user1")
        assert prefs == []

    @pytest.mark.asyncio
    async def test_delete_preference(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "lang", "Python", 0.9)
        result = await repo.delete_preference("user1", "topic", "lang")
        assert result is True
        prefs = await repo.get_preferences("user1")
        assert len(prefs) == 0

    @pytest.mark.asyncio
    async def test_delete_preference_not_found(self, repo: UserProfileRepository):
        result = await repo.delete_preference("user1", "topic", "nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_all_preferences(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "t1", "v1", 0.5)
        await repo.upsert_preference("user1", "format", "f1", "v2", 0.8)
        count = await repo.delete_all_preferences("user1")
        assert count == 2
        prefs = await repo.get_preferences("user1")
        assert len(prefs) == 0

    @pytest.mark.asyncio
    async def test_different_users_isolated(self, repo: UserProfileRepository):
        await repo.upsert_preference("user1", "topic", "lang", "Python", 0.9)
        await repo.upsert_preference("user2", "topic", "lang", "Rust", 0.7)

        prefs1 = await repo.get_preferences("user1")
        prefs2 = await repo.get_preferences("user2")
        assert len(prefs1) == 1
        assert len(prefs2) == 1
        assert prefs1[0]["value"] == "Python"
        assert prefs2[0]["value"] == "Rust"
