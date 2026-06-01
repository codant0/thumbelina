"""Dependency injection for the Thumbelina API."""

from __future__ import annotations

from thumbelina.memory.manager import MemoryManager

# Default in-memory database for API usage
_DEFAULT_DB_URL = "sqlite:///:memory:"

# Module-level singleton for the memory manager
_memory_manager: MemoryManager | None = None


def get_memory_manager(db_url: str | None = None) -> MemoryManager:
    """Get or create the MemoryManager singleton.

    Parameters
    ----------
    db_url:
        Database URL. If None, uses the default in-memory SQLite.

    Returns
    -------
    MemoryManager
        The memory manager instance.
    """
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(db_url or _DEFAULT_DB_URL)
    return _memory_manager


def reset_memory_manager() -> None:
    """Reset the memory manager singleton (for testing)."""
    global _memory_manager
    if _memory_manager is not None:
        _memory_manager.close()
    _memory_manager = None
