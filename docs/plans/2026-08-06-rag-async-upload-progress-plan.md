# RAG 异步上传与可视化进度 — 实现计划

> **For implementer:** Use TDD throughout. Write failing test first. Watch it fail. Then implement.

**Goal:** 将三种 RAG 上传入口（单文件/URL/批量）改为后台异步任务，前端通过轮询展示阶段+分块级进度，支持取消。

**Architecture:** 纯内存 `UploadTaskManager`（dict+锁+Semaphore(1) 串行）管理任务生命周期；上传端点返回 202+task_id；Indexer 增加进度回调与协作式取消（embedding 按 32 条分批）；前端新 hook 每 1s 轮询任务列表端点并渲染任务卡片。

**Tech Stack:** FastAPI / asyncio / pytest+pytest-asyncio(auto) / ruff+mypy(strict)；React 19 + TypeScript + Vitest + @testing-library/react。

**设计文档:** `docs/plans/2026-08-06-rag-async-upload-progress-design.md`

**约束（所有任务适用）:**
- Python 3.11，mypy strict 无错误，ruff（E,F,I,N,W,UP，行长 100）通过。
- 异步测试无需装饰器（`asyncio_mode = "auto"`）。
- 每个任务完成后立即 commit。
- 不做范围外改动（YAGNI）。

---

## Task 1: Indexer 进度事件、分批向量化与协作式取消

**Files:**
- Modify: `src/thumbelina/rag/pipeline/indexer.py`
- Test: `tests/test_rag/test_pipeline/test_indexer.py`

### Step 1: 写失败测试

在 `tests/test_rag/test_pipeline/test_indexer.py` 末尾追加：

```python
import threading

from thumbelina.rag.pipeline.indexer import (
    EMBED_BATCH_SIZE,
    IndexCancelledError,
    ProgressEvent,
)


def _make_chunks(n: int) -> list[Chunk]:
    return [_make_chunk(f"chunk {i}") for i in range(n)]


class TestProgressCallback:
    """progress_cb / cancel_event 支持。"""

    def test_progress_event_stages_and_chunk_counts(self):
        events: list[ProgressEvent] = []
        chunks = _make_chunks(70)
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(chunks),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )
        stats = indexer.index(
            "/tmp/a.md",
            progress_cb=lambda ev: events.append(ev),
        )
        assert stats.indexed_count == 70
        stages = [ev.stage for ev in events]
        assert "loading" in stages
        assert "chunking" in stages
        assert "embedding" in stages
        assert "storing" in stages
        embedding_events = [ev for ev in events if ev.stage == "embedding"]
        # 70 chunks / 每批 32 → 3 批：32, 64, 70
        assert [ev.chunk_done for ev in embedding_events] == [32, 64, 70]
        assert all(ev.chunk_total == 70 for ev in embedding_events)
        assert all(ev.filename == "test.md" for ev in embedding_events)

    def test_no_callback_behavior_unchanged(self):
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(_make_chunks(3)),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )
        stats = indexer.index("/tmp/a.md")
        assert stats.indexed_count == 3
        assert not stats.errors

    def test_cancel_event_raises(self):
        cancel = threading.Event()

        class CancellingEmbedding(FakeEmbedding):
            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                cancel.set()  # 第一批完成后取消
                return super().embed_batch(texts)

        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(_make_chunks(EMBED_BATCH_SIZE * 2)),
            embedder=CancellingEmbedding(),
            vector_store=FakeVectorStore(),
        )
        with pytest.raises(IndexCancelledError):
            indexer.index("/tmp/a.md", cancel_event=cancel)

    def test_index_batch_reports_file_progress(self):
        events: list[ProgressEvent] = []
        indexer = Indexer(
            loader=FakeLoader([_make_document()]),
            chunker=FakeChunker(_make_chunks(2)),
            embedder=FakeEmbedding(),
            vector_store=FakeVectorStore(),
        )
        indexer.index_batch(
            ["/tmp/a.md", "/tmp/b.md"],
            progress_cb=lambda ev: events.append(ev),
        )
        loading_events = [ev for ev in events if ev.stage == "loading"]
        assert [ev.file_index for ev in loading_events] == [0, 1]
        assert all(ev.total_files == 2 for ev in loading_events)
```

（文件顶部已有 `import threading` 以外的必要导入；`pytest` 需确认已导入，若无则在顶部 import 区加入 `import pytest`。）

### Step 2: 运行测试 — 确认失败

```bash
pytest tests/test_rag/test_pipeline/test_indexer.py -k "TestProgressCallback" -x -q
```

预期：FAIL（`ImportError: cannot import name 'ProgressEvent'`）。

### Step 3: 实现

修改 `src/thumbelina/rag/pipeline/indexer.py`：

1. 顶部 import 追加：

```python
import threading
from collections.abc import Callable
```

2. 模块级常量与异常（放在 `IndexStats` 之前）：

```python
#: 向量化分批大小。分批执行使长文档可以向客户端报告细粒度进度，
#: 并支持批间协作式取消。
EMBED_BATCH_SIZE = 32


class IndexCancelledError(Exception):
    """索引任务被外部取消时抛出。"""


@dataclass
class ProgressEvent:
    """索引流水线进度事件。

    stage 取值: "loading" | "chunking" | "embedding" | "storing"。
    """

    stage: str
    file_index: int = 0
    total_files: int = 1
    chunk_done: int = 0
    chunk_total: int = 0
    filename: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise IndexCancelledError()
```

3. `index()` 签名改为：

```python
def index(
    self,
    path: str,
    *,
    progress_cb: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> IndexStats:
```

方法体改动（保持原语义，插入事件发射）：

```python
    stats = IndexStats()
    logger.info(f"index path: {path}")

    _check_cancel(cancel_event)

    def _emit(stage: str, **kwargs: object) -> None:
        if progress_cb is None:
            return
        progress_cb(
            ProgressEvent(
                stage=stage,
                file_index=int(kwargs.get("file_index", 0)),
                total_files=int(kwargs.get("total_files", 1)),
                chunk_done=int(kwargs.get("chunk_done", 0)),
                chunk_total=int(kwargs.get("chunk_total", 0)),
                filename=str(kwargs.get("filename", path)),
            )
        )

    # 1. 加载
    _emit("loading")
    documents = self._load(path, stats)
    if not documents:
        return stats
    stats.documents = documents

    # 2. 去重 -> 分块 → 3. 向量化 → 4. 写入
    for document in documents:
        # （原有文档级去重代码不变）
        ...
        _emit("chunking", filename=document.name)
        chunks = self._chunk(document, stats)
        if not chunks:
            continue
        self._embed_and_store(
            chunks,
            stats,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            emit=_emit,
            filename=document.name,
        )

    logger.info(f"file index result: {stats}")
    return stats
```

注意：`file_index` / `total_files` 由 `_emit` 的 kwargs 传入；`index()` 单文件默认 0/1。
原去重分支中的 `return stats` 保持不变。

4. `index_batch()` 签名改为：

```python
def index_batch(
    self,
    paths: list[str],
    *,
    progress_cb: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> IndexStats:
    total = IndexStats()
    total_files = len(paths)
    for file_index, path in enumerate(paths):
        if progress_cb is not None:
            wrapped = _FileProgressWrapper(progress_cb, file_index, total_files)
            result = self.index(
                path, progress_cb=wrapped.emit, cancel_event=cancel_event
            )
        else:
            result = self.index(path, cancel_event=cancel_event)
        total.documents.extend(result.documents)
        total.document_count += result.document_count
        total.chunk_count += result.chunk_count
        total.indexed_count += result.indexed_count
        total.skipped_count += result.skipped_count
        total.errors.extend(result.errors)
    return total
```

并新增辅助类（模块级，`Indexer` 之前或之后均可）：

