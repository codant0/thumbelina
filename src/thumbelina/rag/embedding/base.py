"""向量化模型的抽象接口。"""

from __future__ import annotations
import chromadb
from abc import ABC, abstractmethod
from collections.abc import Sequence

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
