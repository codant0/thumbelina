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
        chromadb.ClientAPI 实例（PersistentClient 或 EphemeralClient）。
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
        # chromadb >= 0.5 list_collections 可能返回 str 列表或 Collection 对象列表
        if collections and isinstance(collections[0], str):
            return [c for c in collections if c.startswith(_COLLECTION_PREFIX)]
        return [c.name for c in collections if c.name.startswith(_COLLECTION_PREFIX)]
