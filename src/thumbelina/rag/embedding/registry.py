"""Embedding 模型注册中心。

规划中的提供者
--------------
- OpenAIEmbedding：text-embedding-3-small / text-embedding-3-large
- HuggingFaceEmbedding：通过 sentence-transformers 使用本地模型
- OllamaEmbedding：Ollama 本地部署方案，完全离线

用法示例
--------
    model = get_embedding_model("openai/text-embedding-3-small")
    vec = await model.embed("你好世界")
"""
