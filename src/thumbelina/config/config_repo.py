"""Repository for system configuration data access."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

from sqlalchemy import select

from thumbelina.memory.models import SystemConfig

logger = logging.getLogger(__name__)

# Sensitive fields that must never be stored in the database.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "secret_key",
        "app_secret",
        "bot_token",
        "webhook_secret",
    }
)


def _is_sensitive(key: str) -> bool:
    """Check if a config key contains sensitive data."""
    suffix = key.rsplit(".", 1)[-1] if "." in key else key
    return suffix in _SENSITIVE_KEYS


class ConfigRepository:
    """Repository for managing system configuration in the database.

    Parameters
    ----------
    db_url:
        SQLAlchemy database URL (e.g., "sqlite:///thumbelina.db").
    """

    def __init__(self, db_url: str) -> None:
        from thumbelina.memory.db import create_db_engine, init_db

        self.engine = create_db_engine(db_url)
        self.SessionLocal = init_db(self.engine)

    def close(self) -> None:
        """Dispose of the database engine and release connections."""
        self.engine.dispose()

    def _is_empty_sync(self) -> bool:
        """Check if the system_config table is empty."""
        with self.SessionLocal() as session:
            from sqlalchemy import func

            count = cast(int, session.query(func.count(SystemConfig.key)).scalar())
            return count == 0

    async def is_empty(self) -> bool:
        """Check if the system_config table is empty.

        Returns
        -------
        bool
            True if no config entries exist.
        """
        return await asyncio.to_thread(self._is_empty_sync)

    # ------------------------------------------------------------------
    # Sync helpers (called via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _get_sync(self, key: str) -> str | None:
        """Synchronous implementation of get."""
        with self.SessionLocal() as session:
            record = session.get(SystemConfig, key)
            if record is None:
                return None
            return cast(str, record.value)

    def _set_sync(self, key: str, value: str, category: str) -> None:
        """Synchronous implementation of set."""
        with self.SessionLocal() as session:
            record = session.get(SystemConfig, key)
            if record:
                record.value = value
                record.category = category
            else:
                record = SystemConfig(key=key, value=value, category=category)
                session.add(record)
            session.commit()

    def _delete_sync(self, key: str) -> bool:
        """Synchronous implementation of delete."""
        with self.SessionLocal() as session:
            record = session.get(SystemConfig, key)
            if not record:
                return False
            session.delete(record)
            session.commit()
            return True

    def _get_all_sync(self) -> dict[str, str]:
        """Synchronous implementation of get_all."""
        with self.SessionLocal() as session:
            stmt = select(SystemConfig)
            records = session.execute(stmt).scalars().all()
            return {r.key: r.value for r in records}

    def _get_by_category_sync(self, category: str) -> dict[str, str]:
        """Synchronous implementation of get_by_category."""
        with self.SessionLocal() as session:
            stmt = select(SystemConfig).where(SystemConfig.category == category)
            records = session.execute(stmt).scalars().all()
            return {r.key: r.value for r in records}

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def get(self, key: str) -> str | None:
        """Get a configuration value by key.

        Parameters
        ----------
        key:
            Dotted config path (e.g., "llm.provider").

        Returns
        -------
        str | None
            The config value, or None if not found.
        """
        return await asyncio.to_thread(self._get_sync, key)

    async def set(self, key: str, value: str, category: str) -> None:
        """Set a configuration value.

        Parameters
        ----------
        key:
            Dotted config path (e.g., "llm.provider").
        value:
            The serialized config value.
        category:
            Config category (e.g., "llm", "channel").
        """
        if _is_sensitive(key):
            logger.warning("Refusing to store sensitive key %s in database", key)
            return
        await asyncio.to_thread(self._set_sync, key, value, category)

    async def delete(self, key: str) -> bool:
        """Delete a configuration value.

        Parameters
        ----------
        key:
            Dotted config path.

        Returns
        -------
        bool
            True if deleted, False if not found.
        """
        return await asyncio.to_thread(self._delete_sync, key)

    async def get_all(self) -> dict[str, str]:
        """Get all configuration values.

        Returns
        -------
        dict[str, str]
            Mapping of dotted config paths to serialized values.
        """
        return await asyncio.to_thread(self._get_all_sync)

    async def get_by_category(self, category: str) -> dict[str, str]:
        """Get all configuration values for a category.

        Parameters
        ----------
        category:
            Config category (e.g., "llm", "channel").

        Returns
        -------
        dict[str, str]
            Mapping of dotted config paths to serialized values.
        """
        return await asyncio.to_thread(self._get_by_category_sync, category)

    async def import_from_dict(self, data: dict[str, Any], category: str) -> int:
        """Import configuration from a nested dict, skipping sensitive fields.

        Parameters
        ----------
        data:
            Nested configuration dict (e.g., from YAML).
        category:
            Config category.

        Returns
        -------
        int
            Number of keys imported.
        """
        count = 0

        def _flatten(obj: Any, prefix: str = "") -> None:
            nonlocal count
            if isinstance(obj, dict):
                for k, v in obj.items():
                    new_key = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, dict):
                        _flatten(v, new_key)
                    else:
                        if not _is_sensitive(new_key):
                            self._set_sync(new_key, json.dumps(v), category)
                            count += 1
            elif isinstance(obj, list):
                if not _is_sensitive(prefix):
                    self._set_sync(prefix, json.dumps(obj), category)
                    count += 1

        _flatten(data)
        return count

    async def export_to_dict(self, category: str | None = None) -> dict[str, Any]:
        """Export configuration to a nested dict.

        Parameters
        ----------
        category:
            Optional category filter.

        Returns
        -------
        dict[str, Any]
            Nested configuration dict with deserialized values.
        """
        if category:
            flat = await self.get_by_category(category)
        else:
            flat = await self.get_all()

        result: dict[str, Any] = {}
        for key, value in flat.items():
            parts = key.split(".")
            current = result
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            try:
                current[parts[-1]] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                current[parts[-1]] = value

        return result
