"""RAG 模块 — 检索增强生成（Retrieval-Augmented Generation）。

该模块提供了一套完整的 RAG 流水线，用于外部知识的检索与注入：
文档摄取、分块、向量化、检索，以及最终与 Thumbelina Agent 的集成。

设计目标：
- 作为独立的学习性子模块，内部各组件松耦合
- 后续可平滑接入主项目的 Agent 循环和 API 层
"""

__version__ = "0.1.0"
