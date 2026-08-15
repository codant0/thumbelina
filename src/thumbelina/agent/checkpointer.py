"""LangGraph 上下文层的检查点存储器创建辅助函数。

检查点存储器在 agent 轮次之间持久化图状态（可变的 LLM 上下文工作区），
以 ``thread_id``（即会话 id）为键。本模块集中管理 saver 的构造，
让 API、CLI 与测试入口共享同一个生命周期安全的工厂。

检查点是运行时的硬性要求：该工厂快速失败并给出可操作的错误，
而不是降级为无状态 agent。

- 非 sqlite 的 ``database_url`` 会直接报错 —— Postgres 支持是后续阶段。
- 缺少 ``langgraph-checkpoint-sqlite`` 包时报错并附安装说明。
- 打开/初始化失败会继续向上传播，让启动过程带着根因中止。
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
    """从 sqlite ``database_url`` 中提取文件系统路径。

    Args:
        database_url: SQLAlchemy 风格的 URL，例如 ``sqlite:///thumbelina.db``。

    Returns:
        数据库文件路径；若 URL 不是基于 sqlite 的，则返回 ``None``。
    """
    for prefix in _SQLITE_URL_PREFIXES:
        if database_url.startswith(prefix):
            path = database_url[len(prefix) :]
            return path or None
    return None


@asynccontextmanager
async def async_checkpointer_from_url(database_url: str) -> AsyncIterator[AsyncSqliteSaver]:
    """为给定的数据库 URL 生成一个 ``AsyncSqliteSaver``。

    saver 在调用方的事件循环内创建（aiosqlite 的要求），其检查点表
    通过 ``setup()`` 幂等创建，底层连接在退出时关闭。

    Raises:
        RuntimeError: 如果 *database_url* 不是基于 sqlite 的
            （Postgres 支持是后续阶段）。
        ImportError: 如果未安装 ``langgraph-checkpoint-sqlite``。
            初始化失败原样向上传播。

    Yields:
        一个 ``AsyncSqliteSaver`` 实例。检查点是硬性运行时要求，
        因此这里永远不会产生 ``None`` —— 失败即中止启动。
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
