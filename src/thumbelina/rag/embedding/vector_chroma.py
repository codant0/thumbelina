"""chromadb 向量存储实现"""

import chromadb

from thumbelina.rag.embedding.base import ScoredChunk, VectorStore
from thumbelina.rag.knowledge_base.models import Chunk


class ChromaVectorStore(VectorStore):
    def __init__(self, collection: chromadb.Collection):
        super().__init__()
        self.collection = collection

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return

        ids = []
        documents = []
        metadatas = []

        for chunk in chunks:
            ids.append(chunk.id)
            documents.append(chunk.content)
            # ChromaDB metadata 必须是 dict，值只能是 str/int/float/bool
            metadatas.append({
                "document_id": chunk.document_id,
                "knowledge_base_id": chunk.knowledge_base_id,
                "metadata": chunk.metadata,  # JSON 字符串，直接存储
            })

        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(self, embedding: list[float], top_k: int = 5) -> list[ScoredChunk]:
        """查询返回完整信息（文本 + 元数据 + 分数）。"""
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        chunks: list[ScoredChunk] = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            chunks.append(ScoredChunk(
                id=results["ids"][0][i],
                content=results["documents"][0][i],
                document_id=meta.get("document_id", ""),
                knowledge_base_id=meta.get("knowledge_base_id", ""),
                metadata=meta.get("metadata", "{}"),
                score=1 - results["distances"][0][i],
            ))
        return chunks

    def delete(self, ids: list[str]) -> None:
        if ids:
            self.collection.delete(ids=ids)

    def query_by_metadata(self, where: dict[str, str], limit: int = 100) -> list[Chunk]:
        """按元数据条件查询文档块。"""
        results = self.collection.get(
            where=where,
            include=["documents", "metadatas"],
            limit=limit,
        )
        chunks: list[Chunk] = []
        for i in range(len(results["ids"])):
            meta = results["metadatas"][i]
            chunks.append(Chunk(
                id=results["ids"][i],
                content=results["documents"][i],
                document_id=meta.get("document_id", ""),
                knowledge_base_id=meta.get("knowledge_base_id", ""),
                metadata=meta.get("metadata", "{}"),
            ))
        return chunks

    def delete_by_metadata(self, where: dict[str, str]) -> int:
        """按元数据条件批量删除文档块，返回删除数量。"""
        results = self.collection.get(where=where, include=[])
        ids = results["ids"]
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)
