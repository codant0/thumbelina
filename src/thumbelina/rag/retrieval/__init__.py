"""检索策略与上下文构建。

规划中的模块
---------------
strategies.py        — 多种检索算法（简单 top-k、MMR、混合检索、重排序）
context_formatter.py — 将检索到的文档片段格式化为 LLM 可用的上下文
"""

from thumbelina.rag.retrieval.context_formatter import ContextFormatter

__all__ = ["ContextFormatter"]
