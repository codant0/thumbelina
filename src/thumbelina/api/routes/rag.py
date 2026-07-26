"""RAG API routes -- knowledge base and document management."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from thumbelina.rag.ingestion.chunker import RecursiveChunker
from thumbelina.rag.ingestion.document_dedup import DocumentDeduplicator
from thumbelina.rag.ingestion.loader import TextLoader
from thumbelina.rag.knowledge_base.repository import (
    DocumentRepository,
    KnowledgeBaseRepository,
)
from thumbelina.rag.pipeline.indexer import Indexer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


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


class SimHashQueryRequest(BaseModel):
    sim_hash: str = Field(
        ..., min_length=16, max_length=16, description="十六进制 SimHash（16 字符）"
    )
    threshold: int = Field(ge=0, le=64, description="汉明距离阈值")
    direction: str = Field(
        default="le", pattern="^(le|ge)$", description="le=相似, ge=差异")
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


def _delete_chunk_fingerprints(request: Request, *, doc_id: str | None = None, kb_id: str | None = None) -> None:
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


@router.post("/knowledge-bases/{kb_id}/documents", response_model=DocumentResponse)
async def upload_document(kb_id: str, file: UploadFile, request: Request) -> DocumentResponse:
    # Verify knowledge base exists
    kb_repo = _get_kb_repo(request)
    kb = await kb_repo.get(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # Validate file type
    from thumbelina.rag.knowledge_base.models import DocumentType

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1]
    try:
        doc_type = DocumentType.from_value(ext)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Save file to temporary location
    tmp_dir = Path("/tmp_file")
    tmp_dir.mkdir(exist_ok=True)
    tmp_path = tmp_dir / Path(file.filename).name
    with open(tmp_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 每次 1MB
            f.write(chunk)
    await file.close()

    try:
        # Build indexer from app.state components
        registry = getattr(request.app.state, "rag_embedding_registry", None)
        if registry is None:
            raise HTTPException(
                status_code=503, detail="RAG embedding registry not available")
        embedder = registry.create()

        store_manager = getattr(request.app.state, "rag_store_manager", None)
        if store_manager is None:
            raise HTTPException(
                status_code=503, detail="RAG store manager not available")
        vector_store = store_manager.get_or_create_store(kb_id)

        # 使用共享的 loader 实例，确保 document_id 与 ChromaDB 中存储的一致
        loader = TextLoader()
        doc_repo = _get_doc_repo(request)
        doc_deduplicator = (
            DocumentDeduplicator(doc_repo=doc_repo) if doc_repo else None
        )

        # 获取主数据库引擎，用于分块级去重
        engine = getattr(request.app.state, "engine", None)

        kb_indexer = Indexer(
            loader=loader,
            chunker=RecursiveChunker(),
            embedder=embedder,
            vector_store=vector_store,
            doc_repo=doc_repo,
            doc_deduplicator=doc_deduplicator,
            engine=engine,
            chunk_dedup_enabled=True,
        )

        stats = await asyncio.to_thread(kb_indexer.index_batch, [tmp_path])
        logger.debug(f"index stats: {stats}")
        if stats.errors:
            raise HTTPException(
                status_code=400, detail="; ".join(stats.errors)
            )

        # TODO 当前的loader只支持单个文件加载，后续补齐文件夹loader时需修改
        documents = stats.documents
        document = documents[0]

        # Save document metadata，使用与 ChromaDB 中相同的 document_id
        doc = await doc_repo.create(
            kb_id=kb_id,
            name=document.name,
            source_uri=document.source_uri,
            doc_type=doc_type.value,
            sha256=document.sha256,
            sim_hash_64=document.sim_hash_64,
            chunk_count=stats.indexed_count,
            doc_id=document.id,
        )

        return DocumentResponse(
            id=doc.id,
            knowledge_base_id=doc.knowledge_base_id,
            name=doc.name,
            doc_type=doc.doc_type,
            chunk_count=doc.chunk_count,
            created_at=str(doc.created_at),
        )
    finally:
        # Clean up temporary file
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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
            logger.warning(
                "Failed to delete vectors for doc %s: %s", doc_id, exc)
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
    embedder = registry.create()

    from thumbelina.rag.retrieval.strategies import SimpleRetriever

    retriever = SimpleRetriever(
        embedding_model=embedder, vector_store=vector_store)

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

    from thumbelina.rag.knowledge_base.simhash import bytes_to_hex, hex_to_simhash_bytes

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
