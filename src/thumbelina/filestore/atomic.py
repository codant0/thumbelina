"""原子的、加锁前的底层文件操作。

``write_text_atomic`` 采用"临时文件 + ``fsync``(best-effort) +
``os.replace``"范式:写入要么整体成功、要么整体失败,崩溃/失败时
不会留下半截文件。所有 I/O 都在 ``asyncio.to_thread`` 外以同步函数
形式提供,由调用方(业务服务)决定是否用公共锁表 :class:`FileLocks`
串行化读改写周期。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TMP_SUFFIX = ".tmp"


def ensure_dir(path: Path) -> None:
    """创建目录(及父级),已存在则忽略。"""
    path.mkdir(parents=True, exist_ok=True)


def write_text_atomic(path: Path, text: str) -> None:
    """把 ``text`` 原子地写入 ``path``。

    先写同目录下的临时文件,``flush`` 并 best-effort ``fsync`` 后
    ``os.replace`` 到目标路径;任何异常都会清理临时文件再抛出,保证
    目标路径要么是旧内容、要么是新内容,绝无半截状态。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + TMP_SUFFIX)
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                # fsync best-effort:Windows/网络盘可能不支持。
                logger.debug("fsync 跳过: %s (%s)", path, exc)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def read_text(path: Path) -> str:
    """读取 ``path`` 全文;文件缺失或读取失败时返回空字符串。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("读取文件失败: %s (%s)", path, exc)
        return ""


def safe_unlink(path: Path) -> None:
    """删除文件,不存在时静默(idempotent)。"""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("删除文件失败: %s (%s)", path, exc)


def cleanup_tmp(base: Path) -> None:
    """递归清理 ``base`` 下所有 ``*.tmp`` 残留。"""
    if not base.is_dir():
        return
    for p in base.rglob(f"*{TMP_SUFFIX}"):
        try:
            p.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("清理残留 .tmp 失败: %s (%s)", p, exc)
