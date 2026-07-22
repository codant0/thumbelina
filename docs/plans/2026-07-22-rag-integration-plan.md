# RAG 集成实施计划

**日期**: 2026-07-22
**设计文档**: `docs/plans/2026-07-22-rag-integration-design.md`

## 任务概览

| # | 任务 | 预计时间 | 依赖 |
|---|------|---------|------|
| 1 | Conversation 模型新增 knowledge_base_id | 4 min | — |
| 2 | RAG API 路由 — 知识库 CRUD | 5 min | Task 1 |
| 3 | RAG API 路由 — 文档管理 | 5 min | Task 2 |
| 4 | RAG API 路由 — 检索测试 | 3 min | Task 2 |
| 5 | RAG 初始化 — app.py lifespan | 4 min | Task 2-4 |
| 6 | Agent RAG 集成 | 5 min | Task 5 |
| 7 | WebSocket/HTTP 传递 knowledge_base_id | 3 min | Task 6 |
| 8 | i18n 添加知识库翻译 | 2 min | — |
| 9 | 前端 KnowledgeBasePage — 知识库管理 | 5 min | Task 5, 8 |
| 10 | 前端 KnowledgeBasePage — 文档管理 | 5 min | Task 9 |
| 11 | 前端 KnowledgeBasePage — 检索测试 | 3 min | Task 10 |
| 12 | 聊天窗口 KnowledgeBaseSelector | 5 min | Task 7, 8 |
| 13 | 端到端验证与清理 | 4 min | Task 1-12 |

---

## Task 1: Conversation 模型新增 knowledge_base_id

### 1.1 测试先行

在 `tests/test_memory/test_models.py`（或相应测试文件）中添加：

```python
class TestConversationKnowledgeBase:
    def test_default_knowledge_base_id_is_none(self):
        """新会话默认不绑定知识库。"""
        conv = Conversation()
        assert conv.knowledge_base_id is None

    def test_set_knowledge_base_id(self):
        conv = Conversation(knowledge_base_id="kb-1")
        assert conv.knowledge_base_id == "kb-1"
```

### 1.2 实现

**文件**: `src/thumbelina/memory/models.py`

在 `Conversation` 模型中新增字段（在 `model` 字段之后）：

```python
knowledge_base_id: Mapped[str | None] = mapped_column(
    String(36),
    nullable=True,
    default=None,
    comment="ID of the RAG knowledge base bound to this conversation",
)
```

**文件**: `src/thumbelina/api/schemas.py`

在 `ConversationSchema` 和 `ConversationDetailSchema` 中新增：

```python
knowledge_base_id: str | None = None
```

**文件**: `src/thumbelina/memory/repository.py`

新增 `set_conversation_knowledge_base` 方法（参照 `set_conversation_model` 模式）：

```python
def _set_conversation_knowledge_base_sync(
    self, conversation_id: str, knowledge_base_id: str | None
) -> bool:
    with self._get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None:
            return False
        conv.knowledge_base_id = knowledge_base_id
        session.commit()
        return True

async def set_conversation_knowledge_base(
    self, conversation_id: str, knowledge_base_id: str | None
) -> bool:
    return await asyncio.to_thread(
        self._set_conversation_knowledge_base_sync,
        conversation_id,
        knowledge_base_id,
    )
```

**文件**: `src/thumbelina/memory/manager.py`

新增转发方法：

```python
async def set_conversation_knowledge_base(
    self, conversation_id: str, knowledge_base_id: str | None
) -> bool:
    return await self.repository.set_conversation_knowledge_base(
        conversation_id, knowledge_base_id
    )
```

**文件**: `src/thumbelina/api/routes/conversations.py`

新增端点：

```python
class SetConversationKnowledgeBaseRequest(BaseModel):
    knowledge_base_id: str | None = Field(
        default=None,
        description="ID of the knowledge base, or null to unbind",
    )

@router.put(
    "/conversations/{conversation_id}/knowledge-base",
    response_model=ConversationSchema,
)
async def set_conversation_knowledge_base(
    conversation_id: str,
    body: SetConversationKnowledgeBaseRequest,
    memory: MemoryManager = Depends(get_memory_manager),
) -> ConversationSchema:
    """Bind or unbind a knowledge base to a conversation."""
    ok = await memory.set_conversation_knowledge_base(
        conversation_id, body.knowledge_base_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = await memory.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSchema(**conv)
```

### 1.3 验证

```bash
pytest tests/test_memory/ -x -q -k "knowledge_base or conversation"
pytest tests/test_api/test_conversations.py -x -q
```

---

## Task 2: RAG API 路由 — 知识库 CRUD

### 2.1 测试先行

创建 `tests/test_api/test_rag.py`：