```python
class _FileProgressWrapper:
    """将 index() 的进度事件重映射为批量上下文中的文件序号。"""

    def __init__(
        self, cb: ProgressCallback, file_index: int, total_files: int
    ) -> None:
        self._cb = cb
        self._file_index = file_index
        self._total_files = total_files

    def emit(self, event: ProgressEvent) -> None:
        self._cb(
            ProgressEvent(
                stage=event.stage,
                file_index=self._file_index,
                total_files=self._total_files,
                chunk_done=event.chunk_done,
                chunk_total=event.chunk_total,
                filename=event.filename,
            )
        )
```

5. `_embed_and_store()` 重写为分批执行：

```python
def _embed_and_store(
    self,
    chunks: list[Chunk],
    stats: IndexStats,
    *,
    progress_cb: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    emit: Callable[..., None] | None = None,
    filename: str = "",
) -> None:
    """步骤 3 + 4：分批向量化并写入向量库，支持进度回调与取消。"""

    # 分块级去重（替换策略：删除旧的，全量写入新的）
    if self.chunk_dedup and chunks:
        chunks, dedup_stats = self.chunk_dedup.deduplicate(
            chunks, chunks[0].knowledge_base_id
        )
        if dedup_stats.removed_old_ids:
            self.vector_store.delete(list(dedup_stats.removed_old_ids))
            logger.info(
                "分块去重: 删除 %d 个旧 chunk, 保留 %d 个新 chunk",
                len(dedup_stats.removed_old_ids),
                len(chunks),
            )

    if not chunks:
        return

    chunk_total = len(chunks)
    chunk_done = 0
    added_ids: list[str] = []

    for start in range(0, chunk_total, EMBED_BATCH_SIZE):
        _check_cancel(cancel_event)
        batch_chunks = chunks[start : start + EMBED_BATCH_SIZE]
        batch_texts = [c.content for c in batch_chunks]

        try:
            embeddings = self.embedder.embed_batch(batch_texts)
        except Exception as exc:
            self._rollback_added(added_ids)
            msg = f"向量化失败: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        try:
            self.vector_store.add(batch_chunks, embeddings)
        except Exception as exc:
            self._rollback_added(added_ids)
            msg = f"写入向量库失败: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        added_ids.extend(c.id for c in batch_chunks)
        chunk_done += len(batch_chunks)
        if emit is not None:
            emit(
                "embedding",
                chunk_done=chunk_done,
                chunk_total=chunk_total,
                filename=filename,
            )

    if emit is not None:
        emit("storing", chunk_done=chunk_done, chunk_total=chunk_total, filename=filename)

    # 注册已入库 chunk 的指纹
    if self.chunk_dedup:
        try:
            self.chunk_dedup.register_chunks(chunks)
        except Exception:
            logger.warning(
                "指纹注册失败，去重索引可能不一致。如需修复，请删除相关文档后重新上传。",
                exc_info=True,
            )

    stats.indexed_count += len(chunks)

def _rollback_added(self, added_ids: list[str]) -> None:
    """批处理中途失败时回滚已写入的分块，保持单文件全有或全无。"""
    if not added_ids:
        return
    try:
        self.vector_store.delete(added_ids)
    except Exception:
        logger.warning("回滚已写入分块失败: %s", added_ids, exc_info=True)
```

（原 `_embed_and_store` 中 `texts = [c.content for c in chunks]` 及单次调用逻辑整体替换。）

### Step 4: 运行测试 — 确认通过

```bash
pytest tests/test_rag/test_pipeline/test_indexer.py -x -q
```

预期：全部 PASS（包括既有测试）。

### Step 5: Commit

```bash
git add src/thumbelina/rag/pipeline/indexer.py tests/test_rag/test_pipeline/test_indexer.py
git commit -m "feat(rag): indexer progress events, batched embedding, cancellation"
```

---

## Task 2: UploadTaskManager 核心状态管理

**Files:**
- Create: `src/thumbelina/rag/pipeline/upload_tasks.py`
- Test: `tests/test_rag/test_pipeline/test_upload_tasks.py`

### Step 1: 写失败测试

创建 `tests/test_rag/test_pipeline/test_upload_tasks.py`：

```python
"""Tests for UploadTaskManager state management."""

from __future__ import annotations

import sys
import types

if "torch" not in sys.modules:
    sys.modules["torch"] = types.ModuleType("torch")

from thumbelina.rag.pipeline.indexer import ProgressEvent
from thumbelina.rag.pipeline.upload_tasks import (
    MAX_FINISHED_TASKS,
    UploadTask,
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
            ProgressEvent(
                stage="embedding", chunk_done=10, chunk_total=40, filename="b.md"
            ),
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
```

### Step 2: 运行测试 — 确认失败

```bash
pytest tests/test_rag/test_pipeline/test_upload_tasks.py -x -q
```

预期：FAIL（`ModuleNotFoundError: thumbelina.rag.pipeline.upload_tasks`）。

### Step 3: 实现

创建 `src/thumbelina/rag/pipeline/upload_tasks.py`：

```python
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
from datetime import datetime, timezone
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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
            id=uuid.uuid4().hex, kb_id=kb_id, kind=kind, label=label,
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
        finished = [
            t for t in self._tasks.values() if t.status in TERMINAL_STATUSES
        ]
        if len(finished) <= MAX_FINISHED_TASKS:
            return
        finished.sort(key=lambda t: t.created_at)
        for task in finished[: len(finished) - MAX_FINISHED_TASKS]:
            self._tasks.pop(task.id, None)
```

### Step 4: 运行测试 — 确认通过

```bash
pytest tests/test_rag/test_pipeline/test_upload_tasks.py -x -q
```

预期：全部 PASS。

### Step 5: Commit

```bash
git add src/thumbelina/rag/pipeline/upload_tasks.py tests/test_rag/test_pipeline/test_upload_tasks.py
git commit -m "feat(rag): in-memory UploadTaskManager with retention and cancel"
```

---

## Task 3: UploadTaskManager.run 异步生命周期测试

**Files:**
- Test: `tests/test_rag/test_pipeline/test_upload_tasks.py`

（`run()` 已在 Task 2 实现；本任务补齐异步行为测试：排队、成功、失败、运行中取消。）

### Step 1: 写失败/补齐测试

在同一文件追加：

```python
import asyncio

import pytest

from thumbelina.rag.pipeline.indexer import IndexCancelledError


class TestRunLifecycle:
    async def test_run_success_completes(self):
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

    async def test_run_exception_fails_with_message(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")

        async def work() -> None:
            raise RuntimeError("boom")

        await m.run(task.id, work)
        assert task.status == "failed"
        assert task.error == "boom"

    async def test_run_index_cancelled_marks_cancelled(self):
        m = UploadTaskManager()
        task = m.create("kb1", "file", "a.md")

        async def work() -> None:
            raise IndexCancelledError

        await m.run(task.id, work)
        assert task.status == "cancelled"

    async def test_cancel_before_semaphore_marks_cancelled(self):
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

    async def test_semaphore_serializes_tasks(self):
        m = UploadTaskManager()
        t1 = m.create("kb1", "file", "1.md")
        t2 = m.create("kb1", "file", "2.md")
        running: list[str] = []

        async def make_work(name: str):
            async def work() -> None:
                running.append(f"{name}-start")
                await asyncio.sleep(0.02)
                running.append(f"{name}-end")
            return work

        a1 = asyncio.create_task(m.run(t1.id, await make_work("a")))
        a2 = asyncio.create_task(m.run(t2.id, await make_work("b")))
        await asyncio.gather(a1, a2)
        assert running == ["a-start", "a-end", "b-start", "b-end"]
```

### Step 2: 运行测试 — 确认通过

```bash
pytest tests/test_rag/test_pipeline/test_upload_tasks.py -x -q
```

预期：全部 PASS（若失败，修复 `run()` 实现而非改测试）。

### Step 3: Commit

```bash
git add tests/test_rag/test_pipeline/test_upload_tasks.py
git commit -m "test(rag): UploadTaskManager async lifecycle (queue, cancel, failure)"
```

