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

import threading

from thumbelina.rag.embedding.base import EmbeddingModel


class EmbeddingRegistry:
    """Embedding模型注册中心（单例）"""

    _instance = None
    _model: dict[str, type[EmbeddingModel]] = {}
    _instance_cache: dict[str, EmbeddingModel] = {}
    # 保护实例缓存的并发访问：后台预加载线程与请求线程可能同时 create()
    _lock = threading.Lock()
    # 当前只支持hugging_face
    _default_provider: str = "hf"
    _default_model: str = "Qwen/Qwen3-Embedding-0.6B"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, model_name: str, model_cls: type[EmbeddingModel]):
        """注册模型类；重复注册同名模型时失效已缓存的实例。"""
        with self._lock:
            self._model[model_name] = model_cls
            self._instance_cache.pop(model_name, None)

    def create(self, model_name: str | None = None, **kwargs) -> EmbeddingModel:
        """创建模型实例（按 model_name 缓存，避免重复加载）。

        线程安全：并发调用（如启动后的后台预加载与首次请求）只会触发一次
        实际加载，其余调用等待加载完成后复用同一实例。
        """
        model_name = model_name or self._default_model
        if model_name not in self._model:
            raise ValueError(f"Unknown embedding model: {model_name}")
        # 快速路径：已缓存时无需加锁
        cached = self._instance_cache.get(model_name)
        if cached is not None:
            return cached
        with self._lock:
            if model_name not in self._instance_cache:
                self._instance_cache[model_name] = self._model[model_name](**kwargs)
            return self._instance_cache[model_name]

    def preload(self, model_name: str | None = None) -> EmbeddingModel:
        """预加载并缓存模型实例（阻塞操作）。

        建议在应用启动完成后通过后台线程调用（如 ``asyncio.to_thread``），
        避免首次使用时等待模型加载。
        """
        return self.create(model_name)

    def is_loaded(self, model_name: str | None = None) -> bool:
        """判断模型实例是否已加载并缓存。"""
        return (model_name or self._default_model) in self._instance_cache