```python
"""Tests for RAG API routes."""
import pytest
from httpx import AsyncClient


class TestKnowledgeBaseCRUD:
    @pytest.mark.asyncio
    async def test_list_knowledge_bases(self, client):
        resp = await client.get("/api/v1/rag/knowledge-bases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # 默认知识库应该存在
        assert any(kb["id"] == "0" for kb in data)

    @pytest.mark.asyncio
    async def test_create_knowledge_base(self, client):
        resp = await client.post("/api/v1/rag/knowledge-bases", json={
            "name": "技术文档",
            "description": "技术相关文档"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "技术文档"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_name_allowed(self, client):
        """不同知识库可以同名。"""
        await client.post("/api/v1/rag/knowledge-bases", json={"name": "A"})
        resp = await client.post("/api/v1/rag/knowledge-bases", json={"name": "A"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_knowledge_base(self, client):
        create_resp = await client.post("/api/v1/rag/knowledge-bases", json={"name": "A"})
        kb_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/rag/knowledge-bases/{kb_id}", json={
            "name": "B", "description": "updated"
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "B"

    @pytest.mark.asyncio
    async def test_delete_knowledge_base(self, client):
        create_resp = await client.post("/api/v1/rag/knowledge-bases", json={"name": "X"})
        kb_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/rag/knowledge-bases/{kb_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_default_kb_fails(self, client):
        resp = await client.delete("/api/v1/rag/knowledge-bases/0")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_nonexistent_kb_returns_404(self, client):
        resp = await client.put("/api/v1/rag/knowledge-bases/no-such", json={"name": "X"})
        assert resp.status_code == 404
```

### 2.2 实现

创建 `src/thumbelina/api/routes/rag.py`：

```python
"""RAG API routes — knowledge base and document management."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

from thumbelina.rag.knowledge_base.repository import (
    DocumentRepository,
    KnowledgeBaseRepository,
)

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


# ---------- Knowledge Base endpoints ----------

@router.get("/knowledge-bases", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(request: Request) -> list[KnowledgeBaseResponse]:
    repo = _get_kb_repo(request)
    kbs = await repo.list_all()
    return [
        KnowledgeBaseResponse(
            id=kb.id, name=kb.name, description=kb.description,
            created_at=str(kb.created_at), updated_at=str(kb.updated_at),
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
        id=kb.id, name=kb.name, description=kb.description,
        created_at=str(kb.created_at), updated_at=str(kb.updated_at),
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
        id=kb.id, name=kb.name, description=kb.description,
        created_at=str(kb.created_at), updated_at=str(kb.updated_at),
    )


@router.delete("/knowledge-bases/{kb_id}")
async def delete_knowledge_base(kb_id: str, request: Request) -> dict:
    repo = _get_kb_repo(request)
    doc_repo = _get_doc_repo(request)
    try:
        deleted = await repo.delete(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    # 级联删除文档元数据和向量
    await doc_repo.delete_by_kb(kb_id)
    store_manager = getattr(request.app.state, "rag_store_manager", None)
    if store_manager:
        store_manager.delete_store(kb_id)
    return {"deleted": True}
```

### 2.3 验证

```bash
pytest tests/test_api/test_rag.py::TestKnowledgeBaseCRUD -x -q
```

---

## Task 3: RAG API 路由 — 文档管理

### 3.1 测试先行

在 `tests/test_api/test_rag.py` 中添加：

```python
class TestDocumentManagement:
    @pytest.mark.asyncio
    async def test_list_documents_empty(self, client):
        resp = await client.get("/api/v1/rag/knowledge-bases/0/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_upload_document(self, client, tmp_path):
        # 准备测试文件
        test_file = tmp_path / "test.md"
        test_file.write_text("# 测试\n这是测试内容。", encoding="utf-8")
        with open(test_file, "rb") as f:
            resp = await client.post(
                "/api/v1/rag/knowledge-bases/0/documents",
                files={"file": ("test.md", f, "text/markdown")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test.md"
        assert data["knowledge_base_id"] == "0"

    @pytest.mark.asyncio
    async def test_upload_unsupported_type_returns_400(self, client, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake")
        with open(test_file, "rb") as f:
            resp = await client.post(
                "/api/v1/rag/knowledge-bases/0/documents",
                files={"file": ("test.pdf", f, "application/pdf")},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_document(self, client, tmp_path):
        # 先上传
        test_file = tmp_path / "a.md"
        test_file.write_text("content", encoding="utf-8")
        with open(test_file, "rb") as f:
            upload_resp = await client.post(
                "/api/v1/rag/knowledge-bases/0/documents",
                files={"file": ("a.md", f, "text/markdown")},
            )
        doc_id = upload_resp.json()["id"]
        resp = await client.delete(f"/api/v1/rag/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_document_returns_404(self, client):
        resp = await client.delete("/api/v1/rag/documents/no-such")
        assert resp.status_code == 404
```

### 3.2 实现

在 `src/thumbelina/api/routes/rag.py` 中追加：

