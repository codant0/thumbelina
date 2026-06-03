"""SQLAlchemy models for user profiling."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from thumbelina.memory.models import Base


class UserProfile(Base):
    """User profile model storing communication style and expertise level.

    Attributes
    ----------
    id:
        Unique identifier for the profile record.
    user_id:
        Identifier for the user (e.g. from auth system).
    communication_style:
        Detected communication style (formal, casual, technical).
    expertise_level:
        Overall expertise level (beginner, intermediate, advanced).
    created_at:
        Timestamp when the profile was created.
    updated_at:
        Timestamp when the profile was last updated.
    """

    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    communication_style: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="casual",
    )
    expertise_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="intermediate",
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

    def __repr__(self) -> str:
        return (
            f"<UserProfile(id={self.id!r}, user_id={self.user_id!r}, "
            f"style={self.communication_style!r})>"
        )


class UserPreference(Base):
    """User preference model for storing categorized preferences with confidence.

    Attributes
    ----------
    id:
        Unique identifier for the preference record.
    user_id:
        Identifier for the user.
    category:
        Preference category (e.g. "topic", "language", "format").
    key:
        Preference key within the category.
    value:
        Preference value.
    confidence_score:
        Confidence score (0.0 to 1.0) indicating how certain the system is
        about this preference.
    created_at:
        Timestamp when the preference was created.
    updated_at:
        Timestamp when the preference was last updated.
    """

    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
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

    def __repr__(self) -> str:
        return (
            f"<UserPreference(id={self.id!r}, user_id={self.user_id!r}, "
            f"category={self.category!r}, key={self.key!r})>"
        )
