"""Tests for :class:`thumbelina.filestore.locks.FileLocks`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from thumbelina.filestore.locks import FileLocks


def run(coro):
    """Run an async coroutine synchronously on a fresh event loop."""
    return asyncio.run(coro)


async def test_locked_serializes_concurrent_sections(tmp_path: Path) -> None:
    locks = FileLocks()
    path = tmp_path / "file.md"
    order: list[str] = []

    async def worker(name: str, delay: float) -> None:
        async with locks.locked(path):
            order.append(f"{name}:enter")
            await asyncio.sleep(delay)
            order.append(f"{name}:exit")

    await asyncio.gather(worker("a", 0.02), worker("b", 0.0), worker("c", 0.0))

    # Critical sections never interleave: each entry partitions the ordering.
    for i in range(0, len(order), 2):
        assert order[i].endswith(":enter")
        assert order[i + 1].endswith(":exit")
        assert order[i].split(":")[0] == order[i + 1].split(":")[0]


async def test_two_keys_are_independent(tmp_path: Path) -> None:
    locks = FileLocks()
    p1 = tmp_path / "a.md"
    p2 = tmp_path / "b.md"
    order: list[str] = []

    async def hold(p: Path, name: str) -> None:
        async with locks.locked(p):
            order.append(f"{name}:enter")
            await asyncio.sleep(0.05)
            order.append(f"{name}:exit")

    # Hold a.md then, while held, confirm b.md is NOT blocked by a.md.
    async def check_b_not_blocked() -> None:
        async with locks.locked(p2):
            order.append("b:enter")
            order.append("b:exit")

    task_a = asyncio.ensure_future(hold(p1, "a"))
    await asyncio.sleep(0.01)
    await check_b_not_blocked()
    await task_a

    assert "b:enter" in order and "b:exit" in order


async def test_same_key_is_reused(tmp_path: Path) -> None:
    locks = FileLocks()
    p = tmp_path / "f.md"
    # Two sequential acquisitions must contend on the same lock object.
    acquired: list[asyncio.Lock] = []

    # Peek the underlying lock used for this key.
    lock = await locks._lock_for(p)  # noqa: SLF001
    async with locks.locked(p):
        acquired.append(lock)
    async with locks.locked(p):
        acquired.append(await locks._lock_for(p))  # noqa: SLF001

    assert acquired[0] is acquired[1]


async def test_locked_multi_key_sorted_and_dedup(tmp_path: Path) -> None:
    locks = FileLocks()
    p_a = tmp_path / "a.md"
    p_b = tmp_path / "b.md"
    order: list[str] = []

    async def acquire_pair() -> None:
        # Pass keys out of order and duplicated; ordering is by sorted path.
        async with locks.locked(p_b, p_a, p_a, p_b):
            order.append((await locks._lock_for(p_a), await locks._lock_for(p_b)))  # noqa: SLF001

    await acquire_pair()

    # Both locks are the same reusable instances.
    a_lock, b_lock = order[0]
    async with locks.locked(p_a):
        assert await locks._lock_for(p_a) is a_lock  # noqa: SLF001


async def test_no_keys_yields_immediately() -> None:
    locks = FileLocks()
    ran = False
    async with locks.locked():
        ran = True
    assert ran


async def test_none_keys_are_ignored() -> None:
    locks = FileLocks()
    async with locks.locked(None, None):
        pass  # no error, no locks acquired
