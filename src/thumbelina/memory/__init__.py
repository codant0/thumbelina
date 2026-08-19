"""基于 Markdown 文件系统的分层记忆子系统。

阶段一(核心存储层)+ 阶段二(LLM 抽取与写入)。

公开 API:
  - :class:`MemoryService` —— 存储服务(读写/索引重建/原子写)。
  - :class:`MemoryExtractor` —— LLM 抽取/改写器(阶段二)。
  - :class:`SearchMemoryTool`/``ReadMemoryTool``/``RememberTool``
    —— Agent 记忆工具(阶段二);:func:`make_memory_tools` 组装。
  - :class:`MemoryEntry`/``MemoryIndex``/``MemoryHit``/``UpdateDecision``
    —— 数据模型(见 :mod:`thumbelina.memory.models`)。
  - :func:`parse_document`/``build_index`` —— 文档解析与索引生成
    (见 :mod:`thumbelina.memory.parser`)。
  - :func:`search_entries`/``select_for_injection`` —— 字符 2-gram
    检索与 L0 注入选择(见 :mod:`thumbelina.memory.search`)。
  - :class:`MemoryServiceError` —— 异常基类。
"""

from __future__ import annotations

from thumbelina.memory.exceptions import MemoryEntryNotFoundError, MemoryServiceError
from thumbelina.memory.extractor import MemoryExtractor
from thumbelina.memory.models import MemoryEntry, MemoryHit, MemoryIndex, UpdateDecision
from thumbelina.memory.parser import build_index, parse_document
from thumbelina.memory.search import search_entries, select_for_injection
from thumbelina.memory.service import MemoryService
from thumbelina.memory.tools import (
    ReadMemoryTool,
    RememberTool,
    SearchMemoryTool,
    make_memory_tools,
)

__all__ = [
    "MemoryEntry",
    "MemoryEntryNotFoundError",
    "MemoryExtractor",
    "MemoryHit",
    "MemoryIndex",
    "MemoryService",
    "MemoryServiceError",
    "ReadMemoryTool",
    "RememberTool",
    "SearchMemoryTool",
    "UpdateDecision",
    "build_index",
    "make_memory_tools",
    "parse_document",
    "search_entries",
    "select_for_injection",
]
