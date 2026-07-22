# 多知识库管理 — 实施计划

**日期**: 2026-07-22
**设计文档**: `docs/plans/2026-07-22-multi-knowledge-base-design.md`

## 任务概览

| # | 任务 | 预计时间 | 依赖 |
|---|------|---------|------|
| 1 | ORM 模型定义 | 3 min | — |
| 2 | 数据库初始化层 | 3 min | Task 1 |
| 3 | KnowledgeBaseRepository | 5 min | Task 2 |
| 4 | DocumentRepository | 5 min | Task 2 |
| 5 | ChromaStoreManager | 4 min | — |
| 6 | 修正 Pydantic 模型 | 2 min | — |
| 7 | 集成测试 + 清理 | 5 min | Task 1-6 |

---

## Task 1: ORM 模型定义

**文件**: `src/thumbelina/rag/knowledge_base/orm_models.py`

### 1.1 测试先行

创建 `tests/test_rag/test_orm_models.py`：

```python
"""Tests for RAG SQLAlchemy ORM models."""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from thumbelina.rag.knowledge_base.orm_models import RagBase, KnowledgeBaseRecord, DocumentRecord


class TestRagBase:
    def test_independent_from_memory_base(self):
        """RAG Base 应独立于 memory 模块的 Base。"""
        from thumbelina.memory.models import Base as MemoryBase
        assert RagBase is not MemoryBase

    def test_tables_created(self):
        engine = create_engine("sqlite:///:memory:")
        RagBase.metadata.create_all(engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        assert "knowledge_bases" in table_names
        assert "rag_documents" in table_names


class TestKnowledgeBaseRecord:
    def test_create_default(self):
        engine = create_engine("sqlite:///:memory:")
        RagBase.metadata.create_all(engine)
        with Session(engine) as session:
            kb = KnowledgeBaseRecord(id="0", name="通用知识库")
            session.add(kb)
            session.commit()
            assert kb.created_at is not None
            assert kb.updated_at is not None

    def test_fields(self):
        kb = KnowledgeBaseRecord(id="kb-1", name="技术文档", description="技术相关")
        assert kb.id == "kb-1"
        assert kb.name == "技术文档"
        assert kb.description == "技术相关"


class TestDocumentRecord:
    def test_create(self):
        engine = create_engine("sqlite:///:memory:")
        RagBase.metadata.create_all(engine)
        with Session(engine) as session:
            kb = KnowledgeBaseRecord(id="0", name="通用知识库")
            session.add(kb)
            doc = DocumentRecord(
                id="doc-1", knowledge_base_id="0",
                name="test.md", source_uri="/tmp/test.md",
                doc_type=".md", chunk_count=5,
            )
            session.add(doc)
            session.commit()
            assert doc.created_at is not None

    def test_default_chunk_count(self):
        doc = DocumentRecord(
            id="doc-2", knowledge_base_id="0",
            name="a.txt", source_uri="/a.txt", doc_type=".txt",
        )
        assert doc.chunk_count == 0
```

### 1.2 实现

`src/thumbelina/rag/knowledge_base/orm_models.py`：

```python
"""RAG 模块独立的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class RagBase(DeclarativeBase):
    """RAG 模块专用的 Base，独立于 memory 模块。"""
    pass


class KnowledgeBaseRecord(RagBase):
    """知识库表。"""
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBaseRecord(id={self.id!r}, name={self.name!r})>"


class DocumentRecord(RagBase):
    """文档元数据表。"""
    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<DocumentRecord(id={self.id!r}, name={self.name!r})>"
```

### 1.3 验证

运行 `pytest tests/test_rag/test_orm_models.py -x -q`，确保全绿。

---

## Task 2: 数据库初始化层

**文件**: `src/thumbelina/rag/knowledge_base/db.py`

### 2.1 测试先行

在 `tests/test_rag/test_repository.py` 中添加 `TestRagDb` 部分：

