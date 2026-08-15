"""Tests for thumbelina.agent.checkpointer module."""

from __future__ import annotations

import pytest

from thumbelina.agent.checkpointer import async_checkpointer_from_url, sqlite_path_from_url


class TestSqlitePathFromUrl:
    """Tests for sqlite_path_from_url URL parsing."""

    def test_plain_sqlite_url(self):
        assert sqlite_path_from_url("sqlite:///thumbelina.db") == "thumbelina.db"

    def test_pysqlite_url(self):
        assert sqlite_path_from_url("sqlite+pysqlite:///data/app.db") == "data/app.db"

    def test_memory_url(self):
        assert sqlite_path_from_url("sqlite:///:memory:") == ":memory:"

    def test_empty_path_returns_none(self):
        assert sqlite_path_from_url("sqlite:///") is None

    def test_non_sqlite_url_returns_none(self):
        assert sqlite_path_from_url("postgresql://user:pw@localhost/db") is None


class TestAsyncCheckpointerFromUrl:
    """Tests for the async checkpointer factory lifecycle."""

    @pytest.mark.asyncio
    async def test_non_sqlite_url_raises(self):
        """Non-sqlite database URLs fail fast (checkpointing is mandatory)."""
        with pytest.raises(RuntimeError, match="sqlite"):
            async with async_checkpointer_from_url("postgresql://localhost/db"):
                pass

    @pytest.mark.asyncio
    async def test_sqlite_url_lifecycle(self, tmp_path):
        """A sqlite URL yields a ready-to-use saver; the file persists after close."""
        db_file = tmp_path / "checkpoints.db"
        async with async_checkpointer_from_url(f"sqlite:///{db_file}") as saver:
            # setup() already ran: checkpoint tables exist, unknown thread is empty.
            assert await saver.aget_tuple({"configurable": {"thread_id": "t1"}}) is None
        assert db_file.exists()