---

## Task 4: API — 任务端点 + 单文件上传异步化

**Files:**
- Modify: `src/thumbelina/api/routes/rag.py`
- Modify: `src/thumbelina/api/app.py`
- Test: `tests/test_api/test_rag.py`

### Step 1: 写失败测试

修改 `tests/test_api/test_rag.py`：

1. `rag_client` fixture 末尾（`return client` 之前）追加：

```python
    from thumbelina.rag.pipeline.upload_tasks import UploadTaskManager

    app.state.rag_upload_tasks = UploadTaskManager()
```

2. `mock_rag_pipeline` fixture 中补上对 `index` 的默认 mock（保留原 `index_batch` 行）：

```python
    mock_indexer_cls.return_value.index.return_value = mock_stats
```

3. 在文件末尾的 Helpers 区新增轮询助手（放在 `_install_mock_module` 附近）：

```python
import time


def _wait_task_done(client, task_id: str, timeout: float = 5.0) -> dict:
    """轮询任务状态直至终态。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/rag/upload-tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s")
```

4. 替换/新增测试类（`TestDocumentManagement` 中 `test_upload_document` 改为如下，其余保留）：

```python
class TestAsyncUpload:
    def test_upload_returns_202_and_task_id(self, rag_client, mock_rag_pipeline):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.md", b"# Test\nHello", "text/markdown")},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data

        task = _wait_task_done(rag_client, data["task_id"])
        assert task["status"] == "completed"
        assert task["kind"] == "file"
        assert task["label"] == "test.md"
        assert task["result"]["uploaded"][0]["name"] == "test.md"

    def test_upload_indexes_document_record(self, rag_client, mock_rag_pipeline):
        import uuid

        mock_stats = MagicMock()
        mock_stats.indexed_count = 3
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "test.md"
        fake_doc.source_uri = "/tmp/test.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.md", b"# Test", "text/markdown")},
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"

        docs = rag_client.get("/api/v1/rag/knowledge-bases/0/documents").json()
        assert len(docs) == 1
        assert docs[0]["chunk_count"] == 3

    def test_upload_unsupported_type_returns_400(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("test.docx", b"PK fake", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_failure_marks_task_failed(self, rag_client, mock_rag_pipeline):
        import uuid

        mock_stats = MagicMock()
        mock_stats.indexed_count = 0
        mock_stats.errors = ["加载失败: 文件损坏"]
        mock_stats.documents = []
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("bad.md", b"x", "text/markdown")},
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "failed"
        assert "加载失败" in task["error"]

    def test_upload_to_missing_kb_returns_404(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/no-such/documents",
            files={"file": ("a.md", b"x", "text/markdown")},
        )
        assert resp.status_code == 404


class TestUploadTaskEndpoints:
    def test_get_unknown_task_returns_404(self, rag_client):
        resp = rag_client.get("/api/v1/rag/upload-tasks/nope")
        assert resp.status_code == 404

    def test_list_tasks_by_kb(self, rag_client, mock_rag_pipeline):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("a.md", b"x", "text/markdown")},
        )
        task_id = resp.json()["task_id"]
        _wait_task_done(rag_client, task_id)
        listing = rag_client.get("/api/v1/rag/knowledge-bases/0/upload-tasks").json()
        assert any(t["id"] == task_id for t in listing)

    def test_cancel_terminal_task_removes_it(self, rag_client, mock_rag_pipeline):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents",
            files={"file": ("a.md", b"x", "text/markdown")},
        )
        task_id = resp.json()["task_id"]
        _wait_task_done(rag_client, task_id)
        del_resp = rag_client.delete(f"/api/v1/rag/upload-tasks/{task_id}")
        assert del_resp.status_code == 200
        assert rag_client.get(f"/api/v1/rag/upload-tasks/{task_id}").status_code == 404

    def test_cancel_unknown_task_returns_404(self, rag_client):
        resp = rag_client.delete("/api/v1/rag/upload-tasks/nope")
        assert resp.status_code == 404
```

同时更新旧测试：
- `TestDocumentManagement.test_upload_document` 整个由 `TestAsyncUpload.test_upload_indexes_document_record` 取代，删除原测试；
- `test_delete_document` / `TestDocumentChunks` 中所有先上传再操作的测试：上传后改为
  `task = _wait_task_done(rag_client, upload_resp.json()["task_id"])`，
  `doc_id = task["result"]["uploaded"][0]["id"]`（替换原 `upload_resp.json()["id"]`），
  并给 `mock_rag_pipeline.return_value.index.return_value` 赋值（替代原 `index_batch` 赋值）。

### Step 2: 运行测试 — 确认失败

```bash
pytest tests/test_api/test_rag.py -x -q
```

预期：FAIL（405/404/断言失败，端点尚未改造）。

### Step 3: 实现

**3a. `src/thumbelina/api/app.py`** — RAG 初始化块内（`app.state.rag_embedding_registry = ...` 附近）追加：

```python
        from thumbelina.rag.pipeline.upload_tasks import UploadTaskManager

        app.state.rag_upload_tasks = UploadTaskManager()
```

**3b. `src/thumbelina/api/routes/rag.py`** 改造要点：

1. imports 追加：

```python
from typing import Any

from thumbelina.rag.pipeline.indexer import IndexCancelledError, Indexer
from thumbelina.rag.pipeline.upload_tasks import (
    TERMINAL_STATUSES,
    UploadTaskManager,
)
```

（删除原 `from thumbelina.rag.pipeline.indexer import Indexer` 旧行，避免重复。）

2. schemas 追加：

```python
class CreateUploadTaskResponse(BaseModel):
    task_id: str


class UploadTaskResponse(BaseModel):
    id: str
    kb_id: str
    kind: str
    label: str
    status: str
    stage: str
    total_files: int
    done_files: int
    current_file: str
    chunk_done: int
    chunk_total: int
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: str
```

3. helpers 追加：

```python
def _get_task_manager(request: Request) -> UploadTaskManager:
    manager = getattr(request.app.state, "rag_upload_tasks", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")
    return manager


async def _save_upload_file(file: UploadFile, filename: str) -> Path:
    """流式保存上传文件到临时目录（uuid 前缀避免同名冲突）。"""
    tmp_dir = Path("/tmp_file")
    tmp_dir.mkdir(exist_ok=True)
    tmp_path = tmp_dir / f"upload_{uuid.uuid4().hex}_{Path(filename).name}"
    with open(tmp_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    return tmp_path
```

4. `_build_indexer(request, ...)` 签名改为 `_build_indexer(state: Any, kb_id: str, *, path=None, loader=None)`，方法体中 `request.app.state` 全部替换为 `state`；两处 `HTTPException(503, ...)` 改为 `RuntimeError(...)`（工作协程中不再是请求上下文）。

5. 新增文件上传工作协程（模块级）：

