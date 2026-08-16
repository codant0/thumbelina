"""跨入口共享的 per-conversation 异步锁。

同一会话（``thread_id == conversation_id``）的 LangGraph 检查点更新
绝不能交错，无论轮次来自 WebSocket、HTTP ``/chat`` 还是通道。所有
入口共享同一个锁注册表，确保指向同一会话的并发轮次被串行化。

锁条目是弱引用：锁只在至少有一轮持有它时存活，会话在连接关闭后
绝不会泄漏锁。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

_conversation_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_conversation_locks_guard = asyncio.Lock()


async def conversation_lock_for(cid: str) -> asyncio.Lock:
    """返回 *cid* 的共享锁，首次使用时创建。"""
    async with _conversation_locks_guard:
        lock = _conversation_locks.get(cid)
        if lock is None:
            lock = asyncio.Lock()
            _conversation_locks[cid] = lock
        return lock


@asynccontextmanager
async def per_conversation_lock(cid: str | None) -> AsyncIterator[None]:
    """串行化单个会话的轮次。

    ``cid=None``（无会话、临时 thread id —— 没有可冲突的对象）时
    立即 yield。锁在退出时释放；一旦没有轮次持有它，注册表条目即因
    弱引用而消亡。
    """
    if cid is None:
        yield
        return
    lock = await conversation_lock_for(cid)
    async with lock:
        yield
