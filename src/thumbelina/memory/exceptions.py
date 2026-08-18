"""记忆子系统异常体系。

``MemoryServiceError`` 为基类,所有 memory 包内抛出的业务异常均派生自此,
便于上层(API 路由/Agent)统一捕获与 503 降级。
"""

from __future__ import annotations


class MemoryServiceError(Exception):
    """记忆子系统业务异常基类。"""


class MemoryEntryNotFoundError(MemoryServiceError):
    """指定 ``category/slug`` 的记忆条目不存在。"""