```python
# ---------- Document schemas ----------

class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    name: str
    doc_type: str
    chunk_count: int
    created_at: str


# ---------- Document endpoints ----------

@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(kb_id: str, request: Request) -> list[DocumentResponse]:
    repo = _get_doc_repo(request)
    docs = await repo.list_by_kb(kb_id)
    return [
        DocumentResponse(
            id=d.id, knowledge_base_id=d.knowledge_base_id,
            name=d.name, doc_type=d.doc_type,
            chunk_count=d.chunk_count, created_at=str(d.created_at),
        )
        for d in docs
    ]


@router.post("/knowledge-bases/{kb_id}/documents", response_model=DocumentResponse)
async def upload_document(
    kb_id: str, file: UploadFile, request: Request
) -> DocumentResponse:
    # 验证知识库存在
    kb_repo = _get_kb_repo(request)
    kb = await kb_repo.get(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # 验证文件类型
    from thumbelina.rag.knowledge_base.models import DocumentType
    doc_type = DocumentType.from_value(file.filename or "")
    if doc_type is None:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # 保存文件到临时目录
    import tempfile, os
    content = await file.read()
    suffix = os.path.splitext(file.filename or ".txt")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 索引文档
        indexer = getattr(request.app.state, "rag_indexer", None)
        if indexer is None:
            raise HTTPException(status_code=503, detail="RAG indexer not available")

        # 获取知识库对应的向量存储
        store_manager = getattr(request.app.state, "rag_store_manager", None)
        if store_manager is None:
            raise HTTPException(status_code=503, detail="RAG store manager not available")
        vector_store = store_manager.get_or_create_store(kb_id)

        # 创建临时 indexer 使用知识库的向量存储
        from thumbelina.rag.pipeline.indexer import Indexer
        from thumbelina.rag.ingestion.loader import TextLoader
        from thumbelina.rag.ingestion.chunker import RecursiveChunker
        from thumbelina.rag.embedding.registry import EmbeddingRegistry

        registry: EmbeddingRegistry = request.app.state.rag_embedding_registry
        embedder = registry.create()
        loader = TextLoader()
        chunker = RecursiveChunker()
        kb_indexer = Indexer(
            loader=loader, chunker=chunker,
            embedder=embedder, vector_store=vector_store,
        )
        stats = kb_indexer.index(tmp_path)

        # 保存文档元数据
        doc_repo = _get_doc_repo(request)
        doc = await doc_repo.create(
            kb_id=kb_id,
            name=file.filename or "unknown",
            source_uri=tmp_path,
            doc_type=doc_type.value,
            chunk_count=stats.indexed_count,
        )

        return DocumentResponse(
            id=doc.id, knowledge_base_id=doc.knowledge_base_id,
            name=doc.name, doc_type=doc.doc_type,
            chunk_count=doc.chunk_count, created_at=str(doc.created_at),
        )
    finally:
        # 清理临时文件
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

    # 从向量存储中删除（需要通过 chunk IDs，简化为重建 collection）
    # 初版：仅删除元数据记录，向量数据将在后续优化中清理
    deleted = await doc_repo.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}
```

### 3.3 验证

```bash
pytest tests/test_api/test_rag.py::TestDocumentManagement -x -q
```

---

## Task 4: RAG API 路由 — 检索测试

### 4.1 测试先行

在 `tests/test_api/test_rag.py` 中添加：

```python
class TestRAGQuery:
    @pytest.mark.asyncio
    async def test_query_returns_results(self, client):
        resp = await client.post("/api/v1/rag/query", json={
            "query": "测试问题",
            "knowledge_base_id": "0",
            "top_k": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    @pytest.mark.asyncio
    async def test_query_empty_results(self, client):
        """空知识库查询应返回空列表。"""
        resp = await client.post("/api/v1/rag/query", json={
            "query": "任意问题",
            "knowledge_base_id": "0",
        })
        assert resp.status_code == 200
        assert resp.json()["results"] == []
```

### 4.2 实现

在 `rag.py` 中追加检索端点：

```python
@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    body: QueryRequest, request: Request
) -> QueryResponse:
    store_manager = getattr(request.app.state, "rag_store_manager", None)
    if store_manager is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")

    vector_store = store_manager.get_or_create_store(body.knowledge_base_id)

    from thumbelina.rag.embedding.registry import EmbeddingRegistry
    registry: EmbeddingRegistry = request.app.state.rag_embedding_registry
    embedder = registry.create()

    from thumbelina.rag.retrieval.strategies import SimpleRetriever
    retriever = SimpleRetriever(embedder=embedder, vector_store=vector_store, top_k=body.top_k)

    try:
        chunks = await retriever.retrieve(body.query)
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
```

### 4.3 验证

```bash
pytest tests/test_api/test_rag.py::TestRAGQuery -x -q
```

---

## Task 5: RAG 初始化 — app.py lifespan

### 5.1 测试先行

在现有的 `tests/test_api/conftest.py` 或新文件中测试 RAG 初始化不破坏现有启动：

```python
@pytest.mark.asyncio
async def test_app_starts_with_rag(client):
    """应用应能正常启动并注册 RAG 路由。"""
    resp = await client.get("/api/v1/rag/knowledge-bases")
    assert resp.status_code == 200
```

### 5.2 实现

**文件**: `src/thumbelina/api/app.py`

在 lifespan 函数中（`subagent_manager` 初始化之后，`agent` 创建之前）添加：

