"""知识库元数据的持久化层。

提供 KnowledgeBaseRepository 和 DocumentRepository，
管理知识库和文档的 CRUD 操作。所有方法均为 async，
内部通过 asyncio.to_thread 包装同步 SQLAlchemy 调用。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from thumbelina.rag.knowledge_base.orm_models import (
    DocumentRecord,
    KnowledgeBaseRecord,
)
from thumbelina.rag.knowledge_base.simhash import (
    hamming_distance,
    serialize_for_vec,
)

logger = logging.getLogger(__name__)

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
        sha256: bytes,
        sim_hash_64: bytes,
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
            # 同步插入 simhash_index 虚拟表
            self._insert_simhash_index_sync(doc.id, sim_hash_64)
            return doc

    async def create(
        self,
        kb_id: str,
        name: str,
        source_uri: str,
        doc_type: str,
        sha256: bytes,
        sim_hash_64: bytes,
        chunk_count: int = 0,
        doc_id: str | None = None,
    ) -> DocumentRecord:
        """注册文档元数据到指定知识库。"""
        return await asyncio.to_thread(
            self._create_sync,
            kb_id,
            name,
            source_uri,
            doc_type,
            sha256,
            sim_hash_64,
            chunk_count,
            doc_id,
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
            stmt = select(DocumentRecord).where(DocumentRecord.sha256 == sha256).limit(1)
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
        # 清理 simhash_index
        self._delete_simhash_index_sync(doc_id)
        return True

    async def delete(self, doc_id: str) -> bool:
        """删除文档元数据。

        Returns
        -------
        bool
            True 表示成功删除，False 表示不存在。
        """
        return await asyncio.to_thread(self._delete_sync, doc_id)

    def delete_sync(self, doc_id: str) -> bool:
        """同步版删除文档元数据。

        供 ``Indexer`` 等同步上下文直接调用，避免 ``asyncio.run()`` 嵌套问题。

        Returns
        -------
        bool
            True 表示成功删除，False 表示不存在。
        """
        return self._delete_sync(doc_id)

    # ---- delete_by_kb ----

    def _delete_by_kb_sync(self, kb_id: str) -> int:
        with self._get_session() as session:
            stmt = select(DocumentRecord).where(DocumentRecord.knowledge_base_id == kb_id)
            docs = list(session.execute(stmt).scalars().all())
            doc_ids = [doc.id for doc in docs]
            for doc in docs:
                session.delete(doc)
            session.commit()
        # 批量清理 simhash_index
        for doc_id in doc_ids:
            self._delete_simhash_index_sync(doc_id)
        return len(doc_ids)

    async def delete_by_kb(self, kb_id: str) -> int:
        """删除指定知识库下所有文档元数据。

        Returns
        -------
        int
            被删除的文档数量。
        """
        return await asyncio.to_thread(self._delete_by_kb_sync, kb_id)

    # ---- simhash_index 操作 ----

    def _insert_simhash_index_sync(self, doc_id: str, sim_hash_bytes: bytes) -> None:
        """向 simhash_index 虚拟表插入一条记录。"""
        try:
            serialized = serialize_for_vec(sim_hash_bytes)
            with self._get_session() as session:
                session.execute(
                    text(
                        "INSERT OR REPLACE INTO simhash_index"
                        " (document_id, simhash_embedding)"
                        " VALUES (:doc_id, :embedding)"
                    ),
                    {"doc_id": doc_id, "embedding": serialized},
                )
                session.commit()
        except Exception as exc:
            logger.warning("插入 simhash_index 失败 (doc_id=%s): %s", doc_id, exc)

    def _delete_simhash_index_sync(self, doc_id: str) -> None:
        """从 simhash_index 虚拟表中删除指定文档的记录。"""
        try:
            with self._get_session() as session:
                session.execute(
                    text("DELETE FROM simhash_index WHERE document_id = :doc_id"),
                    {"doc_id": doc_id},
                )
                session.commit()
        except Exception as exc:
            logger.warning("删除 simhash_index 记录失败 (doc_id=%s): %s", doc_id, exc)

    # ---- simhash 距离查询 ----

    def _find_by_simhash_sync(
        self,
        query_bytes: bytes,
        threshold: int,
        direction: str,
        kb_id: str | None,
        limit: int,
    ) -> list[tuple[DocumentRecord, int]]:
        """按汉明距离查询文档。内部同步方法。

        simhash_index 使用 float[64] 存储二进制向量，vec0 MATCH 返回 L2 距离。
        对于 0/1 二进制向量，L2² = 汉明距离。
        """
        with self._get_session() as session:
            if direction == "le":
                # 查找相似文档：使用 vec0 MATCH 获取最近邻
                try:
                    import math

                    serialized = serialize_for_vec(query_bytes)
                    # L2 阈值 = sqrt(汉明阈值)
                    l2_threshold = math.sqrt(threshold)

                    rows = session.execute(
                        text(
                            "SELECT document_id, distance FROM simhash_index "
                            "WHERE simhash_embedding MATCH :embedding AND k = :k "
                            "ORDER BY distance"
                        ),
                        {"embedding": serialized, "k": max(limit * 10, 1000)},
                    ).fetchall()

                    # L2 距离转汉明距离：hamming = round(L2²)
                    results: list[tuple[DocumentRecord, int]] = []
                    for row in rows:
                        doc_id = row[0]
                        l2_dist = float(row[1])
                        hamming_dist = round(l2_dist**2)
                        if l2_dist > l2_threshold:
                            break  # 已排序，后续距离更大，可提前终止
                        doc = session.get(DocumentRecord, doc_id)
                        if doc is None:
                            continue
                        if kb_id is not None and doc.knowledge_base_id != kb_id:
                            continue
                        results.append((doc, hamming_dist))
                        if len(results) >= limit:
                            break
                    return results
                except Exception as exc:
                    logger.warning("simhash MATCH 查询失败: %s", exc)
                    return []

            elif direction == "ge":
                # 查找差异文档：全量扫描 + hamming distance 过滤
                stmt = select(DocumentRecord)
                if kb_id is not None:
                    stmt = stmt.where(DocumentRecord.knowledge_base_id == kb_id)
                docs = list(session.execute(stmt).scalars().all())

                results = []
                for doc in docs:
                    distance = hamming_distance(query_bytes, doc.sim_hash_64)
                    if distance >= threshold:
                        results.append((doc, distance))

                # 按距离降序排列（差异最大的排前面）
                results.sort(key=lambda x: x[1], reverse=True)
                return results[:limit]

            else:
                raise ValueError(f"direction 必须为 'le' 或 'ge'，实际为 '{direction}'")

    async def find_by_simhash(
        self,
        query_sim_hash: bytes,
        threshold: int,
        direction: str = "le",
        kb_id: str | None = None,
        limit: int = 100,
    ) -> list[tuple[DocumentRecord, int]]:
        """按汉明距离查询文档。

        Parameters
        ----------
        query_sim_hash:
            8 字节 SimHash blob（大端序）。
        threshold:
            汉明距离阈值，范围 [0, 64]。
        direction:
            "le" = 查找距离 ≤ 阈值的相似文档；
            "ge" = 查找距离 ≥ 阈值的差异文档。
        kb_id:
            可选，限定在某个知识库内查询。
        limit:
            最大返回数量。

        Returns
        -------
        list[tuple[DocumentRecord, int]]
            (文档, 距离) 列表。
        """
        return await asyncio.to_thread(
            self._find_by_simhash_sync, query_sim_hash, threshold, direction, kb_id, limit
        )

    def find_by_simhash_sync(
        self,
        query_sim_hash: bytes,
        threshold: int,
        direction: str = "le",
        kb_id: str | None = None,
        limit: int = 100,
    ) -> list[tuple[DocumentRecord, int]]:
        """同步版 SimHash 查询。

        供 ``DocumentDeduplicator`` 等同步上下文使用，直接调用内部实现。

        Parameters
        ----------
        query_sim_hash:
            8 字节 SimHash blob（大端序）。
        threshold:
            汉明距离阈值，范围 [0, 64]。
        direction:
            "le" = 查找距离 ≤ 阈值的相似文档；
            "ge" = 查找距离 ≥ 阈值的差异文档。
        kb_id:
            可选，限定在某个知识库内查询。
        limit:
            最大返回数量。

        Returns
        -------
        list[tuple[DocumentRecord, int]]
            (文档, 距离) 列表。
        """
        return self._find_by_simhash_sync(query_sim_hash, threshold, direction, kb_id, limit)