```python
"""Tests for RAG database initialization and repositories."""
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from thumbelina.rag.knowledge_base.db import init_rag_db
from thumbelina.rag.knowledge_base.orm_models import KnowledgeBaseRecord, RagBase


class TestRagDb:
    def test_init_creates_tables(self):
        engine = create_engine("sqlite:///:memory:")
        session_factory = init_rag_db(engine)
        inspector = inspect(engine)
        assert "knowledge_bases" in inspector.get_table_names()
        assert "rag_documents" in inspector.get_table_names()

    def test_init_seeds_default_knowledge_base(self):
        engine = create_engine("sqlite:///:memory:")
        init_rag_db(engine)
        with Session(engine) as session:
            kb = session.get(KnowledgeBaseRecord, "0")
            assert kb is not None
            assert kb.name == "通用知识库"

    def test_init_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        init_rag_db(engine)
        init_rag_db(engine)  # 第二次不应报错
        with Session(engine) as session:
            kbs = session.execute(select(KnowledgeBaseRecord)).scalars().all()
            assert len(kbs) == 1  # 不应重复创建
```

### 2.2 实现

`src/thumbelina/rag/knowledge_base/db.py`：

```python
"""RAG 模块数据库引擎和初始化。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.rag.knowledge_base.orm_models import (
    KnowledgeBaseRecord,
    RagBase,
)

_DEFAULT_KB_ID = "0"
_DEFAULT_KB_NAME = "通用知识库"
_DEFAULT_KB_DESC = "通用知识库，默认使用该知识库"


def init_rag_db(engine: Engine) -> sessionmaker[Session]:
    """创建 RAG 表并植入默认知识库，返回会话工厂。"""
    RagBase.metadata.create_all(engine)
    _ensure_default_knowledge_base(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_default_knowledge_base(engine: Engine) -> None:
    """如果 id='0' 的通用知识库不存在则自动创建。"""
    with Session(engine) as session:
        existing = session.get(KnowledgeBaseRecord, _DEFAULT_KB_ID)
        if existing is None:
            session.add(
                KnowledgeBaseRecord(
                    id=_DEFAULT_KB_ID,
                    name=_DEFAULT_KB_NAME,
                    description=_DEFAULT_KB_DESC,
                )
            )
            session.commit()
```

### 2.3 验证

运行 `pytest tests/test_rag/test_repository.py::TestRagDb -x -q`。

---

## Task 3: KnowledgeBaseRepository

**文件**: `src/thumbelina/rag/knowledge_base/repository.py`（重写）

### 3.1 测试先行

在 `tests/test_rag/test_repository.py` 中添加 `TestKnowledgeBaseRepository`：

```python
class TestKnowledgeBaseRepository:
    @pytest.fixture
    def repo(self):
        engine = create_engine("sqlite:///:memory:")
        sf = init_rag_db(engine)
        return KnowledgeBaseRepository(session_factory=sf)

    @pytest.mark.asyncio
    async def test_list_all_includes_default(self, repo):
        kbs = await repo.list_all()
        assert len(kbs) == 1
        assert kbs[0].id == "0"

    @pytest.mark.asyncio
    async def test_create_and_get(self, repo):
        kb = await repo.create("kb-1", "技术文档", "技术相关文档")
        assert kb.id == "kb-1"
        fetched = await repo.get("kb-1")
        assert fetched is not None
        assert fetched.name == "技术文档"

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, repo):
        await repo.create("kb-1", "A", "")
        with pytest.raises(ValueError, match="已存在"):
            await repo.create("kb-1", "B", "")

    @pytest.mark.asyncio
    async def test_update(self, repo):
        await repo.create("kb-1", "A", "desc")
        updated = await repo.update("kb-1", name="B", description="new desc")
        assert updated.name == "B"
        assert updated.description == "new desc"

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, repo):
        with pytest.raises(ValueError, match="不存在"):
            await repo.update("no-such", name="X")

    @pytest.mark.asyncio
    async def test_delete(self, repo):
        await repo.create("kb-1", "A", "")
        result = await repo.delete("kb-1")
        assert result is True
        assert await repo.get("kb-1") is None

    @pytest.mark.asyncio
    async def test_delete_default_raises(self, repo):
        with pytest.raises(ValueError, match="不可删除"):
            await repo.delete("0")

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo):
        result = await repo.delete("no-such")
        assert result is False
```

### 3.2 实现

