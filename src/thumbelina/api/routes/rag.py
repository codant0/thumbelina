"""RAG API routes -- knowledge base and document management."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from thumbelina.rag.common.repository import (
    DocumentRepository,
    KnowledgeBaseRepository,
)
from thumbelina.rag.ingestion.chunker import RecursiveChunker
from thumbelina.rag.ingestion.document_dedup import DocumentDeduplicator
from thumbelina.rag.ingestion.loader import Loader, LoaderRegistry, TextLoader
from thumbelina.rag.pipeline.indexer import IndexCancelledError, Indexer, ProgressEvent
from thumbelina.rag.pipeline.upload_tasks import (
    TERMINAL_STATUSES,
    UploadTaskManager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

# 后台上传任务的强引用：事件循环仅弱引用跟踪 Task，丢弃引用可能导致
# 任务在执行中被 GC（状态卡在 running、临时文件泄漏）。
_background_tasks: set[asyncio.Task[None]] = set()


# ---------- Pydantic schemas ----------


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    created_at: str
    updated_at: str


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    knowledge_base_id: str = Field(default="0")
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResultChunk(BaseModel):
    content: str
    score: float
    metadata: str | None = None


class QueryResponse(BaseModel):
    results: list[QueryResultChunk]


class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    name: str
    doc_type: str
    chunk_count: int
    created_at: str


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    content: str
    metadata: str | None = None


class UrlUploadRequest(BaseModel):
    url: str = Field(..., min_length=1, description="要抓取的网页 URL")


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


class SimHashQueryRequest(BaseModel):
    sim_hash: str = Field(
        ..., min_length=16, max_length=16, description="十六进制 SimHash（16 字符）"
    )
    threshold: int = Field(ge=0, le=64, description="汉明距离阈值")
    direction: str = Field(default="le", pattern="^(le|ge)$", description="le=相似, ge=差异")
    knowledge_base_id: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class SimHashResultDocument(BaseModel):
    id: str
    name: str
    sim_hash: str
    distance: int


# ---------- Helpers ----------


def _get_kb_repo(request: Request) -> KnowledgeBaseRepository:
    repo = getattr(request.app.state, "rag_kb_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")
    return repo


def _get_doc_repo(request: Request) -> DocumentRepository:
    repo = getattr(request.app.state, "rag_doc_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")
    return repo


def _get_task_manager(request: Request) -> UploadTaskManager:
    manager: UploadTaskManager | None = getattr(request.app.state, "rag_upload_tasks", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")
    return manager


def _doc_repo_from_state(state: Any) -> DocumentRepository:
    repo: DocumentRepository | None = getattr(state, "rag_doc_repo", None)
    if repo is None:
        raise RuntimeError("RAG not initialized")
    return repo


async def _save_upload_file(file: UploadFile, filename: str) -> Path:
    """流式保存上传文件到临时目录（uuid 前缀避免同名冲突）。"""
    tmp_dir = Path("/tmp_file")
    tmp_dir.mkdir(exist_ok=True)
    tmp_path = tmp_dir / f"upload_{uuid.uuid4().hex}_{Path(filename).name}"
    try:
        with open(tmp_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def _unlink_tmp_files(paths: list[Path]) -> None:
    """删除上传临时文件（逐个忽略失败），供任务 cleanup 回调使用。"""
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


def _delete_chunk_fingerprints(
    request: Request, *, doc_id: str | None = None, kb_id: str | None = None
) -> None:
    """手动清理 chunk 指纹记录（FK CASCADE 未启用时的保底措施）。"""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return
    try:
        from sqlalchemy import text as sql_text

        with engine.begin() as conn:
            if doc_id:
                conn.execute(
                    sql_text("DELETE FROM rag_chunk_fingerprints WHERE document_id = :doc_id"),
                    {"doc_id": doc_id},
                )
            elif kb_id:
                conn.execute(
                    sql_text("DELETE FROM rag_chunk_fingerprints WHERE kb_id = :kb_id"),
                    {"kb_id": kb_id},
                )
    except Exception as exc:
        logger.warning("清理 chunk 指纹失败: %s", exc)


# ---------- Knowledge Base endpoints ----------


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(request: Request) -> list[KnowledgeBaseResponse]:
    repo = _get_kb_repo(request)
    kbs = await repo.list_all()
    return [
        KnowledgeBaseResponse(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            created_at=str(kb.created_at),
            updated_at=str(kb.updated_at),
        )
        for kb in kbs
    ]


@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    body: KnowledgeBaseCreate, request: Request
) -> KnowledgeBaseResponse:
    repo = _get_kb_repo(request)
    kb_id = uuid.uuid4().hex
    try:
        kb = await repo.create(kb_id, body.name, body.description)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return KnowledgeBaseResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        created_at=str(kb.created_at),
        updated_at=str(kb.updated_at),
    )


@router.put("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str, body: KnowledgeBaseUpdate, request: Request
) -> KnowledgeBaseResponse:
    repo = _get_kb_repo(request)
    try:
        kb = await repo.update(kb_id, name=body.name, description=body.description)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return KnowledgeBaseResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        created_at=str(kb.created_at),
        updated_at=str(kb.updated_at),
    )


@router.delete("/knowledge-bases/{kb_id}")
async def delete_knowledge_base(kb_id: str, request: Request) -> dict:
    repo = _get_kb_repo(request)
    doc_repo = _get_doc_repo(request)
    # 1. 先清理 ChromaDB 向量库
    store_manager = getattr(request.app.state, "rag_store_manager", None)
    if store_manager:
        store_manager.delete_store(kb_id)
    # 2. 清理 chunk 指纹
    _delete_chunk_fingerprints(request, kb_id=kb_id)
    # 3. 删除文档元数据
    await doc_repo.delete_by_kb(kb_id)
    # 4. 最后删除知识库记录
    try:
        deleted = await repo.delete(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"deleted": True}


# ---------- Document endpoints ----------


@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(kb_id: str, request: Request) -> list[DocumentResponse]:
    repo = _get_doc_repo(request)
    docs = await repo.list_by_kb(kb_id)
    return [
        DocumentResponse(
            id=d.id,
            knowledge_base_id=d.knowledge_base_id,
            name=d.name,
            doc_type=d.doc_type,
            chunk_count=d.chunk_count,
            created_at=str(d.created_at),
        )
        for d in docs
    ]


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

    manager = _get_task_manager(request)
    try:
        tmp_path = await _save_upload_file(file, filename)
    finally:
        await file.close()

    task = manager.create(kb_id, "file", filename, total_files=1)
    state = request.app.state
    bg = asyncio.create_task(
        manager.run(
            task.id,
            lambda: _run_file_upload(
                manager=manager,
                task_id=task.id,
                kb_id=kb_id,
                files=[(filename, tmp_path, doc_type.value)],
                state=state,
            ),
            cleanup=lambda: _unlink_tmp_files([tmp_path]),
        )
    )
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)
    return CreateUploadTaskResponse(task_id=task.id)


async def _run_file_upload(
    *,
    manager: UploadTaskManager,
    task_id: str,
    kb_id: str,
    files: list[tuple[str, Path, str]],
    state: Any,
    pre_skipped: list[str] | None = None,
) -> None:
    """索引已落盘的上传文件并写入文档元数据。

    files: (显示名, 临时路径, doc_type) 列表。
    pre_skipped: 端点层已判定跳过（如不支持的类型）的文件名，随最终结果一并记录；
    任务在启动前被取消时，端点预置的结果即保留这些 skipped 信息。
    临时文件清理由调用方通过 manager.run() 的 cleanup 回调负责。
    """
    if not files:
        if not pre_skipped:
            raise RuntimeError("没有可上传的文件")
        return  # 结果已在端点中预置 skipped，直接 completed
    doc_repo = _doc_repo_from_state(state)
    uploaded: list[dict[str, Any]] = []
    skipped: list[str] = list(pre_skipped or [])
    errors: list[dict[str, str]] = []

    def _progress(ev: ProgressEvent) -> None:
        manager.update_progress(task_id, ev)

    for idx, (display_name, tmp_path, doc_type) in enumerate(files):
        manager.start_file(task_id, idx, display_name)
        try:
            indexer = await _build_indexer(state, kb_id, path=str(tmp_path))
            stats = await asyncio.to_thread(
                indexer.index,
                str(tmp_path),
                progress_cb=_progress,
                cancel_event=manager.get_cancel_event(task_id),
            )
        except IndexCancelledError:
            raise
        except Exception as exc:
            errors.append({"filename": display_name, "error": str(exc)})
            continue
        if stats.errors:
            errors.append({"filename": display_name, "error": "; ".join(stats.errors)})
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
        uploaded.append({"id": doc.id, "name": doc.name, "chunk_count": doc.chunk_count})
        manager.mark_file_done(task_id)
    if not uploaded and errors:
        raise RuntimeError("; ".join(e["error"] for e in errors))
    manager.set_result(task_id, {"uploaded": uploaded, "skipped": skipped, "errors": errors})


async def _run_url_upload(
    *,
    manager: UploadTaskManager,
    task_id: str,
    kb_id: str,
    url: str,
    state: Any,
) -> None:
    """抓取 URL 内容并索引为文档。无临时文件，不需要 cleanup 回调。"""
    doc_repo = _doc_repo_from_state(state)

    def _progress(ev: ProgressEvent) -> None:
        manager.update_progress(task_id, ev)

    manager.start_file(task_id, 0, url)
    indexer = await _build_indexer(state, kb_id, path=url)
    stats = await asyncio.to_thread(
        indexer.index,
        url,
        progress_cb=_progress,
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
            "uploaded": [{"id": doc.id, "name": doc.name, "chunk_count": doc.chunk_count}],
            "skipped": [],
            "errors": [],
        },
    )


async def _build_indexer(
    state: Any,
    kb_id: str,
    *,
    path: str | None = None,
    loader: Loader | None = None,
) -> Indexer:
    """从 app.state 构建 Indexer 实例（复用已有组件）。

    loader 选择策略（优先级从高到低）：
    1. 显式传入 loader 参数 → 直接使用
    2. 传入 path 参数 → 由 LoaderRegistry 根据路径自动匹配
    3. 均未传入 → 回退到 TextLoader

    在后台工作协程中调用（非请求上下文），组件缺失时抛出 RuntimeError。
    """
    registry = getattr(state, "rag_embedding_registry", None)
    if registry is None:
        raise RuntimeError("RAG embedding registry not available")
    # 在工作线程中获取模型实例：若启动后的后台预加载仍在进行，
    # 这里会等待其完成并复用缓存实例，而不是阻塞事件循环或重复加载
    embedder = await asyncio.to_thread(registry.create)

    store_manager = getattr(state, "rag_store_manager", None)
    if store_manager is None:
        raise RuntimeError("RAG store manager not available")
    vector_store = store_manager.get_or_create_store(kb_id)

    doc_repo = _doc_repo_from_state(state)
    doc_deduplicator = DocumentDeduplicator(doc_repo=doc_repo)
    engine = getattr(state, "engine", None)

    # Loader 选择：显式 > 自动匹配 > 默认
    if loader is None and path is not None:
        try:
            loader = LoaderRegistry.find(path)
        except ValueError:
            loader = TextLoader()

    return Indexer(
        loader=loader or TextLoader(),
        chunker=RecursiveChunker(),
        embedder=embedder,
        vector_store=vector_store,
        doc_repo=doc_repo,
        doc_deduplicator=doc_deduplicator,
        engine=engine,
        chunk_dedup_enabled=True,
    )


@router.post(
    "/knowledge-bases/{kb_id}/documents/url",
    status_code=202,
    response_model=CreateUploadTaskResponse,
)
async def upload_document_by_url(
    kb_id: str, body: UrlUploadRequest, request: Request
) -> CreateUploadTaskResponse:
    """通过 URL 抓取网页内容并索引为文档（后台任务）。"""
    kb_repo = _get_kb_repo(request)
    if await kb_repo.get(kb_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    manager = _get_task_manager(request)
    task = manager.create(kb_id, "url", url, total_files=1)
    state = request.app.state
    bg = asyncio.create_task(
        manager.run(
            task.id,
            lambda: _run_url_upload(
                manager=manager, task_id=task.id, kb_id=kb_id, url=url, state=state
            ),
        )
    )
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)
    return CreateUploadTaskResponse(task_id=task.id)


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
        try:
            tmp_path = await _save_upload_file(file, filename)
        finally:
            await file.close()
        accepted.append((filename, tmp_path, doc_type.value))

    label = accepted[0][0] if accepted else (skipped_names[0] if skipped_names else "")
    task = manager.create(kb_id, "batch", label, total_files=len(accepted))
    if skipped_names:
        manager.set_result(task.id, {"uploaded": [], "skipped": skipped_names, "errors": []})
    state = request.app.state
    tmp_paths = [tmp_path for _, tmp_path, _ in accepted]
    bg = asyncio.create_task(
        manager.run(
            task.id,
            lambda: _run_file_upload(
                manager=manager,
                task_id=task.id,
                kb_id=kb_id,
                files=accepted,
                state=state,
                pre_skipped=skipped_names,
            ),
            cleanup=lambda: _unlink_tmp_files(tmp_paths),
        )
    )
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)
    return CreateUploadTaskResponse(task_id=task.id)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request) -> dict:
    doc_repo = _get_doc_repo(request)
    doc = await doc_repo.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # 清理向量库中属于该文档的 chunks
    store_manager = getattr(request.app.state, "rag_store_manager", None)
    if store_manager:
        try:
            store = store_manager.get_or_create_store(doc.knowledge_base_id)
            store.delete_by_metadata(where={"document_id": doc_id})
        except Exception as exc:
            logger.warning("Failed to delete vectors for doc %s: %s", doc_id, exc)
    # 清理 chunk 指纹
    _delete_chunk_fingerprints(request, doc_id=doc_id)

    deleted = await doc_repo.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkResponse])
async def list_document_chunks(doc_id: str, request: Request) -> list[ChunkResponse]:
    doc_repo = _get_doc_repo(request)
    doc = await doc_repo.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    store_manager = getattr(request.app.state, "rag_store_manager", None)
    if store_manager is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")

    store = store_manager.get_or_create_store(doc.knowledge_base_id)
    chunks = store.query_by_metadata(where={"document_id": doc_id})
    return [
        ChunkResponse(
            id=c.id,
            document_id=c.document_id,
            content=c.content,
            metadata=c.metadata,
        )
        for c in chunks
    ]


# ---------- Upload task endpoints ----------


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
async def cancel_upload_task(task_id: str, request: Request) -> dict[str, bool]:
    """取消活跃任务；终态任务则从列表中移除。"""
    manager = _get_task_manager(request)
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Upload task not found")
    if task.status in TERMINAL_STATUSES:
        manager.remove(task_id)
        return {"cancelled": False}
    return {"cancelled": manager.cancel(task_id)}


# ---------- Query endpoint ----------


@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(body: QueryRequest, request: Request) -> QueryResponse:
    store_manager = getattr(request.app.state, "rag_store_manager", None)
    if store_manager is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")

    registry = getattr(request.app.state, "rag_embedding_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")

    vector_store = store_manager.get_or_create_store(body.knowledge_base_id)
    # 在工作线程中获取模型实例，避免阻塞事件循环（预加载未完成时会等待加载）
    embedder = await asyncio.to_thread(registry.create)

    from thumbelina.rag.retrieval.strategies import SimpleRetriever

    retriever = SimpleRetriever(embedding_model=embedder, vector_store=vector_store)

    try:
        chunks = await asyncio.to_thread(retriever.retrieve, body.query, body.top_k)
    except Exception as exc:
        logger.warning("RAG query failed: %s", exc)
        chunks = []

    return QueryResponse(
        results=[
            QueryResultChunk(
                content=c.content,
                score=c.score,
                metadata=c.metadata if hasattr(c, "metadata") else None,
            )
            for c in chunks
        ]
    )


# ---------- SimHash query endpoint ----------


@router.post("/documents/simhash-query", response_model=list[SimHashResultDocument])
async def query_by_simhash(
    body: SimHashQueryRequest, request: Request
) -> list[SimHashResultDocument]:
    """按 SimHash 汉明距离查询文档。

    - direction="le"：查找相似文档（距离 ≤ 阈值）
    - direction="ge"：查找差异文档（距离 ≥ 阈值）
    """
    doc_repo = _get_doc_repo(request)

    from thumbelina.rag.common.simhash import bytes_to_hex, hex_to_simhash_bytes

    try:
        query_bytes = hex_to_simhash_bytes(body.sim_hash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 SimHash: {exc}")

    results = await doc_repo.find_by_simhash(
        query_sim_hash=query_bytes,
        threshold=body.threshold,
        direction=body.direction,
        kb_id=body.knowledge_base_id,
        limit=body.limit,
    )

    return [
        SimHashResultDocument(
            id=doc.id,
            name=doc.name,
            sim_hash=bytes_to_hex(doc.sim_hash_64),
            distance=distance,
        )
        for doc, distance in results
    ]
