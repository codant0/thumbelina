"""检索策略：从向量库中召回相关文档片段。

规划中的策略
-------------
- SimpleRetriever：基于余弦相似度的 top-k 检索
- MMRRetriever：最大边际相关性（Maximum Marginal Relevance），兼顾相关性与多样性
- HybridRetriever：结合关键词 + 向量检索的混合策略
- ReRankRetriever：用轻量级交叉编码器对 top-k 结果重排序
"""

from abc import ABC, abstractmethod

from thumbelina.rag.embedding.base import EmbeddingModel, ScoredChunk, VectorStore
from thumbelina.rag.common.models import Chunk


class Retriever(ABC):
    """向量召回"""

    @abstractmethod
    def retrieve(self, query: str) -> list[Chunk]:
        """根据问题召回向量"""


class SimpleRetriever(Retriever):
    """基于余弦相似度的 top-k 检索。"""

    def __init__(self, embedding_model: EmbeddingModel, vector_store: VectorStore):
        super().__init__()
        self.embedding_model = embedding_model
        self.vector_store = vector_store

    def retrieve(self, query: str, top_k: int = 5) -> list[ScoredChunk]:
        query_embedding = self.embedding_model.embed(query)
        results = self.vector_store.query(embedding=query_embedding, top_k=top_k)
        return results
