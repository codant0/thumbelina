"""按 key 的文件锁表,串行化"读-改-写"的临界区。

业务服务(如 ``todo``、``memory``)各自持有 :class:`FileLocks` 实例,
用 ``async with locks.locked(path)`` 包裹需要对单个文件做的读写操作;
涉及**多个文件**(例如 memory 写条目后还要重建 ``index.md``)时,传入
多个 key,锁会按稳定顺序依次获取,避免不同调用方按不同顺序加锁导致
死锁。

传统做法是"整目录一把锁";这里按 key(通常是文件路径)加锁,让互不
相关的文件可以并发操作,同时为跨文件的复合写保留一致性。

注:锁是**进程内**的(asyncio),作用于单个事件循环,与既有行为一致。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

LockKey = Path | str


class FileLocks:
    """维护 ``key -> asyncio.Lock`` 映射并提供多 key 顺序加锁。"""

    def __init__(self) -> None:
        self._locks: dict[LockKey, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _lock_for(self, key: LockKey) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def locked(self, *keys: LockKey | None) -> AsyncIterator[None]:
        """按稳定顺序获取 ``keys`` 各自对应的锁,退出时逆序释放。

        传入零个 key 时立即 yield(无临界区)。重复 key 会去重;``None``
        会被忽略。key 为文件路径(``Path``/``str``),按排序后的稳定顺序
        获取,避免不同调用方按不同顺序加锁导致死锁。
        """
        unique = sorted({key for key in keys if key is not None})
        acquired: list[asyncio.Lock] = []
        try:
            for key in unique:
                lock = await self._lock_for(key)
                await lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()
