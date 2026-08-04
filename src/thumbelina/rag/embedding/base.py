"""向量化模型的抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from thumbelina.rag.common.models import Chunk


class EmbeddingModel(ABC):
    """文本向量化模型接口。"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """将单段文本编码为向量。"""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将多段文本编码为向量。"""


class ScoredChunk(Chunk):
    """带检索分数的文档片段，继承 Chunk 的全部字段。"""

    score: float = 0.0


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

    @abstractmethod
    def query_by_metadata(self, where: dict[str, str], limit: int = 100) -> list[Chunk]:
        """按元数据条件查询文档块（不涉及向量检索）。

        Parameters
        ----------
        where:
            过滤条件键值对，例如 ``{"document_id": "abc"}``。
        limit:
            最大返回条数，默认 100。
        """

    @abstractmethod
    def delete_by_metadata(self, where: dict[str, str]) -> int:
        """按元数据条件批量删除文档块。

        Returns
        -------
        int
            实际删除的文档块数量。
        """
