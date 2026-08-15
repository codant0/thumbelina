"""thumbelina.agent.checkpointer 模块的测试。"""

from __future__ import annotations

import pytest

from thumbelina.agent.checkpointer import async_checkpointer_from_url, sqlite_path_from_url


class TestSqlitePathFromUrl:
    """sqlite_path_from_url URL 解析的测试。"""

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
    """异步检查点工厂生命周期的测试。"""

    @pytest.mark.asyncio
    async def test_non_sqlite_url_raises(self):
        """非 sqlite 的数据库 URL 快速失败（检查点是强制的）。"""
        with pytest.raises(RuntimeError, match="sqlite"):
            async with async_checkpointer_from_url("postgresql://localhost/db"):
                pass

    @pytest.mark.asyncio
    async def test_sqlite_url_lifecycle(self, tmp_path):
        """sqlite URL 产生可直接使用的 saver；关闭后文件仍保留。"""
        db_file = tmp_path / "checkpoints.db"
        async with async_checkpointer_from_url(f"sqlite:///{db_file}") as saver:
            # setup() 已执行：检查点表存在，未知 thread 为空。
            assert await saver.aget_tuple({"configurable": {"thread_id": "t1"}}) is None
        assert db_file.exists()