```python
# Initialize RAG components
rag_kb_repo = None
rag_doc_repo = None
rag_store_manager = None
rag_embedding_registry = None
rag_indexer = None
try:
    from thumbelina.rag.knowledge_base.db import init_rag_db
    from thumbelina.rag.knowledge_base.repository import (
        KnowledgeBaseRepository,
        DocumentRepository,
    )
    from thumbelina.rag.embedding.registry import EmbeddingRegistry
    from thumbelina.rag.embedding.store_manager import ChromaStoreManager
    from thumbelina.rag.ingestion.chunker import RecursiveChunker
    from thumbelina.rag.ingestion.loader import TextLoader
    from thumbelina.rag.pipeline.indexer import Indexer

    # 复用主数据库引擎初始化 RAG 表
    rag_session_factory = init_rag_db(memory.engine)
    rag_kb_repo = KnowledgeBaseRepository(session_factory=rag_session_factory)
    rag_doc_repo = DocumentRepository(session_factory=rag_session_factory)

    # 向量存储（使用 ChromaDB EphemeralClient 或配置的持久化路径）
    try:
        import chromadb
        chroma_client = chromadb.PersistentClient(path="./data/chroma")
    except Exception:
        import chromadb
        chroma_client = chromadb.EphemeralClient()
    rag_store_manager = ChromaStoreManager(chroma_client)

    # Embedding 注册
    rag_embedding_registry = EmbeddingRegistry()

    # 存储到 app.state
    app.state.rag_kb_repo = rag_kb_repo
    app.state.rag_doc_repo = rag_doc_repo
    app.state.rag_store_manager = rag_store_manager
    app.state.rag_embedding_registry = rag_embedding_registry

    logger.info("RAG components initialized")
except Exception:
    logger.debug("RAG not initialized (missing dependencies)", exc_info=True)
```

**文件**: `src/thumbelina/api/app.py` — 在路由注册部分添加：

```python
from thumbelina.api.routes import rag
# ...
app.include_router(rag.router, prefix="/api/v1")
```

### 5.3 验证

```bash
pytest tests/test_api/test_rag.py -x -q
```

---

## Task 6: Agent RAG 集成

### 6.1 测试先行

在 `tests/test_agent/test_graph.py` 中添加：

```python
class TestAgentRAGIntegration:
    @pytest.mark.asyncio
    async def test_get_rag_context_returns_none_when_no_retriever(self, agent):
        """没有 RAG 组件时应返回 None。"""
        result = await agent._get_rag_context("test query", "0")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_rag_context_with_retriever(self, agent, mock_retriever):
        """有 retriever 时应返回格式化的上下文。"""
        agent.rag_retriever = mock_retriever
        agent.rag_formatter = mock_formatter
        result = await agent._get_rag_context("test query", "0")
        assert result is not None
        assert "相关知识" in result or len(result) > 0
```

### 6.2 实现

**文件**: `src/thumbelina/agent/graph.py`

在 `ThumbelinaAgent.__init__` 中新增参数：

```python
def __init__(
    self,
    # ... existing params ...
    rag_retriever: Any | None = None,
    rag_formatter: Any | None = None,
) -> None:
    # ... existing init ...
    self.rag_retriever = rag_retriever
    self.rag_formatter = rag_formatter
```

新增 `_get_rag_context` 方法：

```python
async def _get_rag_context(
    self, query: str, knowledge_base_id: str
) -> str | None:
    """Retrieve RAG context for the given query from the specified knowledge base."""
    if not knowledge_base_id:
        return None

    # 延迟导入避免循环依赖
    try:
        from thumbelina.rag.embedding.registry import EmbeddingRegistry
        from thumbelina.rag.retrieval.strategies import SimpleRetriever
        from thumbelina.rag.retrieval.context_formatter import ContextFormatter
    except ImportError:
        return None

    # 从 app.state 获取组件（通过闭包或实例属性）
    if not hasattr(self, "_rag_store_manager") or self._rag_store_manager is None:
        return None

    try:
        store = self._rag_store_manager.get_or_create_store(knowledge_base_id)
        embedder = self._rag_embedding_registry.create()
        retriever = SimpleRetriever(embedder=embedder, vector_store=store, top_k=5)
        chunks = retriever.retrieve(query)

        if not chunks:
            return None

        formatter = ContextFormatter()
        context = formatter.format(chunks)
        if context:
            return f"以下是与用户问题相关的知识库内容，请参考回答：\n\n{context}"
    except Exception:
        logger.warning("RAG context retrieval failed", exc_info=True)

    return None
```

在 `run()` 和 `stream()` 中注入 RAG context（在 skill_context 之前）：

```python
# 在 initial_messages 构建中，user_context 之后：
rag_context = None
if self.current_conversation_id and hasattr(self, "_rag_store_manager"):
    # 从 conversation 获取 knowledge_base_id
    if self.memory_manager:
        conv = await self.memory_manager.get_conversation(self.current_conversation_id)
        if conv:
            kb_id = conv.get("knowledge_base_id")
            if kb_id:
                rag_context = await self._get_rag_context(user_input, kb_id)
if rag_context:
    initial_messages.append(SystemMessage(content=rag_context))
```

更新 `clone()` 方法传递 RAG 组件：

```python
def clone(self) -> ThumbelinaAgent:
    cloned = ThumbelinaAgent(
        # ... existing params ...
    )
    cloned._rag_store_manager = getattr(self, "_rag_store_manager", None)
    cloned._rag_embedding_registry = getattr(self, "_rag_embedding_registry", None)
    return cloned
```