```python
async def _run_file_upload(
    *,
    manager: UploadTaskManager,
    task_id: str,
    kb_id: str,
    files: list[tuple[str, Path, str]],
    state: Any,
) -> None:
    """索引已落盘的上传文件并写入文档元数据。

    files: (显示名, 临时路径, doc_type) 列表。
    """
    doc_repo = _doc_repo_from_state(state)
    uploaded: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []
    try:
        for idx, (display_name, tmp_path, doc_type) in enumerate(files):
            manager.start_file(task_id, idx, display_name)
            try:
                indexer = await _build_indexer(state, kb_id, path=str(tmp_path))
                stats = await asyncio.to_thread(
                    indexer.index,
                    str(tmp_path),
                    progress_cb=lambda ev, tid=task_id: manager.update_progress(tid, ev),
                    cancel_event=manager.get_cancel_event(task_id),
                )
            except IndexCancelledError:
                raise
            except Exception as exc:
                errors.append({"filename": display_name, "error": str(exc)})
                continue
            if stats.errors:
                errors.append(
                    {"filename": display_name, "error": "; ".join(stats.errors)}
                )
                continue
            if not stats.documents:
                skipped.append(display_name)
                continue
            document = stats.documents[0]
            doc = await doc_repo.create(
                kb_id=kb_id,
                name=document.name,
                source_uri=document.source_uri,
                doc_type=doc_type,
                sha256=document.sha256,
                sim_hash_64=document.sim_hash_64,
                chunk_count=stats.indexed_count,
                doc_id=document.id,
            )
            uploaded.append(
                {"id": doc.id, "name": doc.name, "chunk_count": doc.chunk_count}
            )
            manager.mark_file_done(task_id)
        if not uploaded and errors:
            raise RuntimeError("; ".join(e["error"] for e in errors))
        manager.set_result(
            task_id, {"uploaded": uploaded, "skipped": skipped, "errors": errors}
        )
    finally:
        for _, tmp_path, _ in files:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _doc_repo_from_state(state: Any) -> DocumentRepository:
    repo = getattr(state, "rag_doc_repo", None)
    if repo is None:
        raise RuntimeError("RAG not initialized")
    return repo
```

6. `upload_document` 端点整体替换：

```python
@router.post(
    "/knowledge-bases/{kb_id}/documents",
    status_code=202,
    response_model=CreateUploadTaskResponse,
)
async def upload_document(
    kb_id: str, file: UploadFile, request: Request
) -> CreateUploadTaskResponse:
    """上传单个文件，创建后台索引任务并立即返回 task_id。"""
    kb_repo = _get_kb_repo(request)
    if await kb_repo.get(kb_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    from thumbelina.rag.common.models import DocumentType

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1]
    try:
        doc_type = DocumentType.from_value(ext)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    tmp_path = await _save_upload_file(file, filename)
    await file.close()

    manager = _get_task_manager(request)
    task = manager.create(kb_id, "file", filename, total_files=1)
    state = request.app.state
    asyncio.create_task(
        manager.run(
            task.id,
            lambda: _run_file_upload(
                manager=manager,
                task_id=task.id,
                kb_id=kb_id,
                files=[(filename, tmp_path, doc_type.value)],
                state=state,
            ),
        )
    )
    return CreateUploadTaskResponse(task_id=task.id)
```

7. 任务查询/取消端点（放在 Document endpoints 区之后）：

```python
@router.get("/upload-tasks/{task_id}", response_model=UploadTaskResponse)
async def get_upload_task(task_id: str, request: Request) -> UploadTaskResponse:
    manager = _get_task_manager(request)
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return UploadTaskResponse(**task.to_dict())


@router.get(
    "/knowledge-bases/{kb_id}/upload-tasks",
    response_model=list[UploadTaskResponse],
)
async def list_upload_tasks(kb_id: str, request: Request) -> list[UploadTaskResponse]:
    manager = _get_task_manager(request)
    return [UploadTaskResponse(**t.to_dict()) for t in manager.list_by_kb(kb_id)]


@router.delete("/upload-tasks/{task_id}")
async def cancel_upload_task(task_id: str, request: Request) -> dict:
    """取消活跃任务；终态任务则从列表中移除。"""
    manager = _get_task_manager(request)
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Upload task not found")
    if task.status in TERMINAL_STATUSES:
        manager.remove(task_id)
        return {"cancelled": False}
    return {"cancelled": manager.cancel(task_id)}
```

8. 批量与 URL 端点本任务暂不改（Task 5），保持现状。

### Step 4: 运行测试 — 确认通过

```bash
pytest tests/test_api/test_rag.py -x -q
```

预期：全部 PASS。若后台任务未在 TestClient 中完成，检查 `asyncio.create_task` 是否在事件循环内调用。

### Step 5: Commit

```bash
git add src/thumbelina/api/routes/rag.py src/thumbelina/api/app.py tests/test_api/test_rag.py
git commit -m "feat(api): async single-file RAG upload with task status endpoints"
```

---

## Task 5: API — 批量与 URL 上传异步化

**Files:**
- Modify: `src/thumbelina/api/routes/rag.py`
- Test: `tests/test_api/test_rag.py`

### Step 1: 写失败测试

追加到 `tests/test_api/test_rag.py`：

```python
class TestAsyncBatchAndUrlUpload:
    def test_batch_upload_returns_202_and_completes(self, rag_client, mock_rag_pipeline):
        import uuid

        mock_stats = MagicMock()
        mock_stats.indexed_count = 1
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "a.md"
        fake_doc.source_uri = "/tmp/a.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/batch",
            files=[
                ("files", ("a.md", b"aaa", "text/markdown")),
                ("files", ("b.md", b"bbb", "text/markdown")),
            ],
        )
        assert resp.status_code == 202
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert task["kind"] == "batch"
        assert task["total_files"] == 2
        assert len(task["result"]["uploaded"]) == 2

    def test_batch_unsupported_files_recorded_as_skipped(
        self, rag_client, mock_rag_pipeline
    ):
        import uuid

        mock_stats = MagicMock()
        mock_stats.indexed_count = 1
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "a.md"
        fake_doc.source_uri = "/tmp/a.md"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/batch",
            files=[
                ("files", ("a.md", b"aaa", "text/markdown")),
                ("files", ("c.docx", b"PK", "application/octet-stream")),
            ],
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert task["result"]["skipped"] == ["c.docx"]

    def test_url_upload_returns_202_and_completes(self, rag_client, mock_rag_pipeline):
        import uuid

        mock_stats = MagicMock()
        mock_stats.indexed_count = 4
        mock_stats.errors = []
        fake_doc = MagicMock()
        fake_doc.id = uuid.uuid4().hex
        fake_doc.name = "example.com"
        fake_doc.source_uri = "https://example.com/a"
        fake_doc.sha256 = b"\x00" * 32
        fake_doc.sim_hash_64 = b"\x00" * 8
        mock_stats.documents = [fake_doc]
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/url",
            json={"url": "https://example.com/a"},
        )
        assert resp.status_code == 202
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "completed"
        assert task["kind"] == "url"
        assert task["label"] == "https://example.com/a"

    def test_url_upload_invalid_scheme_returns_400(self, rag_client):
        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/url",
            json={"url": "ftp://example.com"},
        )
        assert resp.status_code == 400

    def test_url_upload_no_content_marks_failed(self, rag_client, mock_rag_pipeline):
        mock_stats = MagicMock()
        mock_stats.indexed_count = 0
        mock_stats.errors = []
        mock_stats.documents = []
        mock_rag_pipeline.return_value.index.return_value = mock_stats

        resp = rag_client.post(
            "/api/v1/rag/knowledge-bases/0/documents/url",
            json={"url": "https://example.com/empty"},
        )
        task = _wait_task_done(rag_client, resp.json()["task_id"])
        assert task["status"] == "failed"
```

### Step 2: 运行测试 — 确认失败

```bash
pytest tests/test_api/test_rag.py -k "TestAsyncBatchAndUrlUpload" -x -q
```

预期：FAIL。

### Step 3: 实现

在 `rag.py` 中：

1. URL 工作协程：

```python
async def _run_url_upload(
    *,
    manager: UploadTaskManager,
    task_id: str,
    kb_id: str,
    url: str,
    state: Any,
) -> None:
    doc_repo = _doc_repo_from_state(state)
    try:
        manager.start_file(task_id, 0, url)
        indexer = await _build_indexer(state, kb_id, path=url)
        stats = await asyncio.to_thread(
            indexer.index,
            url,
            progress_cb=lambda ev, tid=task_id: manager.update_progress(tid, ev),
            cancel_event=manager.get_cancel_event(task_id),
        )
        if stats.errors:
            raise RuntimeError("; ".join(stats.errors))
        if not stats.documents:
            raise RuntimeError("未能从 URL 提取到内容")
        document = stats.documents[0]
        doc = await doc_repo.create(
            kb_id=kb_id,
            name=document.name,
            source_uri=url,
            doc_type="html",
            sha256=document.sha256,
            sim_hash_64=document.sim_hash_64,
            chunk_count=stats.indexed_count,
            doc_id=document.id,
        )
        manager.mark_file_done(task_id)
        manager.set_result(
            task_id,
            {
                "uploaded": [
                    {"id": doc.id, "name": doc.name, "chunk_count": doc.chunk_count}
                ],
                "skipped": [],
                "errors": [],
            },
        )
    except IndexCancelledError:
        raise
```

