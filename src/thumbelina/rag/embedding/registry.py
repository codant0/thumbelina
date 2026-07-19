"""Embedding 模型注册中心。

规划中的提供者
--------------
- OpenAIEmbedding：text-embedding-3-small / text-embedding-3-large
- HuggingFaceEmbedding：通过 sentence-transformers 使用本地模型
- OllamaEmbedding：Ollama 本地部署方案，完全离线

用法示例
--------
    model = get_embedding_model("hf/text-embedding-3-small")
    vec = model.embed("你好世界")
"""

from thumbelina.rag.embedding.base import EmbeddingModel


class EmbeddingRegistry:
    """Embedding模型注册中心（单例）"""
    _instance = None
    _model: dict[str, type[EmbeddingModel]] = {}
    # 当前只支持hugging_face
    _default_provider: str = "hf"
    _default_model: str = "Qwen/Qwen3-Embedding-0.6B"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, model_name: str, model_cls: type[EmbeddingModel]):
        """注册模型类"""
        self._model[model_name] = model_cls

    def create(self, model_name: str | None = None, **kwargs) -> EmbeddingModel:
        """创建模型实例"""
        model_name = model_name or self._default_model
        if model_name not in self._model:
            raise ValueError(f"Unknown embedding model: {model_name}")
        return self._model[model_name](**kwargs)
