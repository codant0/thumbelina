"""Checkpointer creation helpers for the LangGraph context layer.

The checkpointer persists graph state (the mutable LLM context workspace)
between agent turns, keyed by ``thread_id`` (which equals the conversation
id). This module centralizes saver construction so that API, CLI, and test
entry points share one lifecycle-safe factory.

Graceful degradation (design doc 四.2):

- Non-sqlite ``database_url`` values yield ``checkpointer=None`` — the agent
  behaves exactly as before checkpointing existed.
- A missing ``langgraph-checkpoint-sqlite`` package likewise degrades to
  ``None`` with a warning instead of failing startup.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

_SQLITE_URL_PREFIXES = ("sqlite+pysqlite:///", "sqlite:///")


def sqlite_path_from_url(database_url: str) -> str | None:
    """Extract the filesystem path from a sqlite ``database_url``.

    Args:
        database_url: SQLAlchemy-style URL, e.g. ``sqlite:///thumbelina.db``.

    Returns:
        The database file path, or ``None`` if the URL is not sqlite-based.
    """
    for prefix in _SQLITE_URL_PREFIXES:
        if database_url.startswith(prefix):
            path = database_url[len(prefix) :]
            return path or None
    return None


@asynccontextmanager
async def async_checkpointer_from_url(database_url: str) -> AsyncIterator[Any]:
    """Yield an ``AsyncSqliteSaver`` for the given database URL.

    The saver is created inside the caller's event loop (an aiosqlite
    requirement), its checkpoint tables are created idempotently via
    ``setup()``, and the underlying connection is closed on exit.

    Args:
        database_url: SQLAlchemy-style URL from ``MemoryConfig.database_url``.

    Yields:
        An ``AsyncSqliteSaver`` instance, or ``None`` when checkpointing is
        unavailable (non-sqlite URL, missing package, or open failure).
        Callers must tolerate ``None`` — the agent degrades to stateless.
    """
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is None:
        logger.info("Checkpointer disabled: database_url %r is not sqlite-based", database_url)
        yield None
        return

    try:
        # mypy cannot resolve this namespace-package submodule (upstream
        # packaging quirk); it imports fine at runtime.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[import-not-found]  # noqa: I001
    except ImportError:
        logger.warning(
            "langgraph-checkpoint-sqlite is not installed; context persistence disabled "
            "(install it with `pip install langgraph-checkpoint-sqlite`)"
        )
        yield None
        return

    stack = AsyncExitStack()
    try:
        saver = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(sqlite_path))
        await saver.setup()
    except Exception as exc:
        await stack.aclose()
        logger.warning("Checkpointer initialization failed; context persistence disabled (%s)", exc)
        yield None
        return

    try:
        yield saver
    finally:
        await stack.aclose()
