"""公共文件存储能力:原子的底层文件操作 + 按 key 的异步文件锁。

- :func:`write_text_atomic` / :func:`read_text` / :func:`safe_unlink`
  / :func:`cleanup_tmp` / :func:`ensure_dir`:原子、健壮的底层文件 I/O。
- :class:`FileLocks`:按 key(通常是文件路径)串行化读改写临界区,支持
  多文件顺序加锁。

供 ``todo``、``memory`` 等基于本地 Markdown 文件系统的服务复用。
"""

from __future__ import annotations

from thumbelina.filestore.atomic import (
    TMP_SUFFIX,
    cleanup_tmp,
    ensure_dir,
    read_text,
    safe_unlink,
    write_text_atomic,
)
from thumbelina.filestore.locks import FileLocks

__all__ = [
    "TMP_SUFFIX",
    "FileLocks",
    "cleanup_tmp",
    "ensure_dir",
    "read_text",
    "safe_unlink",
    "write_text_atomic",
]