### 6.3 验证

```bash
pytest tests/test_agent/test_graph.py -x -q -k "rag"
```

---

## Task 7: WebSocket/HTTP 传递 knowledge_base_id

### 7.1 测试先行

在 `tests/test_api/test_websocket.py` 中验证 RAG 上下文注入：

```python
@pytest.mark.asyncio
async def test_websocket_applies_rag_context(client):
    """当对话绑定知识库时，应注入 RAG 上下文。"""
    # 创建对话并绑定知识库
    # 发送消息并验证 agent._get_rag_context 被调用
    pass  # 具体实现取决于测试基础设施
```

### 7.2 实现

**文件**: `src/thumbelina/api/app.py`

在 agent 创建后，注入 RAG 组件：

```python
# 注入 RAG 组件到 agent
if rag_store_manager and rag_embedding_registry:
    agent._rag_store_manager = rag_store_manager
    agent._rag_embedding_registry = rag_embedding_registry
```

**文件**: `src/thumbelina/api/websocket.py`

无需修改 — RAG 上下文在 agent 内部通过 `current_conversation_id` 自动获取。WebSocket 已经正确设置了 `agent.current_conversation_id`，Agent 会在 `run()`/`stream()` 中自动查找 conversation 的 `knowledge_base_id`。

### 7.3 验证

```bash
pytest tests/test_api/ -x -q
```

---

## Task 8: i18n 添加知识库翻译

### 8.1 实现

**文件**: `frontend/src/i18n/locales/zh-CN.json`

```json
{
  "nav": {
    "knowledgeBase": "知识库"
  },
  "knowledgeBase": {
    "title": "个人知识库",
    "knowledgeBases": "知识库",
    "createKnowledgeBase": "创建知识库",
    "editKnowledgeBase": "编辑知识库",
    "deleteKnowledgeBase": "删除知识库",
    "name": "名称",
    "namePlaceholder": "输入知识库名称",
    "description": "描述",
    "descriptionPlaceholder": "输入知识库描述（可选）",
    "documents": "文档",
    "uploadDocument": "上传文档",
    "dragDropHint": "拖拽文件到此处或点击上传",
    "supportedFormats": "支持格式：.txt, .md",
    "documentName": "文件名",
    "documentType": "类型",
    "chunkCount": "分块数",
    "uploadTime": "上传时间",
    "noDocuments": "暂无文档",
    "noKnowledgeBases": "暂无知识库，点击上方按钮创建",
    "deleteConfirm": "确认删除此知识库？相关文档将被一并删除。",
    "queryTest": "检索测试",
    "queryPlaceholder": "输入测试问题…",
    "runQuery": "检索",
    "queryResults": "检索结果",
    "noQueryResults": "未检索到相关内容",
    "defaultKnowledgeBase": "通用知识库",
    "notUsingKnowledgeBase": "不使用知识库",
    "chooseKnowledgeBase": "为当前对话选择知识库",
    "uploadSuccess": "文档上传成功",
    "uploadFailed": "文档上传失败",
    "deleteSuccess": "删除成功",
    "deleteFailed": "删除失败",
    "createSuccess": "知识库已创建",
    "createFailed": "创建知识库失败",
    "updateSuccess": "知识库已更新",
    "updateFailed": "更新知识库失败",
    "fetchFailed": "加载知识库失败",
    "score": "相似度"
  }
}
```

**文件**: `frontend/src/i18n/locales/en.json`

```json
{
  "nav": {
    "knowledgeBase": "Knowledge"
  },
  "knowledgeBase": {
    "title": "Personal Knowledge Base",
    "knowledgeBases": "Knowledge Bases",
    "createKnowledgeBase": "Create Knowledge Base",
    "editKnowledgeBase": "Edit Knowledge Base",
    "deleteKnowledgeBase": "Delete Knowledge Base",
    "name": "Name",
    "namePlaceholder": "Enter knowledge base name",
    "description": "Description",
    "descriptionPlaceholder": "Enter description (optional)",
    "documents": "Documents",
    "uploadDocument": "Upload Document",
    "dragDropHint": "Drag files here or click to upload",
    "supportedFormats": "Supported: .txt, .md",
    "documentName": "File Name",
    "documentType": "Type",
    "chunkCount": "Chunks",
    "uploadTime": "Upload Time",
    "noDocuments": "No documents yet",
    "noKnowledgeBases": "No knowledge bases. Click the button above to create one.",
    "deleteConfirm": "Delete this knowledge base? All documents will be removed.",
    "queryTest": "Query Test",
    "queryPlaceholder": "Enter a test question…",
    "runQuery": "Search",
    "queryResults": "Query Results",
    "noQueryResults": "No relevant content found",
    "defaultKnowledgeBase": "General Knowledge",
    "notUsingKnowledgeBase": "No knowledge base",
    "chooseKnowledgeBase": "Choose knowledge base for this conversation",
    "uploadSuccess": "Document uploaded",
    "uploadFailed": "Upload failed",
    "deleteSuccess": "Deleted",
    "deleteFailed": "Delete failed",
    "createSuccess": "Knowledge base created",
    "createFailed": "Failed to create knowledge base",
    "updateSuccess": "Knowledge base updated",
    "updateFailed": "Failed to update knowledge base",
    "fetchFailed": "Failed to load knowledge bases",
    "score": "Score"
  }
}
```