```python
"""知识库元数据的持久化层。"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.rag.knowledge_base.orm_models import KnowledgeBaseRecord

_DEFAULT_KB_ID = "0"


class KnowledgeBaseRepository:
    """知识库 CRUD 操作。

    Parameters
    ----------
    session_factory:
        由 ``init_rag_db()`` 返回的 SQLAlchemy sessionmaker。
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        return self._session_factory()

    # ---- create ----
    def _create_sync(self, id: str, name: str, description: str | None = None) -> KnowledgeBaseRecord:
        with self._get_session() as session:
            existing = session.get(KnowledgeBaseRecord, id)
            if existing is not None:
                raise ValueError(f"知识库 {id} 已存在")
            kb = KnowledgeBaseRecord(id=id, name=name, description=description)
            session.add(kb)
            session.commit()
            session.refresh(kb)
            return kb

    async def create(self, id: str, name: str, description: str | None = None) -> KnowledgeBaseRecord:
        return await asyncio.to_thread(self._create_sync, id, name, description)

    # ---- get ----
    def _get_sync(self, id: str) -> KnowledgeBaseRecord | None:
        with self._get_session() as session:
            return session.get(KnowledgeBaseRecord, id)

    async def get(self, id: str) -> KnowledgeBaseRecord | None:
        return await asyncio.to_thread(self._get_sync, id)

    # ---- list_all ----
    def _list_all_sync(self) -> list[KnowledgeBaseRecord]:
        with self._get_session() as session:
            stmt = select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.created_at)
            return list(session.execute(stmt).scalars().all())

    async def list_all(self) -> list[KnowledgeBaseRecord]:
        return await asyncio.to_thread(self._list_all_sync)

    # ---- update ----
    def _update_sync(self, id: str, name: str | None = None, description: str | None = None) -> KnowledgeBaseRecord:
        with self._get_session() as session:
            kb = session.get(KnowledgeBaseRecord, id)
            if kb is None:
                raise ValueError(f"知识库 {id} 不存在")
            if name is not None:
                kb.name = name
            if description is not None:
                kb.description = description
            session.commit()
            session.refresh(kb)
            return kb

    async def update(self, id: str, name: str | None = None, description: str | None = None) -> KnowledgeBaseRecord:
        return await asyncio.to_thread(self._update_sync, id, name, description)

    # ---- delete ----
    def _delete_sync(self, id: str) -> bool:
        if id == _DEFAULT_KB_ID:
            raise ValueError("通用知识库不可删除")
        with self._get_session() as session:
            kb = session.get(KnowledgeBaseRecord, id)
            if kb is None:
                return False
            session.delete(kb)
            session.commit()
            return True

    async def delete(self, id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, id)
```

### 3.3 验证

运行 `pytest tests/test_rag/test_repository.py::TestKnowledgeBaseRepository -x -q`。

---

## Task 4: DocumentRepository

**文件**: 在 `repository.py` 中追加（同一文件）

### 4.1 测试先行

在 `tests/test_rag/test_repository.py` 中添加 `TestDocumentRepository`：

```python
class TestDocumentRepository:
    @pytest.fixture
    def repos(self):
        engine = create_engine("sqlite:///:memory:")
        sf = init_rag_db(engine)
        return KnowledgeBaseRepository(session_factory=sf), DocumentRepository(session_factory=sf)

    @pytest.mark.asyncio
    async def test_create_and_get(self, repos):
        _, doc_repo = repos
        doc = await doc_repo.create("0", "test.md", "/tmp/test.md", ".md", 10)
        fetched = await doc_repo.get(doc.id)
        assert fetched is not None
        assert fetched.name == "test.md"
        assert fetched.chunk_count == 10

    @pytest.mark.asyncio
    async def test_list_by_kb(self, repos):
        _, doc_repo = repos
        await doc_repo.create("0", "a.md", "/a.md", ".md")
        await doc_repo.create("0", "b.txt", "/b.txt", ".txt")
        docs = await doc_repo.list_by_kb("0")
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_delete(self, repos):
        _, doc_repo = repos
        doc = await doc_repo.create("0", "a.md", "/a.md", ".md")
        result = await doc_repo.delete(doc.id)
        assert result is True
        assert await doc_repo.get(doc.id) is None

    @pytest.mark.asyncio
    async def test_delete_by_kb(self, repos):
        _, doc_repo = repos
        await doc_repo.create("0", "a.md", "/a.md", ".md")
        await doc_repo.create("0", "b.txt", "/b.txt", ".txt")
        count = await doc_repo.delete_by_kb("0")
        assert count == 2
        assert len(await doc_repo.list_by_kb("0")) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repos):
        _, doc_repo = repos
        result = await doc_repo.delete("no-such")
        assert result is False
```