2. `upload_document_by_url` 端点整体替换（前置校验不变）：

```python
@router.post(
    "/knowledge-bases/{kb_id}/documents/url",
    status_code=202,
    response_model=CreateUploadTaskResponse,
)
async def upload_document_by_url(
    kb_id: str, body: UrlUploadRequest, request: Request
) -> CreateUploadTaskResponse:
    """通过 URL 抓取网页内容并索引（后台任务）。"""
    kb_repo = _get_kb_repo(request)
    if await kb_repo.get(kb_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400, detail="URL 必须以 http:// 或 https:// 开头"
        )

    manager = _get_task_manager(request)
    task = manager.create(kb_id, "url", url, total_files=1)
    state = request.app.state
    asyncio.create_task(
        manager.run(
            task.id,
            lambda: _run_url_upload(
                manager=manager, task_id=task.id, kb_id=kb_id, url=url, state=state
            ),
        )
    )
    return CreateUploadTaskResponse(task_id=task.id)
```

3. `upload_documents_batch` 端点整体替换：

```python
@router.post(
    "/knowledge-bases/{kb_id}/documents/batch",
    status_code=202,
    response_model=CreateUploadTaskResponse,
)
async def upload_documents_batch(
    kb_id: str, files: list[UploadFile], request: Request
) -> CreateUploadTaskResponse:
    """批量上传多个文件（后台任务）。不支持的类型记入任务结果 skipped。"""
    kb_repo = _get_kb_repo(request)
    if await kb_repo.get(kb_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    from thumbelina.rag.common.models import DocumentType

    manager = _get_task_manager(request)
    accepted: list[tuple[str, Path, str]] = []
    skipped_names: list[str] = []
    for file in files:
        filename = file.filename or ""
        ext = os.path.splitext(filename)[1]
        try:
            doc_type = DocumentType.from_value(ext)
        except ValueError:
            skipped_names.append(filename)
            await file.close()
            continue
        tmp_path = await _save_upload_file(file, filename)
        await file.close()
        accepted.append((filename, tmp_path, doc_type.value))

    label = accepted[0][0] if accepted else (skipped_names[0] if skipped_names else "")
    task = manager.create(kb_id, "batch", label, total_files=len(accepted))
    if skipped_names:
        manager.set_result(
            task.id, {"uploaded": [], "skipped": skipped_names, "errors": []}
        )
    state = request.app.state
    asyncio.create_task(
        manager.run(
            task.id,
            lambda: _run_batch_upload(
                manager=manager,
                task_id=task.id,
                kb_id=kb_id,
                files=accepted,
                pre_skipped=skipped_names,
                state=state,
            ),
        )
    )
    return CreateUploadTaskResponse(task_id=task.id)
```

4. 批量工作协程（复用 `_run_file_upload` 逻辑并合并预先 skipped）：

```python
async def _run_batch_upload(
    *,
    manager: UploadTaskManager,
    task_id: str,
    kb_id: str,
    files: list[tuple[str, Path, str]],
    pre_skipped: list[str],
    state: Any,
) -> None:
    if not files:
        if not pre_skipped:
            raise RuntimeError("没有可上传的文件")
        return  # 结果已含 skipped，直接 completed
    # 复用单文件工作协程，最后合并 pre_skipped
    ...
```

实现方式：直接在 `_run_file_upload` 增加 `pre_skipped: list[str] | None = None` 参数，
开头 `skipped = list(pre_skipped or [])`；`_run_batch_upload` 不必单独存在——
`upload_documents_batch` 直接调用 `_run_file_upload(..., pre_skipped=skipped_names)`。
（即删除 `_run_batch_upload`，修改 `_run_file_upload` 签名。）注意：`_run_file_upload`
中 `if not uploaded and errors: raise` 的判定保持不变（全部 skipped 且无错误 → completed）。

### Step 4: 运行测试 — 确认通过

```bash
pytest tests/test_api/test_rag.py -x -q
```

预期：全部 PASS。

### Step 5: Commit

```bash
git add src/thumbelina/api/routes/rag.py tests/test_api/test_rag.py
git commit -m "feat(api): async batch and URL RAG uploads via task system"
```

---

## Task 6: 前端 API 客户端与类型

**Files:**
- Modify: `frontend/src/types/rag.ts`
- Modify: `frontend/src/api/rag.ts`
- Test: `frontend/src/api/rag.test.ts`（新建）

### Step 1: 写失败测试

创建 `frontend/src/api/rag.test.ts`：

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  uploadFilesAsync,
  uploadUrlAsync,
  listUploadTasks,
  cancelUploadTask,
} from './rag'

function mockJson(data: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(data), { status }),
  )
}

describe('rag upload task api', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uploadFilesAsync posts single file to /documents', async () => {
    const spy = mockJson({ task_id: 't1' }, 202)
    const id = await uploadFilesAsync('kb1', [new File(['x'], 'a.md')])
    expect(id).toBe('t1')
    expect(spy.mock.calls[0][0]).toContain('/knowledge-bases/kb1/documents')
  })

  it('uploadFilesAsync posts multiple files to /documents/batch', async () => {
    const spy = mockJson({ task_id: 't2' }, 202)
    await uploadFilesAsync('kb1', [new File(['x'], 'a.md'), new File(['y'], 'b.md')])
    expect(spy.mock.calls[0][0]).toContain('/documents/batch')
  })

  it('uploadUrlAsync posts url', async () => {
    const spy = mockJson({ task_id: 't3' }, 202)
    await uploadUrlAsync('kb1', 'https://example.com')
    expect(spy.mock.calls[0][0]).toContain('/documents/url')
  })

  it('listUploadTasks returns tasks', async () => {
    mockJson([{ id: 't1', status: 'running' }])
    const tasks = await listUploadTasks('kb1')
    expect(tasks).toHaveLength(1)
    expect(tasks[0].id).toBe('t1')
  })

  it('cancelUploadTask calls DELETE', async () => {
    const spy = mockJson({ cancelled: true })
    await cancelUploadTask('t1')
    const init = spy.mock.calls[0][1]
    expect(init?.method).toBe('DELETE')
  })

  it('uploadFilesAsync throws on error detail', async () => {
    mockJson({ detail: 'Unsupported file type' }, 400)
    await expect(
      uploadFilesAsync('kb1', [new File(['x'], 'a.exe')]),
    ).rejects.toThrow('Unsupported file type')
  })
})
```

### Step 2: 运行测试 — 确认失败

```bash
cd frontend && npm run test -- rag.test.ts
```

预期：FAIL（函数不存在）。

### Step 3: 实现

`frontend/src/types/rag.ts` 追加：

```ts
export type UploadTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type UploadTaskKind = 'file' | 'url' | 'batch'

export interface UploadTask {
  id: string
  kb_id: string
  kind: UploadTaskKind
  label: string
  status: UploadTaskStatus
  stage: string
  total_files: number
  done_files: number
  current_file: string
  chunk_done: number
  chunk_total: number
  error?: string | null
  result?: {
    uploaded: Array<{ id: string; name: string; chunk_count: number }>
    skipped: string[]
    errors: Array<{ filename: string; error: string }>
  } | null
  created_at: string
}
```

`frontend/src/api/rag.ts`：删除 `uploadDocument`、`uploadDocumentByUrl`、`uploadDocumentsBatch`，替换为：

```ts
import type { UploadTask } from '../types/rag'

