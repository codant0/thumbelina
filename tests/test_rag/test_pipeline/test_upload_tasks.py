"""Tests for UploadTaskManager state management."""

from __future__ import annotations

import asyncio
import sys
import types

if "torch" not in sys.modules:
    sys.modules["torch"] = types.ModuleType("torch")

from thumbelina.rag.pipeline.indexer import IndexCancelledError, ProgressEvent
from thumbelina.rag.pipeline.upload_tasks import (
    MAX_FINISHED_TASKS,
    UploadTaskManager,
)


class TestCreateAndGet:
    def test_create_returns_pending_task(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md", total_files=1)
        assert task.status == "pending"
        assert task.stage == "queued"
        assert task.kb_id == "kb1"
        assert task.kind == "file"
        assert task.label == "a.md"

    def test_get_unknown_returns_none(self) -> None:
        m = UploadTaskManager()
        assert m.get("nope") is None

    def test_list_by_kb_sorted_desc_and_filtered(self) -> None:
        m = UploadTaskManager()
        t1 = m.create("kb1", "file", "a.md")
        t2 = m.create("kb2", "file", "b.md")
        t3 = m.create("kb1", "url", "http://x")
        ids = [t.id for t in m.list_by_kb("kb1")]
        assert ids == [t3.id, t1.id]
        assert [t.id for t in m.list_by_kb("kb2")] == [t2.id]


class TestCancel:
    def test_cancel_pending_task(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        assert m.cancel(task.id) is True
        assert m.get(task.id).status == "cancelled"  # type: ignore[union-attr]
        assert task.cancel_event.is_set()

    def test_cancel_unknown_returns_false(self) -> None:
        m = UploadTaskManager()
        assert m.cancel("nope") is False

    def test_cancel_terminal_returns_false(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        m.cancel(task.id)
        assert m.cancel(task.id) is False


class TestProgress:
    def test_update_progress_fields(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "batch", "a.md", total_files=3)
        m.start_file(task.id, 1, "b.md")
        assert task.done_files == 1
        assert task.current_file == "b.md"
        m.update_progress(
            task.id,
            ProgressEvent(stage="embedding", chunk_done=10, chunk_total=40, filename="b.md"),
        )
        assert task.stage == "embedding"
        assert task.chunk_done == 10
        assert task.chunk_total == 40
        m.mark_file_done(task.id)
        assert task.done_files == 2

    def test_update_progress_ignores_terminal(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        m.cancel(task.id)
        m.update_progress(task.id, ProgressEvent(stage="embedding", chunk_done=5))
        assert task.chunk_done == 0


class TestRetention:
    def test_finished_tasks_evicted_beyond_limit(self) -> None:
        m = UploadTaskManager()
        for i in range(MAX_FINISHED_TASKS + 5):
            t = m.create("kb1", "file", f"f{i}.md")
            m.cancel(t.id)  # 立即进入终态
        listed = m.list_by_kb("kb1")
        assert len(listed) <= MAX_FINISHED_TASKS
        # 最新的保留
        assert listed[0].label == f"f{MAX_FINISHED_TASKS + 4}.md"

    def test_active_tasks_never_evicted(self) -> None:
        m = UploadTaskManager()
        first = m.create("kb1", "file", "keep.md")  # pending（活跃）
        for i in range(MAX_FINISHED_TASKS + 5):
            t = m.create("kb1", "file", f"f{i}.md")
            m.cancel(t.id)
        assert m.get(first.id) is not None


class TestToDict:
    def test_to_dict_serializable(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        d = task.to_dict()
        assert d["id"] == task.id
        assert d["kb_id"] == "kb1"
        assert d["status"] == "pending"
        assert isinstance(d["created_at"], str)
        assert "cancel_event" not in d


class TestRunLifecycle:
    """run() 异步生命周期：排队、成功、失败、取消、串行。"""

    async def test_run_success_completes(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        ran = []

        async def work() -> None:
            ran.append(1)

        await m.run(task.id, work)
        assert ran == [1]
        assert task.status == "completed"
        assert task.stage == "done"
        assert task.done_files == task.total_files

    async def test_run_exception_fails_with_message(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")

        async def work() -> None:
            raise RuntimeError("boom")

        await m.run(task.id, work)
        assert task.status == "failed"
        assert task.error == "boom"
        assert task.stage == "done"

    async def test_run_index_cancelled_marks_cancelled(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")

        async def work() -> None:
            raise IndexCancelledError

        await m.run(task.id, work)
        assert task.status == "cancelled"
        assert task.stage == "done"

    async def test_cancel_before_semaphore_marks_cancelled(self) -> None:
        m = UploadTaskManager()
        blocker = m.create("kb1", "file", "blocker.md")
        queued = m.create("kb1", "file", "queued.md")
        release = asyncio.Event()

        async def blocking_work() -> None:
            await release.wait()

        async def queued_work() -> None:
            raise AssertionError("不应执行")

        task1 = asyncio.create_task(m.run(blocker.id, blocking_work))
        await asyncio.sleep(0.01)  # 让 blocker 拿到信号量
        task2 = asyncio.create_task(m.run(queued.id, queued_work))
        await asyncio.sleep(0.01)  # queued 开始排队
        assert m.cancel(queued.id) is True
        release.set()
        await task1
        await task2
        assert blocker.status == "completed"
        assert queued.status == "cancelled"

    async def test_semaphore_serializes_tasks(self) -> None:
        m = UploadTaskManager()
        t1 = m.create("kb1", "file", "1.md")
        t2 = m.create("kb1", "file", "2.md")
        order: list[str] = []

        async def work(name: str) -> None:
            order.append(f"{name}-start")
            await asyncio.sleep(0.02)
            order.append(f"{name}-end")

        a1 = asyncio.create_task(m.run(t1.id, lambda: work("a")))
        a2 = asyncio.create_task(m.run(t2.id, lambda: work("b")))
        await asyncio.gather(a1, a2)
        assert order == ["a-start", "a-end", "b-start", "b-end"]

    async def test_run_unknown_id_noop(self) -> None:
        m = UploadTaskManager()
        ran = []

        async def work() -> None:
            ran.append(1)

        await m.run("nope", work)
        assert ran == []

    async def test_double_run_executes_once(self) -> None:
        """同一 id 并发两次 run()，工作协程只应执行一次。"""
        m = UploadTaskManager(max_concurrent=1)
        blocker = m.create("kb1", "file", "blocker.md")
        task = m.create("kb1", "file", "a.md")
        release = asyncio.Event()
        ran = []

        async def blocking_work() -> None:
            await release.wait()

        async def work() -> None:
            ran.append(1)

        b = asyncio.create_task(m.run(blocker.id, blocking_work))
        await asyncio.sleep(0.01)  # blocker 拿到信号量
        r1 = asyncio.create_task(m.run(task.id, work))
        r2 = asyncio.create_task(m.run(task.id, work))
        await asyncio.sleep(0.01)  # 两次 run 都在排队
        release.set()
        await asyncio.gather(b, r1, r2)
        assert ran == [1]
        assert task.status == "completed"

    def test_remove_cancels_removed_task(self) -> None:
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        assert m.remove(task.id) is True
        assert task.cancel_event.is_set()
        assert m.remove(task.id) is False
