"""hugging face 嵌入模型实现"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from thumbelina.rag.embedding.base import EmbeddingModel

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class HuggingFaceEmbedding(EmbeddingModel):
    """通过sentence-transformers使用本地模型"""

    def __init__(self, model_name: str = "Qwen/Qwen3-Embedding-0.6B"):
        super().__init__()
        try:
            from huggingface_hub import try_to_load_from_cache
            from sentence_transformers import SentenceTransformer as _ST
        except ImportError as exc:
            raise ImportError(
                "HuggingFace embedding requires sentence-transformers. "
                "Install with: pip install sentence-transformers"
            ) from exc

        # 检查 HuggingFace 缓存中是否存在该模型的快照目录
        cached = try_to_load_from_cache(model_name, "config.json")
        if isinstance(cached, str) and Path(cached).exists():
            # 缓存存在，拿到快照目录（config.json 所在目录的父级）
            snapshot_dir = str(Path(cached).parent)
            print(f"使用本地缓存模型: {snapshot_dir}")
            self.model: SentenceTransformer = _ST(
                snapshot_dir, local_files_only=True)
        else:
            print(f"本地未找到缓存，从 HuggingFace Hub 下载: {model_name}")
            self.model = _ST(model_name)

    def embed(self, text: str) -> list[float]:
        """单文本向量化"""
        return self.model.encode(text).flatten().tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化"""
        return self.model.encode(texts).tolist()
