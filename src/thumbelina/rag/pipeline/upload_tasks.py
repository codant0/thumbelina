"""RAG 上传任务管理（纯内存）。

上传请求创建任务后立即返回 task_id；后台协程经信号量排队后执行
索引流水线，进度通过 ``update_progress`` 更新，客户端轮询 API 读取。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from thumbelina.rag.pipeline.indexer import IndexCancelledError, ProgressEvent

logger = logging.getLogger(__name__)

#: 终态任务的最大保留条数（超出按完成时间 FIFO 淘汰）。
MAX_FINISHED_TASKS = 50

TERMINAL_STATUSES = ("completed", "failed", "cancelled")


@dataclass
class UploadTask:
    """单个上传任务的状态快照。"""

    id: str
    kb_id: str
    kind: str  # "file" | "url" | "batch"
    label: str  # 展示名：文件名或 URL
    status: str = "pending"  # pending|running|completed|failed|cancelled
    stage: str = "queued"  # queued|loading|chunking|embedding|storing|done
    total_files: int = 1
    done_files: int = 0
    current_file: str = ""
    chunk_done: int = 0
    chunk_total: int = 0
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kb_id": self.kb_id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "stage": self.stage,
            "total_files": self.total_files,
            "done_files": self.done_files,
            "current_file": self.current_file,
            "chunk_done": self.chunk_done,
            "chunk_total": self.chunk_total,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
        }


class UploadTaskManager:
    """进程内上传任务注册表与生命周期管理。"""

    def __init__(self, max_concurrent: int = 1) -> None:
        self._tasks: dict[str, UploadTask] = {}
        self._lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    # -- 注册与查询 ------------------------------------------------

    def create(self, kb_id: str, kind: str, label: str, total_files: int = 1) -> UploadTask:
        task = UploadTask(
            id=uuid.uuid4().hex,
            kb_id=kb_id,
            kind=kind,
            label=label,
            total_files=total_files,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._evict_finished()
        return task

    def get(self, task_id: str) -> UploadTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_by_kb(self, kb_id: str) -> list[UploadTask]:
        with self._lock:
            tasks = [t for t in self._tasks.values() if t.kb_id == kb_id]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def remove(self, task_id: str) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None

    def get_cancel_event(self, task_id: str) -> threading.Event | None:
        task = self.get(task_id)
        return task.cancel_event if task else None

    # -- 状态变更（工作线程 + 事件循环共用，加锁） -------------------

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return False
            task.cancel_event.set()
            if task.status == "pending":
                task.status = "cancelled"
                task.stage = "done"
                self._evict_finished()
            return True

    def start_file(self, task_id: str, index: int, filename: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return
            task.done_files = index
            task.current_file = filename
            task.chunk_done = 0
            task.chunk_total = 0

    def mark_file_done(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return
            task.done_files += 1

    def update_progress(self, task_id: str, event: ProgressEvent) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return
            task.stage = event.stage
            if event.filename:
                task.current_file = event.filename
            task.chunk_done = event.chunk_done
            task.chunk_total = event.chunk_total
            if event.total_files > 0:
                task.total_files = event.total_files

    def set_result(self, task_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.result = result

    # -- 生命周期 --------------------------------------------------

    async def run(self, task_id: str, work: Callable[[], Awaitable[None]]) -> None:
        """排队并执行任务工作协程，负责状态收尾。"""
        task = self.get(task_id)
        if task is None or task.status != "pending":
            return
        async with self._semaphore:
            if task.cancel_event.is_set():
                self._finalize(task_id, "cancelled")
                return
            self._set_status(task_id, "running")
            try:
                await work()
            except IndexCancelledError:
                self._finalize(task_id, "cancelled")
            except asyncio.CancelledError:
                self._finalize(task_id, "cancelled")
                raise
            except Exception as exc:
                logger.exception("Upload task %s failed", task_id)
                self._fail(task_id, str(exc))
            else:
                self._finalize(task_id, "completed")

    # -- 内部 ------------------------------------------------------

    def _set_status(self, task_id: str, status: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.status = status

    def _finalize(self, task_id: str, status: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return
            task.status = status
            task.stage = "done"
            if status == "completed":
                task.done_files = task.total_files

    def _fail(self, task_id: str, error: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return
            task.status = "failed"
            task.stage = "done"
            task.error = error

    def _evict_finished(self) -> None:
        finished = [t for t in self._tasks.values() if t.status in TERMINAL_STATUSES]
        if len(finished) <= MAX_FINISHED_TASKS:
            return
        finished.sort(key=lambda t: t.created_at)
        for task in finished[: len(finished) - MAX_FINISHED_TASKS]:
            self._tasks.pop(task.id, None)