### 8.2 验证

```bash
cd frontend && npm run build
```

---

## Task 9: 前端 KnowledgeBasePage — 知识库管理

### 9.1 测试先行

创建 `frontend/src/components/KnowledgeBase/__tests__/KnowledgeBasePage.test.tsx`：

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { KnowledgeBasePage } from '../KnowledgeBasePage'

// Mock fetch
global.fetch = vi.fn()

describe('KnowledgeBasePage', () => {
  it('renders page title', () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 })
    )
    render(<KnowledgeBasePage />)
    expect(screen.getByText(/知识库|Knowledge/i)).toBeInTheDocument()
  })

  it('displays knowledge bases list', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([
        { id: '0', name: '通用知识库', description: '', created_at: '', updated_at: '' },
        { id: 'kb-1', name: '技术文档', description: '技术相关', created_at: '', updated_at: '' },
      ]), { status: 200 })
    )
    render(<KnowledgeBasePage />)
    await waitFor(() => {
      expect(screen.getByText('通用知识库')).toBeInTheDocument()
      expect(screen.getByText('技术文档')).toBeInTheDocument()
    })
  })
})
```

### 9.2 实现

**文件**: `frontend/src/components/KnowledgeBase/KnowledgeBasePage.tsx`

参照 ChannelsPage 或 PluginsPage 的结构模式：

```tsx
import { useState, useEffect, useCallback } from 'react'
import { BookOpen, Plus, Trash2, Edit2, Check, X } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { KnowledgeBase } from '../../types/rag'

