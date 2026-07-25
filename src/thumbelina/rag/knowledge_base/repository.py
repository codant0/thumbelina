"""知识库元数据的持久化层。

提供 KnowledgeBaseRepository 和 DocumentRepository，
管理知识库和文档的 CRUD 操作。所有方法均为 async，
内部通过 asyncio.to_thread 包装同步 SQLAlchemy 调用。
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.rag.knowledge_base.orm_models import (
    DocumentRecord,
    KnowledgeBaseRecord,
)

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

    def _create_sync(
        self, id: str, name: str, description: str | None = None
    ) -> KnowledgeBaseRecord:
        with self._get_session() as session:
            existing = session.get(KnowledgeBaseRecord, id)
            if existing is not None:
                raise ValueError(f"知识库 {id} 已存在")
            kb = KnowledgeBaseRecord(id=id, name=name, description=description)
            session.add(kb)
            session.commit()
            session.refresh(kb)
            return kb

    async def create(
        self, id: str, name: str, description: str | None = None
    ) -> KnowledgeBaseRecord:
        """创建知识库。

        Raises
        ------
        ValueError
            如果 id 已存在。
        """
        return await asyncio.to_thread(self._create_sync, id, name, description)

    # ---- get ----

    def _get_sync(self, id: str) -> KnowledgeBaseRecord | None:
        with self._get_session() as session:
            return session.get(KnowledgeBaseRecord, id)

    async def get(self, id: str) -> KnowledgeBaseRecord | None:
        """按 ID 获取知识库，不存在返回 None。"""
        return await asyncio.to_thread(self._get_sync, id)

    # ---- list_all ----

    def _list_all_sync(self) -> list[KnowledgeBaseRecord]:
        with self._get_session() as session:
            stmt = select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.created_at)
            return list(session.execute(stmt).scalars().all())

    async def list_all(self) -> list[KnowledgeBaseRecord]:
        """列出所有知识库。"""
        return await asyncio.to_thread(self._list_all_sync)

    # ---- update ----

    def _update_sync(
        self, id: str, name: str | None = None, description: str | None = None
    ) -> KnowledgeBaseRecord:
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

    async def update(
        self, id: str, name: str | None = None, description: str | None = None
    ) -> KnowledgeBaseRecord:
        """更新知识库属性。

        Raises
        ------
        ValueError
            如果知识库不存在。
        """
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
        """删除知识库。

        Returns
        -------
        bool
            True 表示成功删除，False 表示不存在。

        Raises
        ------
        ValueError
            如果尝试删除 id="0" 的通用知识库。
        """
        return await asyncio.to_thread(self._delete_sync, id)


class DocumentRepository:
    """文档元数据 CRUD 操作。

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

    def _create_sync(
        self,
        kb_id: str,
        name: str,
        source_uri: str,
        doc_type: str,
        sha256: str,
        sim_hash_64: str,
        chunk_count: int = 0,
        doc_id: str | None = None,
    ) -> DocumentRecord:
        with self._get_session() as session:
            doc = DocumentRecord(
                id=doc_id or uuid.uuid4().hex,
                knowledge_base_id=kb_id,
                name=name,
                source_uri=source_uri,
                doc_type=doc_type,
                sha256=sha256,
                sim_hash_64=sim_hash_64,
                chunk_count=chunk_count,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc

    async def create(
        self,
        kb_id: str,
        name: str,
        source_uri: str,
        doc_type: str,
        sha256: str,
        sim_hash_64: str,
        chunk_count: int = 0,
        doc_id: str | None = None,
    ) -> DocumentRecord:
        """注册文档元数据到指定知识库。"""
        return await asyncio.to_thread(
            self._create_sync, kb_id, name, source_uri, doc_type, sha256, sim_hash_64, chunk_count, doc_id
        )

    # ---- get ----

    def _get_sync(self, doc_id: str) -> DocumentRecord | None:
        with self._get_session() as session:
            return session.get(DocumentRecord, doc_id)

    async def get(self, doc_id: str) -> DocumentRecord | None:
        """按 ID 获取文档，不存在返回 None。"""
        return await asyncio.to_thread(self._get_sync, doc_id)
    
    def _get_by_sha256(self, sha256: bytes) -> DocumentRecord:
        with self._get_session() as session:
            stmt = (
                select(DocumentRecord)
                .where(DocumentRecord.sha256 == sha256)
                .limit(1)
            )
            return session.execute(stmt).scalar()

    async def get_by_sha256(self, sha256: bytes) -> DocumentRecord:
        """根据sha256值获取知识库"""
        return await asyncio.to_thread(self._get_by_sha256, sha256)


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
        """列出指定知识库的所有文档。"""
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
        """删除文档元数据。

        Returns
        -------
        bool
            True 表示成功删除，False 表示不存在。
        """
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
        """删除指定知识库下所有文档元数据。

        Returns
        -------
        int
            被删除的文档数量。
        """
        return await asyncio.to_thread(self._delete_by_kb_sync, kb_id)