export async function uploadFilesAsync(kbId: string, files: File[]): Promise<string> {
  const formData = new FormData()
  let path: string
  if (files.length === 1) {
    formData.append('file', files[0])
    path = `${API_BASE}/knowledge-bases/${kbId}/documents`
  } else {
    for (const file of files) formData.append('files', file)
    path = `${API_BASE}/knowledge-bases/${kbId}/documents/batch`
  }
  const res = await fetch(path, { method: 'POST', body: formData })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return data.task_id as string
}

export async function uploadUrlAsync(kbId: string, url: string): Promise<string> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents/url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return data.task_id as string
}

export async function listUploadTasks(kbId: string): Promise<UploadTask[]> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/upload-tasks`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<UploadTask[]>
}

export async function cancelUploadTask(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/upload-tasks/${taskId}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
}
```

### Step 4: 运行测试 — 确认通过

```bash
cd frontend && npm run test -- rag.test.ts
```

预期：PASS。

### Step 5: Commit

```bash
git add frontend/src/types/rag.ts frontend/src/api/rag.ts frontend/src/api/rag.test.ts
git commit -m "feat(frontend): async upload task API client"
```

---

## Task 7: useUploadTasks 轮询 hook

**Files:**
- Create: `frontend/src/hooks/useUploadTasks.ts`
- Test: `frontend/src/hooks/useUploadTasks.test.ts`

### Step 1: 写失败测试

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useUploadTasks } from './useUploadTasks'

let fetchMock: ReturnType<typeof vi.fn>

function respond(tasks: unknown[]) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(tasks), { status: 200 }),
  )
}

describe('useUploadTasks', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('loads tasks on mount', async () => {
    respond([{ id: 't1', status: 'completed' }])
    const { result } = renderHook(() => useUploadTasks('kb1'))
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('polls while active tasks exist and stops after settle', async () => {
    respond([{ id: 't1', status: 'running' }])
    const onSettled = vi.fn()
    const { result } = renderHook(() => useUploadTasks('kb1', onSettled))
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))

    respond([{ id: 't1', status: 'running' }])
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    respond([{ id: 't1', status: 'completed' }])
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1))

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(fetchMock).toHaveBeenCalledTimes(3) // 不再轮询
  })

  it('cancel calls DELETE and refreshes', async () => {
    respond([{ id: 't1', status: 'running' }])
    const { result } = renderHook(() => useUploadTasks('kb1'))
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))

    fetchMock.mockResolvedValueOnce(new Response('{"cancelled": true}', { status: 200 }))
    respond([])
    await act(async () => { await result.current.cancel('t1') })
    expect(fetchMock.mock.calls[1][1]?.method).toBe('DELETE')
  })

  it('dismissed terminal tasks stay hidden after refresh', async () => {
    respond([
      { id: 't1', status: 'completed' },
      { id: 't2', status: 'running' },
    ])
    const { result } = renderHook(() => useUploadTasks('kb1'))
    await waitFor(() => expect(result.current.tasks).toHaveLength(2))

    act(() => result.current.dismiss('t1'))
    expect(result.current.tasks).toHaveLength(1)

    respond([
      { id: 't1', status: 'completed' },
      { id: 't2', status: 'completed' },
    ])
    await act(async () => { await result.current.refresh() })
    expect(result.current.tasks.map(t => t.id)).toEqual(['t2'])
  })

  it('resets when kbId changes', async () => {
    respond([{ id: 't1', status: 'completed' }])
    const { result, rerender } = renderHook(
      ({ kb }: { kb: string | null }) => useUploadTasks(kb),
      { initialProps: { kb: 'kb1' as string | null } },
    )
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))
    rerender({ kb: null })
    expect(result.current.tasks).toHaveLength(0)
  })
})
```

### Step 2: 运行测试 — 确认失败

```bash
cd frontend && npm run test -- useUploadTasks
```

预期：FAIL（模块不存在）。

### Step 3: 实现

创建 `frontend/src/hooks/useUploadTasks.ts`：

```ts
import { useCallback, useEffect, useRef, useState } from 'react'
import type { UploadTask } from '../types/rag'
import * as ragApi from '../api/rag'

const POLL_INTERVAL_MS = 1000

function isActive(t: UploadTask): boolean {
  return t.status === 'pending' || t.status === 'running'
}

