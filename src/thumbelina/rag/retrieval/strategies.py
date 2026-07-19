"""检索策略：从向量库中召回相关文档片段。

规划中的策略
-------------
- SimpleRetriever：基于余弦相似度的 top-k 检索
- MMRRetriever：最大边际相关性（Maximum Marginal Relevance），兼顾相关性与多样性
- HybridRetriever：结合关键词 + 向量检索的混合策略
- ReRankRetriever：用轻量级交叉编码器对 top-k 结果重排序
"""

import torch

from abc import ABC, abstractmethod
from pathlib import Path

import chromadb

from thumbelina.rag.embedding.base import EmbeddingModel
from thumbelina.rag.embedding.hf_provider import HuggingFaceEmbedding
from thumbelina.rag.ingestion.chunker import RecursiveChunker
from thumbelina.rag.ingestion.loader import TextLoader
from thumbelina.rag.knowledge_base.models import Chunk


class Retriever(ABC):
    """向量召回"""

    @abstractmethod
    def retrieve(self, query: str) -> list[Chunk]:
        """根据问题召回向量"""


class SimpleRetriever(Retriever):
    """基于余弦相似度的 top-k 检索。"""

    def __init__(self, embedding_model: EmbeddingModel):
        super().__init__()
        self.embedding_model = embedding_model

    def retrieve(self, query: str, top_k: int = 5) -> list[str]:
        query_embedding = self.embedding_model.embed(query)
        results = self.embedding_model.chromadb_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        return results["documents"][0]


if __name__ == "__main__":
    # 1. 加载
    BASE_DIR = Path(__file__).parent
    TEST_FILE = str(BASE_DIR / ".." / "demo" / "data" / "doc.md")
    loader = TextLoader()
    documents = loader.load(TEST_FILE)
    for i, document in enumerate(documents):
        # 2. 切块
        recursive_chunker = RecursiveChunker()
        chunks = recursive_chunker.chunk(document)

    # 3. 向量化
    chromadb_client = chromadb.EphemeralClient()
    chromadb_collection = chromadb_client.get_or_create_collection(
        name="default",
        embedding_function=None,
        metadata={"hnsw:space": "cosine"})
    embedding_model = HuggingFaceEmbedding(
        chromadb_collection=chromadb_collection)
    embeddings = embedding_model.embed_batch(
        [str(x.content) for x in chunks])
    # 4. 嵌入
    embedding_model.save_embeddings(chunks, embeddings)

    # 5. 向量召回
    query = "哆啦A梦使用的3个秘密道具是什么？"
    retriever = SimpleRetriever(embedding_model)
    results = retriever.retrieve(query)
    for i, result in enumerate(results):
      print(f"result {i + 1}: {result}")