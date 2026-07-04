"""检索策略：从向量库中召回相关文档片段。

规划中的策略
-------------
- SimpleRetriever：基于余弦相似度的 top-k 检索
- MMRRetriever：最大边际相关性（Maximum Marginal Relevance），兼顾相关性与多样性
- HybridRetriever：结合关键词 + 向量检索的混合策略
- ReRankRetriever：用轻量级交叉编码器对 top-k 结果重排序
"""
