"""向量化模型的抽象接口。"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import NamedTuple
from pydantic import BaseModel

from thumbelina.rag.knowledge_base.models import Chunk


class EmbeddingModel(ABC):
    """文本向量化模型接口。"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """将单段文本编码为向量。"""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将多段文本编码为向量。"""


class ScoredChunk(NamedTuple):
    chunk: Chunk
    score: float


class VectorStore(ABC):
    """向量存储抽象接口"""

    @abstractmethod
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """批量写入文档块及向量"""

    @abstractmethod
    def query(self, embedding: list[float], top_k: int = 5) -> list[ScoredChunk]:
        """top_k向量召回"""

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """批量删除文档块"""