export function KnowledgeBasePage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const { t } = useTranslation()

  const fetchKnowledgeBases = useCallback(async () => {
    try {
      const resp = await fetch('/api/v1/rag/knowledge-bases')
      if (resp.ok) {
        const data = await resp.json()
        setKnowledgeBases(Array.isArray(data) ? data : [])
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchKnowledgeBases() }, [fetchKnowledgeBases])

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      const resp = await fetch('/api/v1/rag/knowledge-bases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      })
      if (resp.ok) {
        const kb = await resp.json()
        setKnowledgeBases(prev => [...prev, kb])
        setNewName('')
        setNewDesc('')
        setCreating(false)
        setSelectedId(kb.id)
      }
    } catch { /* ignore */ }
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('knowledgeBase.deleteConfirm'))) return
    try {
      const resp = await fetch(`/api/v1/rag/knowledge-bases/${id}`, { method: 'DELETE' })
      if (resp.ok) {
        setKnowledgeBases(prev => prev.filter(kb => kb.id !== id))
        if (selectedId === id) setSelectedId(null)
      }
    } catch { /* ignore */ }
  }

  const handleUpdate = async (id: string) => {
    try {
      const resp = await fetch(`/api/v1/rag/knowledge-bases/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editName.trim(), description: editDesc.trim() || null }),
      })
      if (resp.ok) {
        const updated = await resp.json()
        setKnowledgeBases(prev => prev.map(kb => kb.id === id ? updated : kb))
        setEditingId(null)
      }
    } catch { /* ignore */ }
  }

  // 渲染结构参照现有页面模式
  return (
    <div className="page-container" data-testid="knowledge-base-page">
      <div className="page-title">
        <BookOpen size={20} />
        {t('knowledgeBase.title')}
      </div>

      <div className="knowledge-base-layout">
        {/* 左侧：知识库列表 */}
        <div className="card knowledge-base-sidebar">
          <div className="card-title">
            {t('knowledgeBase.knowledgeBases')}
            <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
              <Plus size={14} /> {t('knowledgeBase.createKnowledgeBase')}
            </button>
          </div>
          {/* 创建表单、列表项... */}
        </div>

        {/* 右侧：选中知识库的详情（文档管理） */}
        <div className="card knowledge-base-detail">
          {/* 文档管理区域，见 Task 10 */}
        </div>
      </div>
    </div>
  )
}
```

**文件**: `frontend/src/types/rag.ts`

```typescript
export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface RAGDocument {
  id: string
  knowledge_base_id: string
  name: string
  doc_type: string
  chunk_count: number
  created_at: string
}

export interface QueryResultChunk {
  content: string
  score: number
  metadata: string | null
}
```

**文件**: `frontend/src/App.tsx`

```tsx
import { KnowledgeBasePage } from './components/KnowledgeBase/KnowledgeBasePage'

// 在 Page 类型中新增 'knowledge-base'
// 在 renderPage 的 switch 中新增:
case 'knowledge-base':
  return <KnowledgeBasePage />
```

**文件**: `frontend/src/components/Layout/Header.tsx`

```tsx
import { BookOpen } from 'lucide-react'

// Page 类型新增 'knowledge-base'
export type Page = 'chat' | 'tasks' | 'memory' | 'dream' | 'settings' | 'plugins' | 'channels' | 'knowledge-base'

// navKeys 新增
const navKeys: Page[] = ['chat', 'tasks', 'memory', 'dream', 'knowledge-base', 'settings', 'plugins', 'channels']

// NAV_ICONS 新增
'knowledge-base': BookOpen,
```

### 9.3 验证

```bash
cd frontend && npm run test
cd frontend && npm run build
```

---

## Task 10: 前端 KnowledgeBasePage — 文档管理

### 10.1 测试先行

```tsx
it('shows document list for selected knowledge base', async () => {
  // Mock fetch for documents
  vi.mocked(fetch).mockResolvedValueOnce(/* documents list */)
  render(<KnowledgeBasePage />)
  // 选择知识库后应显示文档列表
})
```

### 10.2 实现

在 `KnowledgeBasePage.tsx` 右侧面板中添加文档管理：

```tsx
// 右侧详情面板
const selectedKB = knowledgeBases.find(kb => kb.id === selectedId)

// 文档管理子组件或内联代码：
// - 文档列表表格
// - 文件上传区域（input type="file"，accept=".txt,.md"）
// - 删除按钮
```

文档相关 API 调用：

```typescript
// 获取文档列表
const resp = await fetch(`/api/v1/rag/knowledge-bases/${kbId}/documents`)

// 上传文档
const formData = new FormData()
formData.append('file', file)
const resp = await fetch(`/api/v1/rag/knowledge-bases/${kbId}/documents`, {
  method: 'POST',
  body: formData,
})

// 删除文档
const resp = await fetch(`/api/v1/rag/documents/${docId}`, { method: 'DELETE' })
```

### 10.3 验证

```bash
cd frontend && npm run test
```

---

## Task 11: 前端 KnowledgeBasePage — 检索测试

### 11.1 测试先行

```tsx
it('renders query test panel', () => {
  render(<KnowledgeBasePage />)
  expect(screen.getByPlaceholderText(/测试问题|test question/i)).toBeInTheDocument()
})
```

### 11.2 实现

在右侧面板底部添加检索测试区域：

```tsx
const [queryText, setQueryText] = useState('')
const [queryResults, setQueryResults] = useState<QueryResultChunk[]>([])
const [querying, setQuerying] = useState(false)

const handleQuery = async () => {
  if (!queryText.trim() || !selectedId) return
  setQuerying(true)
  try {
    const resp = await fetch('/api/v1/rag/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: queryText.trim(),
        knowledge_base_id: selectedId,
        top_k: 5,
      }),
    })
    if (resp.ok) {
      const data = await resp.json()
      setQueryResults(data.results || [])
    }
  } catch { /* ignore */ }
  finally { setQuerying(false) }
}
```

结果展示：

```tsx
<div className="card">
  <div className="card-title">{t('knowledgeBase.queryTest')}</div>
  <div className="form-group">
    <input
      className="form-input"
      placeholder={t('knowledgeBase.queryPlaceholder')}
      value={queryText}
      onChange={e => setQueryText(e.target.value)}
      onKeyDown={e => e.key === 'Enter' && handleQuery()}
    />
    <button className="btn btn-primary btn-sm" onClick={handleQuery} disabled={querying}>
      {querying ? t('common.testing') : t('knowledgeBase.runQuery')}
    </button>
  </div>
  {queryResults.length > 0 ? (
    <div className="query-results">
      {queryResults.map((r, i) => (
        <div key={i} className="query-result-item">
          <div className="query-result-score">{t('knowledgeBase.score')}: {(r.score * 100).toFixed(1)}%</div>
          <div className="query-result-content">{r.content}</div>
        </div>
      ))}
    </div>
  ) : (
    <p className="task-empty">{t('knowledgeBase.noQueryResults')}</p>
  )}
</div>
```

### 11.3 验证

```bash
cd frontend && npm run test && npm run build
```

---

## Task 12: 聊天窗口 KnowledgeBaseSelector

### 12.1 测试先行

创建 `frontend/src/components/Chat/__tests__/KnowledgeBaseSelector.test.tsx`：

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { KnowledgeBaseSelector } from '../KnowledgeBaseSelector'

global.fetch = vi.fn()

describe('KnowledgeBaseSelector', () => {
  it('renders trigger button', () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 })
    )
    render(<KnowledgeBaseSelector conversationId="c1" onChange={() => {}} />)
    expect(screen.getByTestId('kb-selector-trigger')).toBeInTheDocument()
  })

  it('shows knowledge base options on click', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([
        { id: '0', name: '通用知识库', description: '', created_at: '', updated_at: '' },
        { id: 'kb-1', name: '技术文档', description: '', created_at: '', updated_at: '' },
      ]), { status: 200 })
    )
    render(<KnowledgeBaseSelector conversationId="c1" onChange={() => {}} />)
    fireEvent.click(screen.getByTestId('kb-selector-trigger'))
    await waitFor(() => {
      expect(screen.getByText('通用知识库')).toBeInTheDocument()
      expect(screen.getByText('技术文档')).toBeInTheDocument()
    })
  })
})
```

### 12.2 实现

**文件**: `frontend/src/components/Chat/KnowledgeBaseSelector.tsx`

参照 `ConversationModelSelector` 的模式：

```tsx
import { useEffect, useRef, useState } from 'react'
import { BookOpen, Check, ChevronDown } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { KnowledgeBase } from '../../types/rag'

