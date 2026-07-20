"""chromadb 向量存储实现"""

import chromadb
from thumbelina.rag.embedding.base import VectorQueryResult, VectorStore
from thumbelina.rag.knowledge_base.models import Chunk


class ChromaVectorStore(VectorStore):
    def __init__(self, collection: chromadb.Collection):
        super().__init__()
        self.collection = collection

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.collection.add(
            documents=[c.content for c in chunks],
            embeddings=embeddings,
            ids=[c.id for c in chunks],
        )

    def query(self, embedding: list[float], top_k: int = 5) -> list[VectorQueryResult]:
        results = self.collection.query(
            query_embeddings=embedding,
            n_results=top_k,
            include=["documents", "embeddings", "distances"],
        )
        return [
            VectorQueryResult(id=id_, content=doc, embedding=emb, distance=dist)
            for id_, doc, emb, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["embeddings"][0],
                results["distances"][0],
            )
        ]

    def delete(self, ids: list[str]) -> None:
        return super().delete(ids)