### 4.2 实现

在 `repository.py` 末尾追加 `DocumentRepository`：

```python
from thumbelina.rag.knowledge_base.orm_models import DocumentRecord


class DocumentRepository:
    """文档元数据 CRUD 操作。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        return self._session_factory()

    # ---- create ----
    def _create_sync(
        self, kb_id: str, name: str, source_uri: str, doc_type: str, chunk_count: int = 0
    ) -> DocumentRecord:
        import uuid
        with self._get_session() as session:
            doc = DocumentRecord(
                id=uuid.uuid4().hex,
                knowledge_base_id=kb_id,
                name=name,
                source_uri=source_uri,
                doc_type=doc_type,
                chunk_count=chunk_count,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc

    async def create(
        self, kb_id: str, name: str, source_uri: str, doc_type: str, chunk_count: int = 0
    ) -> DocumentRecord:
        return await asyncio.to_thread(
            self._create_sync, kb_id, name, source_uri, doc_type, chunk_count
        )

    # ---- get ----
    def _get_sync(self, doc_id: str) -> DocumentRecord | None:
        with self._get_session() as session:
            return session.get(DocumentRecord, doc_id)

    async def get(self, doc_id: str) -> DocumentRecord | None:
        return await asyncio.to_thread(self._get_sync, doc_id)

    # ---- list_by_kb ----
    def _list_by_kb_sync(self, kb_id: str) -> list[DocumentRecord]:
        with self._get_session() as session:
            stmt = (
                select(DocumentRecord)
                .where(DocumentRecord.knowledge_base_id == kb_id)
                .order_by(DocumentRecord.created_at)
            )
            return list(session.execute(stmt).scalars().all())

    async def list_by_kb(self, kb_id: str) -> list[DocumentRecord]:
        return await asyncio.to_thread(self._list_by_kb_sync, kb_id)

    # ---- delete ----
    def _delete_sync(self, doc_id: str) -> bool:
        with self._get_session() as session:
            doc = session.get(DocumentRecord, doc_id)
            if doc is None:
                return False
            session.delete(doc)
            session.commit()
            return True

    async def delete(self, doc_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, doc_id)

    # ---- delete_by_kb ----
    def _delete_by_kb_sync(self, kb_id: str) -> int:
        with self._get_session() as session:
            stmt = select(DocumentRecord).where(DocumentRecord.knowledge_base_id == kb_id)
            docs = list(session.execute(stmt).scalars().all())
            for doc in docs:
                session.delete(doc)
            session.commit()
            return len(docs)

    async def delete_by_kb(self, kb_id: str) -> int:
        return await asyncio.to_thread(self._delete_by_kb_sync, kb_id)
```

### 4.3 验证

运行 `pytest tests/test_rag/test_repository.py -x -q`，确保全绿。

---

## Task 5: ChromaStoreManager

**文件**: `src/thumbelina/rag/embedding/store_manager.py`

### 5.1 测试先行

创建 `tests/test_rag/test_embedding/test_store_manager.py`：

```python
"""Tests for ChromaStoreManager."""
import pytest
import chromadb
from thumbelina.rag.embedding.store_manager import ChromaStoreManager
from thumbelina.rag.embedding.vector_chroma import ChromaVectorStore


class TestChromaStoreManager:
    @pytest.fixture
    def manager(self):
        client = chromadb.EphemeralClient()
        return ChromaStoreManager(client)

    def test_get_or_create_store(self, manager):
        store = manager.get_or_create_store("0")
        assert isinstance(store, ChromaVectorStore)

    def test_get_same_store_returns_same(self, manager):
        store1 = manager.get_or_create_store("0")
        store2 = manager.get_or_create_store("0")
        assert store1.collection.name == store2.collection.name

    def test_different_kb_different_collection(self, manager):
        store0 = manager.get_or_create_store("0")
        store1 = manager.get_or_create_store("kb-1")
        assert store0.collection.name != store1.collection.name

    def test_collection_naming(self, manager):
        store = manager.get_or_create_store("kb-42")
        assert store.collection.name == "rag_kb_kb-42"

    def test_delete_store(self, manager):
        manager.get_or_create_store("kb-1")
        manager.delete_store("kb-1")
        # 删除后重新创建应该成功（新 collection）
        store = manager.get_or_create_store("kb-1")
        assert store is not None

    def test_list_stores(self, manager):
        manager.get_or_create_store("0")
        manager.get_or_create_store("kb-1")
        names = manager.list_stores()
        assert "rag_kb_0" in names
        assert "rag_kb_kb-1" in names
```

