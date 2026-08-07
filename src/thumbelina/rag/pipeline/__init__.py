"""编排流水线子模块：协调完整的 RAG 索引流程。

规划中的模块
---------------
indexer.py — 协调「加载 → 分块 → 向量化 → 存储」的完整流水线
"""

from thumbelina.rag.pipeline.indexer import Indexer, IndexStats

__all__ = ["Indexer", "IndexStats"]
