"""文档索引流水线。

协调完整的文档处理流程：

    1. 加载原始文档（loader）
    2. 切分为片段（chunker）
    3. 为每个片段生成向量（embedding model）
    4. 将向量 + 元数据写入向量库（vector store）

规划中的接口
------------
    indexer = Indexer(loader, chunker, embedder, vector_store)
    doc_id = await indexer.index("path/to/document.pdf")
"""