### 5.2 实现

`src/thumbelina/rag/embedding/store_manager.py`：

```python
"""ChromaDB 多知识库 Collection 管理。"""

from __future__ import annotations

import chromadb

from thumbelina.rag.embedding.vector_chroma import ChromaVectorStore

_COLLECTION_PREFIX = "rag_kb_"


class ChromaStoreManager:
    """管理每个知识库对应的 ChromaDB Collection。

    Parameters
    ----------
    client:
        chromadb.Client 实例（PersistentClient 或 EphemeralClient）。
    """

    def __init__(self, client: chromadb.ClientAPI) -> None:
        self._client = client
        self._stores: dict[str, ChromaVectorStore] = {}

    def get_or_create_store(self, kb_id: str) -> ChromaVectorStore:
        """获取或创建指定知识库的向量存储。"""
        if kb_id in self._stores:
            return self._stores[kb_id]

        collection = self._client.get_or_create_collection(
            name=f"{_COLLECTION_PREFIX}{kb_id}",
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )
        store = ChromaVectorStore(collection)
        self._stores[kb_id] = store
        return store

    def delete_store(self, kb_id: str) -> None:
        """删除指定知识库的 Collection。"""
        name = f"{_COLLECTION_PREFIX}{kb_id}"
        try:
            self._client.delete_collection(name)
        except Exception:
            pass  # collection 不存在时忽略
        self._stores.pop(kb_id, None)

    def list_stores(self) -> list[str]:
        """列出所有 RAG 知识库 Collection 名称。"""
        collections = self._client.list_collections()
        # chromadb >= 0.5 list_collections 返回 str 列表
        if collections and isinstance(collections[0], str):
            return [c for c in collections if c.startswith(_COLLECTION_PREFIX)]
        return [c.name for c in collections if c.name.startswith(_COLLECTION_PREFIX)]
```

### 5.3 验证

运行 `pytest tests/test_rag/test_embedding/test_store_manager.py -x -q`。

---

## Task 6: 修正 Pydantic 模型

**文件**: `src/thumbelina/rag/knowledge_base/models.py`

### 6.1 修改

```python
class KnowledgeBase(BaseModel):
    """知识库分组。"""
    id: str = "0"          # 修正：str = 0 → str = "0"
    name: str = '通用知识库'
    description: str = '通用知识库，默认使用该知识库'
```

### 6.2 修正测试

`tests/test_rag/test_knowledge_base_models.py` 中 `TestKnowledgeBase.test_default_values` 需要适配：

```python
def test_default_values(self):
    kb = KnowledgeBase()
    assert kb.id == "0"      # 原来是 0（int）
    assert kb.name == "通用知识库"
```

### 6.3 验证

运行 `pytest tests/test_rag/test_knowledge_base_models.py -x -q`。

---

## Task 7: 集成验证 + 更新导出

### 7.1 更新 `__init__.py` 导出

更新 `src/thumbelina/rag/knowledge_base/__init__.py`：

```python
"""知识库子模块：管理已索引文档的集合。"""

from thumbelina.rag.knowledge_base.models import (
    Chunk, Document, DocumentType, KnowledgeBase,
)
from thumbelina.rag.knowledge_base.orm_models import (
    DocumentRecord, KnowledgeBaseRecord, RagBase,
)
from thumbelina.rag.knowledge_base.repository import (
    DocumentRepository, KnowledgeBaseRepository,
)
from thumbelina.rag.knowledge_base.db import init_rag_db

__all__ = [
    "Chunk", "Document", "DocumentType", "KnowledgeBase",
    "DocumentRecord", "KnowledgeBaseRecord", "RagBase",
    "DocumentRepository", "KnowledgeBaseRepository",
    "init_rag_db",
]
```

### 7.2 全量测试

```bash
pytest tests/test_rag/ -x -q
```

### 7.3 Lint + Type Check

```bash
ruff check src/thumbelina/rag/knowledge_base/ src/thumbelina/rag/embedding/store_manager.py
mypy src/thumbelina/rag/knowledge_base/
```
