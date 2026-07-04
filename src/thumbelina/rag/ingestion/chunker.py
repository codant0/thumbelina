"""文本分块策略：将长文档拆分为适合检索的片段。

规划中的策略
-------------
- FixedSizeChunker：按固定字符/词元数切分，支持重叠
- RecursiveChunker：递归按分隔符切分（段落 → 句子 → 子句）
- SemanticChunker：利用 embedding 相似度在语义边界处切分
"""
