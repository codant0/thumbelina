"""向量化模型的抽象接口。"""

from __future__ import annotations
import chromadb
from abc import ABC, abstractmethod
from pydantic import BaseModel

from thumbelina.rag.knowledge_base.models import Chunk


class EmbeddingModel(ABC):
    """文本向量化模型接口。"""

    chromadb_collection: chromadb.Collection

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """将单段文本编码为向量。"""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将多段文本编码为向量。"""

    def save_embeddings(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        # 将索引写入向量数据库中，写入内容包含：原始文本内容、向量索引、i
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            self.chromadb_collection.add(
                documents=chunk.content,
                embeddings=[embedding],
                ids=[str(i)],
            )


class VectorQueryResult(BaseModel):
    id: str
    content: str
    embedding: list[float] = []
    distance: float = 0.0

class VectorStore(ABC):
    """向量存储抽象接口"""

    @abstractmethod
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """批量写入文档块及向量"""

    @abstractmethod
    def query(self, embedding: list[float], top_k: int = 5) -> list[VectorQueryResult]:
        """top_k向量召回"""

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """批量删除文档块"""