interface KnowledgeBaseSelectorProps {
  conversationId?: string
  selectedKnowledgeBaseId?: string | null
  onChange: (knowledgeBaseId: string | null) => void
}

export function KnowledgeBaseSelector({
  conversationId,
  selectedKnowledgeBaseId,
  onChange,
}: KnowledgeBaseSelectorProps) {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    let cancelled = false
    fetch('/api/v1/rag/knowledge-bases')
      .then(res => res.ok ? res.json() : [])
      .then(data => { if (!cancelled) setKnowledgeBases(Array.isArray(data) ? data : []) })
      .catch(() => { if (!cancelled) setKnowledgeBases([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const isNoneSelected = selectedKnowledgeBaseId == null
  const selectedKB = knowledgeBases.find(kb => kb.id === selectedKnowledgeBaseId)
  const label = loading
    ? t('common.loading')
    : isNoneSelected
      ? t('knowledgeBase.notUsingKnowledgeBase')
      : selectedKB?.name || t('knowledgeBase.notUsingKnowledgeBase')

  if (!conversationId) return null

  return (
    <div className="kb-selector" ref={wrapRef} data-testid="kb-selector">
      <button
        type="button"
        className="kb-selector__trigger"
        data-testid="kb-selector-trigger"
        title={t('knowledgeBase.chooseKnowledgeBase')}
        onClick={() => setOpen(o => !o)}
      >
        <BookOpen size={14} />
        <span className="kb-selector__label">{label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <ul className="kb-selector__menu" role="listbox">
          <li
            role="option"
            aria-selected={isNoneSelected}
            className={`kb-selector__option${isNoneSelected ? ' selected' : ''}`}
            onClick={() => { onChange(null); setOpen(false) }}
          >
            <span>{t('knowledgeBase.notUsingKnowledgeBase')}</span>
            {isNoneSelected && <Check size={14} />}
          </li>
          {knowledgeBases.map(kb => {
            const selected = selectedKnowledgeBaseId === kb.id
            return (
              <li
                key={kb.id}
                role="option"
                aria-selected={selected}
                className={`kb-selector__option${selected ? ' selected' : ''}`}
                onClick={() => { onChange(kb.id); setOpen(false) }}
              >
                <span>{kb.name}</span>
                {selected && <Check size={14} />}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
```

**文件**: `frontend/src/components/Chat/ChatWindow.tsx`

在 status bar 中添加 `KnowledgeBaseSelector`（与 ModelSelector 同级）：

```tsx
import { KnowledgeBaseSelector } from './KnowledgeBaseSelector'

// 在 ConversationModelSelector 旁边添加:
{conversationId && (
  <KnowledgeBaseSelector
    conversationId={conversationId}
    selectedKnowledgeBaseId={activeConversation?.knowledge_base_id ?? null}
    onChange={(kbId) => handleSetKnowledgeBase(conversationId, kbId)}
  />
)}
```

**文件**: `frontend/src/types/chat.ts`

在 `Conversation` 接口中新增：

```typescript
knowledge_base_id?: string | null
```

**文件**: `frontend/src/api/conversations.ts`

新增 API 函数：

```typescript
export async function setConversationKnowledgeBase(
  conversationId: string,
  knowledgeBaseId: string | null,
): Promise<Conversation> {
  const res = await fetch(`/api/v1/conversations/${conversationId}/knowledge-base`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ knowledge_base_id: knowledgeBaseId }),
  })
  if (!res.ok) throw new Error('Failed to set knowledge base')
  return res.json()
}
```

**文件**: `frontend/src/App.tsx`

新增 handler 并传递给 ChatWindow：

```tsx
const handleSetKnowledgeBase = useCallback(async (id: string, kbId: string | null) => {
  try {
    const updated = await setConversationKnowledgeBase(id, kbId)
    updateConversationInState(updated)
  } catch { /* ignore */ }
}, [updateConversationInState])

// ChatWindow props 新增:
onSetKnowledgeBase={handleSetKnowledgeBase}
```

### 12.3 验证

```bash
cd frontend && npm run test && npm run build
```

---

## Task 13: 端到端验证与清理

### 13.1 后端全量测试

```bash
pytest tests/ -x -q
ruff check src/ tests/
mypy src/
```

### 13.2 前端全量测试

```bash
cd frontend
npm run test
npm run lint
npm run build
```

### 13.3 手动验证清单

- [ ] 启动服务后，导航栏出现「知识库」入口
- [ ] 可创建、编辑、删除知识库
- [ ] 可上传 .txt/.md 文档到知识库
- [ ] 文档列表正确显示
- [ ] 检索测试可返回结果
- [ ] 聊天窗口 status bar 出现知识库选择器
- [ ] 选择知识库后，对话中能引用知识库内容
- [ ] 选择「不使用知识库」后，对话不走 RAG
- [ ] 切换对话时，知识库选择器自动更新
