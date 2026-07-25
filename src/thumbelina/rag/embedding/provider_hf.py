"""hugging face 嵌入模型实现"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from thumbelina.rag.embedding.base import EmbeddingModel

# Pre-import torch at module level to ensure its DLLs are loaded before
# sentence_transformers → transformers triggers a conflicting import chain.
# This must happen before any other C extension modules interfere with DLL
# resolution on Windows.
try:
    import torch  # noqa: F401
except OSError:
    pass

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


def _ensure_torch_dll_path() -> None:
    """Add torch's lib directory to DLL search path on Windows.

    PyTorch's ``shm.dll`` depends on other DLLs in the same directory.
    When imported inside a server process (uvicorn), the DLL search path
    may not include torch's lib directory, causing ``WinError 127``.

    This function is a safety net — the primary fix is pre-importing torch
    in ``app.py`` lifespan before other C extensions load.
    """
    if os.name != "nt":
        return
    try:
        import torch as _torch

        torch_lib = str(Path(_torch.__file__).parent / "lib")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(torch_lib)
        current_path = os.environ.get("PATH", "")
        if torch_lib not in current_path:
            os.environ["PATH"] = torch_lib + os.pathsep + current_path
    except ImportError:
        # torch not available — find path from filesystem
        try:
            import importlib.util

            spec = importlib.util.find_spec("torch")
            if spec and spec.origin:
                torch_lib = str(Path(spec.origin).parent / "lib")
                if Path(torch_lib).is_dir():
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(torch_lib)
                    current_path = os.environ.get("PATH", "")
                    if torch_lib not in current_path:
                        os.environ["PATH"] = torch_lib + os.pathsep + current_path
        except (ValueError, AttributeError):
            pass


class HuggingFaceEmbedding(EmbeddingModel):
    """通过sentence-transformers使用本地模型"""

    def __init__(self, model_name: str = "Qwen/Qwen3-Embedding-0.6B"):
        super().__init__()
        # Ensure torch DLLs can be found before importing sentence_transformers
        _ensure_torch_dll_path()

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
            self.model: SentenceTransformer = _ST(snapshot_dir, local_files_only=True)
        else:
            print(f"本地未找到缓存，从 HuggingFace Hub 下载: {model_name}")
            self.model = _ST(model_name)

    def embed(self, text: str) -> list[float]:
        """单文本向量化"""
        return self.model.encode(text).flatten().tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化"""
        return self.model.encode(texts).tolist()