export function useUploadTasks(kbId: string | null, onSettled?: () => void) {
  const [tasks, setTasks] = useState<UploadTask[]>([])
  const prevActiveRef = useRef<Set<string>>(new Set())
  const dismissedRef = useRef<Set<string>>(new Set())
  const onSettledRef = useRef(onSettled)

  useEffect(() => {
    onSettledRef.current = onSettled
  }, [onSettled])

  const refresh = useCallback(async () => {
    if (!kbId) return
    try {
      const list = await ragApi.listUploadTasks(kbId)
      const visible = list.filter(t => !dismissedRef.current.has(t.id))
      const activeIds = new Set(visible.filter(isActive).map(t => t.id))
      const settledNow = [...prevActiveRef.current].filter(id => !activeIds.has(id))
      prevActiveRef.current = activeIds
      setTasks(visible)
      if (settledNow.length > 0) onSettledRef.current?.()
    } catch {
      // 轮询的瞬时错误忽略，下一轮重试
    }
  }, [kbId])

  useEffect(() => {
    if (!kbId) {
      setTasks([])
      prevActiveRef.current = new Set()
      dismissedRef.current = new Set()
      return
    }
    void refresh()
  }, [kbId, refresh])

  const hasActive = tasks.some(isActive)

  useEffect(() => {
    if (!kbId || !hasActive) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [kbId, hasActive, refresh])

  const submitFiles = useCallback(
    async (files: File[]) => {
      if (!kbId) return
      await ragApi.uploadFilesAsync(kbId, files)
      await refresh()
    },
    [kbId, refresh],
  )

  const submitUrl = useCallback(
    async (url: string) => {
      if (!kbId) return
      await ragApi.uploadUrlAsync(kbId, url)
      await refresh()
    },
    [kbId, refresh],
  )

  const cancel = useCallback(
    async (taskId: string) => {
      await ragApi.cancelUploadTask(taskId)
      await refresh()
    },
    [refresh],
  )

  const dismiss = useCallback((taskId: string) => {
    dismissedRef.current.add(taskId)
    setTasks(prev => prev.filter(t => t.id !== taskId))
  }, [])

  return { tasks, hasActive, submitFiles, submitUrl, cancel, dismiss, refresh }
}
```

### Step 4: 运行测试 — 确认通过

```bash
cd frontend && npm run test -- useUploadTasks
```

预期：PASS。

### Step 5: Commit

```bash
git add frontend/src/hooks/useUploadTasks.ts frontend/src/hooks/useUploadTasks.test.ts
git commit -m "feat(frontend): useUploadTasks polling hook"
```

---

## Task 8: UploadTaskList 任务卡片组件

**Files:**
- Create: `frontend/src/components/KnowledgeBase/UploadTaskList.tsx`
- Test: `frontend/src/components/KnowledgeBase/UploadTaskList.test.tsx`

### Step 1: 写失败测试

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { UploadTaskList } from './UploadTaskList'
import type { UploadTask } from '../../types/rag'

function makeTask(overrides: Partial<UploadTask>): UploadTask {
  return {
    id: 't1', kb_id: 'kb1', kind: 'file', label: 'a.md',
    status: 'running', stage: 'embedding',
    total_files: 1, done_files: 0, current_file: 'a.md',
    chunk_done: 48, chunk_total: 320, error: null, result: null,
    created_at: '2026-08-06T12:00:00Z',
    ...overrides,
  }
}

describe('UploadTaskList', () => {
  it('renders nothing when empty', () => {
    const { container } = render(
      <UploadTaskList tasks={[]} onCancel={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows progress for running task', () => {
    render(
      <UploadTaskList tasks={[makeTask({})]} onCancel={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(screen.getByText('a.md')).toBeInTheDocument()
    expect(screen.getByText('uploadTask.statusRunning')).toBeInTheDocument()
    expect(screen.getByText(/48\/320/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
  })

  it('shows batch label with file count', () => {
    render(
      <UploadTaskList
        tasks={[makeTask({ kind: 'batch', total_files: 12, done_files: 4, stage: 'loading', chunk_done: 0, chunk_total: 0 })]}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByText('uploadTask.batchFileLabel')).toBeInTheDocument()
  })

  it('shows error for failed task', () => {
    render(
      <UploadTaskList
        tasks={[makeTask({ status: 'failed', error: '加载失败' })]}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByText('加载失败')).toBeInTheDocument()
  })

  it('calls onCancel for active task', () => {
    const onCancel = vi.fn()
    render(
      <UploadTaskList tasks={[makeTask({})]} onCancel={onCancel} onDismiss={vi.fn()} />,
    )
    fireEvent.click(screen.getByTitle('uploadTask.cancelTask'))
    expect(onCancel).toHaveBeenCalledWith('t1')
  })

  it('calls onDismiss for terminal task', () => {
    const onDismiss = vi.fn()
    render(
      <UploadTaskList
        tasks={[makeTask({ status: 'completed' })]}
        onCancel={vi.fn()}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByTitle('uploadTask.dismissTask'))
    expect(onDismiss).toHaveBeenCalledWith('t1')
  })
})
```

（测试不包裹 i18n Provider，`t()` 回退为键名本身 —— 与项目现有组件测试一致。）

### Step 2: 运行测试 — 确认失败

```bash
cd frontend && npm run test -- UploadTaskList
```

预期：FAIL（组件不存在）。

### Step 3: 实现

创建 `frontend/src/components/KnowledgeBase/UploadTaskList.tsx`：

```tsx
import { Check, FileText, Link, Files, Loader2, X, XCircle } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { UploadTask } from '../../types/rag'

interface Props {
  tasks: UploadTask[]
  onCancel: (taskId: string) => void
  onDismiss: (taskId: string) => void
}

const ACTIVE_STATUSES = new Set(['pending', 'running'])

function taskPercent(t: UploadTask): number {
  if (t.status === 'completed') return 100
  if (t.total_files <= 0) return 0
  const fileSpan = 100 / t.total_files
  const chunkPart = t.chunk_total > 0 ? (t.chunk_done / t.chunk_total) * fileSpan : 0
  return Math.min(Math.round(t.done_files * fileSpan + chunkPart), 99)
}

export function UploadTaskList({ tasks, onCancel, onDismiss }: Props) {
  const { t } = useTranslation()
  if (tasks.length === 0) return null

  const stageLabel = (t: UploadTask): string => {
    if (t.status === 'pending') return 'uploadTask.stageQueued'
    const map: Record<string, string> = {
      loading: 'uploadTask.stageLoading',
      chunking: 'uploadTask.stageChunking',
      embedding: 'uploadTask.stageEmbedding',
      storing: 'uploadTask.stageStoring',
    }
    return map[t.stage] ?? ''
  }

  const icon = (t: UploadTask) => {
    if (t.kind === 'url') return <Link size={13} />
    if (t.kind === 'batch') return <Files size={13} />
    return <FileText size={13} />
  }

  return (
    <div className="kb-upload-tasks" data-testid="kb-upload-tasks">
      <div className="kb-upload-tasks__title">{t('uploadTask.title')}</div>
      {tasks.map(task => {
        const active = ACTIVE_STATUSES.has(task.status)
        const pct = taskPercent(task)
        return (
          <div key={task.id} className="kb-upload-task" data-testid={`kb-upload-task-${task.id}`}>
            <div className="kb-upload-task__header">
              <span className="kb-upload-task__icon">{icon(task)}</span>
              <span className="kb-upload-task__label" title={task.label}>
                {task.kind === 'batch'
                  ? t('uploadTask.batchFileLabel', {
                      name: task.label, count: String(task.total_files),
                    })
                  : task.label}
              </span>
              <span className={`kb-upload-task__badge kb-upload-task__badge--${task.status}`}>
                {task.status === 'running' && <Loader2 size={10} className="spin" />}
                {task.status === 'completed' && <Check size={10} />}
                {task.status === 'failed' && <XCircle size={10} />}
                {t(`uploadTask.status_${task.status}`)}
              </span>
              {active ? (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onCancel(task.id)}
                  title={t('uploadTask.cancelTask')}
                >
                  <X size={12} />
                </button>
              ) : (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onDismiss(task.id)}
                  title={t('uploadTask.dismissTask')}
                >
                  <X size={12} />
                </button>
              )}
            </div>
            {active && (
              <>
                <div className="kb-upload-task__bar" role="progressbar"
                  aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="kb-upload-task__fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="kb-upload-task__detail">
                  <span>{t(stageLabel(task))}</span>
                  {task.total_files > 1 && (
                    <span>
                      {t('uploadTask.fileProgress', {
                        done: String(task.done_files), total: String(task.total_files),
                      })}
                    </span>
                  )}
                  {task.chunk_total > 0 && (
                    <span>
                      {t('uploadTask.chunkProgress', {
                        done: String(task.chunk_done), total: String(task.chunk_total),
                      })}
                    </span>
                  )}
                </div>
              </>
            )}
            {task.status === 'completed' && task.result && (
              <div className="kb-upload-task__result">
                {t('uploadTask.taskResult', {
                  uploaded: String(task.result.uploaded.length),
                  skipped: String(task.result.skipped.length),
                  errors: String(task.result.errors.length),
                })}
              </div>
            )}
            {task.status === 'failed' && task.error && (
              <div className="kb-upload-task__error">{task.error}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}
```

注意测试断言：statusRunning 键名需与实现一致 —— 实现使用 `uploadTask.status_${status}`，
因此测试中期望文本应为 `uploadTask.statusRunning`，即键 `status_running` 不匹配。
统一为独立键：实现改用映射对象：

```ts
const statusKey: Record<string, string> = {
  pending: 'uploadTask.statusPending',
  running: 'uploadTask.statusRunning',
  completed: 'uploadTask.statusCompleted',
  failed: 'uploadTask.statusFailed',
  cancelled: 'uploadTask.statusCancelled',
}
// 渲染: {t(statusKey[task.status] ?? task.status)}
```

（Step 1 测试即按此断言，无需修改测试。）

### Step 4: 运行测试 — 确认通过

```bash
cd frontend && npm run test -- UploadTaskList
```

预期：PASS。

### Step 5: Commit

```bash
git add frontend/src/components/KnowledgeBase/UploadTaskList.tsx frontend/src/components/KnowledgeBase/UploadTaskList.test.tsx
git commit -m "feat(frontend): UploadTaskList progress card component"
```

---

## Task 9: KnowledgeBasePage 接线 + i18n + 样式

**Files:**
- Modify: `frontend/src/components/KnowledgeBase/KnowledgeBasePage.tsx`
- Modify: `frontend/src/i18n/locales/zh-CN.json`
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/App.css`

### Step 1: 修改页面

`KnowledgeBasePage.tsx` 改动清单（逐项执行）：

1. imports：追加
   ```ts
   import { UploadTaskList } from './UploadTaskList'
   import { useUploadTasks } from '../../hooks/useUploadTasks'
   ```
2. 删除状态：`uploading`（保留作提交中瞬时态）、`batchUploading`、`batchProgress`、`batchSummary` 全部删除。
3. 在组件顶部添加（`selectedKb` 之后定义）：

```tsx
  const handleUploadSettled = useCallback(() => {
    if (selectedKb) {
      void loadDocuments(selectedKb.id)
      void loadKbs()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKb?.id])

  const {
    tasks: uploadTasks, submitFiles, submitUrl,
    cancel: cancelUpload, dismiss: dismissUpload,
  } = useUploadTasks(selectedKb?.id ?? null, handleUploadSettled)
```

4. `handleUpload` 替换为：

```tsx
  const handleUpload = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0 || !selectedKb) return
    setUploading(true)
    try {
      await submitFiles(Array.from(files))
      showToast(t('uploadTask.submitSuccess'))
    } catch (err) {
      const detail = err instanceof Error ? err.message : t('knowledgeBase.uploadFailed')
      showToast(detail, true)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [selectedKb, showToast, t, submitFiles])
```

5. `handleUrlUpload` 替换核心调用：

```tsx
    setUrlUploading(true)
    try {
      await submitUrl(url)
      showToast(t('uploadTask.submitSuccess'))
      setUrlInput('')
    } catch (err) { ...原样... } finally { setUrlUploading(false) }
```
（依赖数组中 `loadDocuments, loadKbs` 替换为 `submitUrl`；删除成功后手动 loadDocuments/loadKbs 调用。）

6. `handleFolderUpload` 替换为：

```tsx
  const handleFolderUpload = useCallback(async () => {
    if (!selectedKb || folderFiles.length === 0) return
    try {
      await submitFiles(folderFiles)
      showToast(t('uploadTask.submitSuccess'))
      setFolderFiles([])
      setFolderFiltered(0)
    } catch (err) {
      const detail = err instanceof Error ? err.message : t('knowledgeBase.uploadFailed')
      showToast(detail, true)
    }
  }, [selectedKb, folderFiles, showToast, t, submitFiles])
```

删除 `batchUploading` 相关 disabled 逻辑（文件夹面板按钮 disabled 条件改为 `folderFiles.length === 0`，移除 `!batchUploading && !batchSummary` 条件）。

7. 删除 "Batch Progress" 与 "Batch Summary" 两个 JSX 块，替换为：

```tsx
                {/* Upload Tasks */}
                <UploadTaskList
                  tasks={uploadTasks}
                  onCancel={id => void cancelUpload(id)}
                  onDismiss={dismissUpload}
                />
```

（位置：上传面板之后、documents 列表之前。）

8. `selectKb` 中删除 `setBatchSummary(null); setBatchProgress(null)` 两行（hook 随 kbId 切换自动重置）。

### Step 2: i18n 条目

`zh-CN.json` 顶层追加（与 `knowledgeBase` 平级）：

```json
  "uploadTask": {
    "title": "上传任务",
    "statusPending": "排队中",
    "statusRunning": "处理中",
    "statusCompleted": "已完成",
    "statusFailed": "失败",
    "statusCancelled": "已取消",
    "stageQueued": "等待中",
    "stageLoading": "解析中",
    "stageChunking": "分块中",
    "stageEmbedding": "向量化中",
    "stageStoring": "入库中",
    "fileProgress": "{done}/{total} 文件",
    "chunkProgress": "{done}/{total} 分块",
    "batchFileLabel": "{name} 等 {count} 个文件",
    "submitSuccess": "上传任务已提交",
    "cancelTask": "取消任务",
    "dismissTask": "关闭",
    "taskResult": "{uploaded} 成功，{skipped} 跳过，{errors} 失败"
  },
```

`en.json` 对应：

```json
  "uploadTask": {
    "title": "Upload Tasks",
    "statusPending": "Queued",
    "statusRunning": "Processing",
    "statusCompleted": "Completed",
    "statusFailed": "Failed",
    "statusCancelled": "Cancelled",
    "stageQueued": "Waiting",
    "stageLoading": "Parsing",
    "stageChunking": "Chunking",
    "stageEmbedding": "Embedding",
    "stageStoring": "Storing",
    "fileProgress": "{done}/{total} files",
    "chunkProgress": "{done}/{total} chunks",
    "batchFileLabel": "{name} and {count} files",
    "submitSuccess": "Upload task submitted",
    "cancelTask": "Cancel task",
    "dismissTask": "Dismiss",
    "taskResult": "{uploaded} uploaded, {skipped} skipped, {errors} failed"
  },
```

同时删除两个 locale 中不再使用的 `batchUploading`、`batchComplete` 键（先全局搜索确认无其他引用）。

### Step 3: 样式（`frontend/src/App.css`）

删除 `.kb-batch-progress` 相关三段规则（约 2647 行起），替换为：

```css
/* ── KB Upload Tasks ── */
.kb-upload-tasks {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}

.kb-upload-tasks__title {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.kb-upload-task {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.kb-upload-task__header {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.kb-upload-task__icon {
  display: inline-flex;
  color: var(--text-secondary);
}

.kb-upload-task__label {
  flex: 1;
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-upload-task__badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.kb-upload-task__badge--running { color: var(--accent); }
.kb-upload-task__badge--completed { color: var(--success, #34d399); }
.kb-upload-task__badge--failed { color: var(--danger, #f87171); }
.kb-upload-task__badge--cancelled { color: var(--text-secondary); }

.kb-upload-task__bar {
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--bg-tertiary);
  overflow: hidden;
}

.kb-upload-task__fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--accent), var(--accent-2, var(--accent)));
  transition: width 0.4s ease;
}

.kb-upload-task__detail {
  display: flex;
  gap: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.kb-upload-task__result {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.kb-upload-task__error {
  font-size: var(--fs-xs);
  color: var(--danger, #f87171);
  word-break: break-all;
}
```

（若项目 CSS 变量中无 `--success`/`--danger`/`--bg-secondary` 等，先在 `App.css`/`themes.css` 中 grep 确认实际变量名，用现有等价变量替换。）

### Step 4: 验证

```bash
cd frontend && npm run test && npm run build
```

预期：全部 PASS，TS 编译通过。

### Step 5: Commit

```bash
git add frontend/src/components/KnowledgeBase/KnowledgeBasePage.tsx \
        frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json \
        frontend/src/App.css
git commit -m "feat(frontend): async upload flow with live task progress cards"
```

---

## Task 10: 全量验证 + README 更新

**Files:**
- Modify: `README.md`、`README_CN.md`（如有 API 表）

### Step 1: 后端全量检查

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest -x -q
```

全部必须通过；有失败就地修复（遵循 Phase 4 系统化调试：先定位根因再改）。

### Step 2: 前端全量检查

```bash
cd frontend && npm run lint && npm run test && npm run build
```

### Step 3: README 更新

`README.md` API 表中 RAG 部分更新为（保留原有其他行）：

```markdown
| POST | `/api/v1/rag/knowledge-bases/{id}/documents` | Upload a document (async, returns task id) |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents/url` | Upload a webpage by URL (async) |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents/batch` | Batch upload documents (async) |
| GET | `/api/v1/rag/upload-tasks/{task_id}` | Get upload task status/progress |
| GET | `/api/v1/rag/knowledge-bases/{id}/upload-tasks` | List upload tasks of a knowledge base |
| DELETE | `/api/v1/rag/upload-tasks/{task_id}` | Cancel or dismiss an upload task |
```

`README_CN.md` 若含相同 API 表，做对应中文更新；若无则跳过（先 grep 确认）。

### Step 4: Commit

```bash
git add -u && git add README.md README_CN.md
git commit -m "docs: update API tables for async RAG upload tasks"
```

### Step 5: 手动冒烟（可选但建议）

```bash
python start_dev.py
```

浏览器打开知识库页面：上传一个大 PDF，确认任务卡片出现、阶段/分块进度实时更新、
文档列表在完成后自动刷新；点击取消按钮确认可中止；切换到其他页面再回来确认任务恢复显示。

---

## 完成标准

- [ ] `pytest`、`ruff`、`mypy`、`npm run lint/test/build` 全绿
- [ ] 三种上传均返回 202，进度卡片实时展示阶段+分块进度
- [ ] 取消与页面刷新恢复均工作
- [ ] 无范围外改动
