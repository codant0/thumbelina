"""RAG 模块测试配置。

strategies.py / indexer.py / provider_hf.py 顶层 import torch / sentence_transformers /
huggingface_hub / chromadb，在无 GPU 环境下会因 DLL 加载失败而崩溃。
这里在收集测试前统一 mock 掉这些重量级依赖。
"""

import sys
import types
from unittest.mock import MagicMock


def _ensure_mock_module(name: str, attrs: dict | None = None) -> None:
    """如果模块尚未加载，注入一个带可选属性的 mock 模块。"""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__spec__ = None  # type: ignore[attr-defined]
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[name] = mod
    elif attrs:
        mod = sys.modules[name]
        for k, v in attrs.items():
            if not hasattr(mod, k):
                setattr(mod, k, v)


# ---------------------------------------------------------------------------
# torch 及子模块
# ---------------------------------------------------------------------------
for _mod_name in [
    "torch",
    "torch.nn",
    "torch.nn.functional",
    "torch.cuda",
]:
    _ensure_mock_module(_mod_name)

# ---------------------------------------------------------------------------
# huggingface_hub — provider_hf.py 直接调用 try_to_load_from_cache
# ---------------------------------------------------------------------------
_ensure_mock_module(
    "huggingface_hub",
    {
        "try_to_load_from_cache": MagicMock(return_value="/nonexistent"),
    },
)

# ---------------------------------------------------------------------------
# sentence_transformers — provider_hf.py 使用 SentenceTransformer
# ---------------------------------------------------------------------------
_ensure_mock_module(
    "sentence_transformers",
    {
        "SentenceTransformer": MagicMock(),
    },
)
