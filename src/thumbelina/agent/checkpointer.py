"""Checkpointer creation helpers for the LangGraph context layer.

The checkpointer persists graph state (the mutable LLM context workspace)
between agent turns, keyed by ``thread_id`` (which equals the conversation
id). This module centralizes saver construction so that API, CLI, and test
entry points share one lifecycle-safe factory.

Checkpointing is a hard requirement of the runtime: this factory fails fast
with an actionable error instead of degrading to a stateless agent.

- A non-sqlite ``database_url`` raises — Postgres support is a later phase.
- A missing ``langgraph-checkpoint-sqlite`` package raises with install
  instructions.
- An open/setup failure propagates so startup aborts with the root cause.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: I001
except ImportError as exc:
    raise ImportError(
        "langgraph-checkpoint-sqlite is required for the LangGraph context "
        "layer. Install it with: pip install langgraph-checkpoint-sqlite"
    ) from exc

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
async def async_checkpointer_from_url(database_url: str) -> AsyncIterator[AsyncSqliteSaver]:
    """Yield an ``AsyncSqliteSaver`` for the given database URL.

    The saver is created inside the caller's event loop (an aiosqlite
    requirement), its checkpoint tables are created idempotently via
    ``setup()``, and the underlying connection is closed on exit.

    Raises:
        RuntimeError: If *database_url* is not sqlite-based (Postgres support
            is a later phase).
        ImportError: If ``langgraph-checkpoint-sqlite`` is not installed.
            Initialization failures propagate unchanged.

    Yields:
        An ``AsyncSqliteSaver`` instance. Checkpointing is a hard runtime
        requirement, so this never yields ``None`` — failures abort startup.
    """
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is None:
        raise RuntimeError(
            f"LangGraph checkpointing requires a sqlite database_url, got "
            f"{database_url!r}. Postgres checkpointer support is a later phase."
        )

    stack = AsyncExitStack()
    saver = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(sqlite_path))
    await saver.setup()
    try:
        yield saver
    finally:
        await stack.aclose()
