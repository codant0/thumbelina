"""记忆目录路径校验(唯一收口)。

``category``/``slug`` 由 LLM 输出、也可经 API 传入,是半受控输入,
必须集中校验以杜绝路径穿越与符号链接逃逸(见设计文档 §8.3)。
本模块是 memory 包所有读写的唯一路径来源,文件路径即 ID
(``<category>/<slug>.md``);``index.md`` 固定为 ``base / "index.md"``,
永不从用户输入派生。
"""

from __future__ import annotations

import re
from pathlib import Path

from thumbelina.filestore import TMP_SUFFIX

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_CAT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

INDEX_FILENAME = "index.md"

__all__ = ["INDEX_FILENAME", "TMP_SUFFIX", "_resolve", "resolve_index"]


def _resolve(base: Path, category: str, slug: str) -> Path:
    """校验并解析 ``base / category / <slug>.md`` 的绝对路径。

    双重断言:白名单正则(天然拒绝 ``..``/``/``/``\\``/``.``) +
    ``resolve()`` + ``is_relative_to()``(顺带解出符号链接)。
    拒绝空串、URL 编码、符号链接逃逸等。

    Raises:
        ValueError: category/slug 非法或路径逃逸记忆根。
    """
    if not _CAT_RE.fullmatch(category) or not _SLUG_RE.fullmatch(slug):
        raise ValueError("illegal category/slug")
    base_resolved = base.resolve()
    p = (base_resolved / category / f"{slug}.md").resolve()
    if not p.is_relative_to(base_resolved):
        raise ValueError("path escapes memory root")
    return p


def resolve_index(base: Path) -> Path:
    """返回固定的 ``index.md`` 路径(不从用户输入派生)。"""
    return base.resolve() / INDEX_FILENAME
