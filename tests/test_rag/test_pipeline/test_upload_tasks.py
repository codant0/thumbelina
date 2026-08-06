"""Tests for UploadTaskManager state management."""

from __future__ import annotations

import sys
import types

if "torch" not in sys.modules:
    sys.modules["torch"] = types.ModuleType("torch")

from thumbelina.rag.pipeline.indexer import ProgressEvent
from thumbelina.rag.pipeline.upload_tasks import (
    MAX_FINISHED_TASKS,
    UploadTaskManager,
)


class TestCreateAndGet:
    def test_create_returns_pending_task(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md", total_files=1)
        assert task.status == "pending"
        assert task.stage == "queued"
        assert task.kb_id == "kb1"
        assert task.kind == "file"
        assert task.label == "a.md"

    def test_get_unknown_returns_none(self):
        m = UploadTaskManager()
        assert m.get("nope") is None

    def test_list_by_kb_sorted_desc_and_filtered(self):
        m = UploadTaskManager()
        t1 = m.create("kb1", "file", "a.md")
        t2 = m.create("kb2", "file", "b.md")
        t3 = m.create("kb1", "url", "http://x")
        ids = [t.id for t in m.list_by_kb("kb1")]
        assert ids == [t3.id, t1.id]
        assert [t.id for t in m.list_by_kb("kb2")] == [t2.id]


class TestCancel:
    def test_cancel_pending_task(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        assert m.cancel(task.id) is True
        assert m.get(task.id).status == "cancelled"  # type: ignore[union-attr]
        assert task.cancel_event.is_set()

    def test_cancel_unknown_returns_false(self):
        m = UploadTaskManager()
        assert m.cancel("nope") is False

    def test_cancel_terminal_returns_false(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        m.cancel(task.id)
        assert m.cancel(task.id) is False


class TestProgress:
    def test_update_progress_fields(self):
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

    def test_update_progress_ignores_terminal(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        m.cancel(task.id)
        m.update_progress(task.id, ProgressEvent(stage="embedding", chunk_done=5))
        assert task.chunk_done == 0


class TestRetention:
    def test_finished_tasks_evicted_beyond_limit(self):
        m = UploadTaskManager()
        for i in range(MAX_FINISHED_TASKS + 5):
            t = m.create("kb1", "file", f"f{i}.md")
            m.cancel(t.id)  # 立即进入终态
        listed = m.list_by_kb("kb1")
        assert len(listed) <= MAX_FINISHED_TASKS
        # 最新的保留
        assert listed[0].label == f"f{MAX_FINISHED_TASKS + 4}.md"

    def test_active_tasks_never_evicted(self):
        m = UploadTaskManager()
        first = m.create("kb1", "file", "keep.md")  # pending（活跃）
        for i in range(MAX_FINISHED_TASKS + 5):
            t = m.create("kb1", "file", f"f{i}.md")
            m.cancel(t.id)
        assert m.get(first.id) is not None


class TestToDict:
    def test_to_dict_serializable(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")
        d = task.to_dict()
        assert d["id"] == task.id
        assert d["kb_id"] == "kb1"
        assert d["status"] == "pending"
        assert isinstance(d["created_at"], str)
        assert "cancel_event" not in d
