"""向量化模型的抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence


class EmbeddingModel(ABC):
    """文本向量化模型接口。"""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """将单段文本编码为向量。"""

    @abstractmethod
    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量将多段文本编码为向量。"""
