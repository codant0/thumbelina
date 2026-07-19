"""向量化模型的抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from thumbelina.rag.knowledge_base.models import Chunk


class EmbeddingModel(ABC):
    """文本向量化模型接口。"""

    @abstractmethod
    def embed(self, chunk: Chunk) -> list[float]:
        """将单段文本编码为向量。"""

    @abstractmethod
    def embed_batch(self, chunks: list[Chunk]) -> list[list[float]]:
        """批量将多段文本编码为向量。"""
