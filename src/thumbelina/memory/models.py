"""基于 Markdown 文件系统的分层记忆数据模型。

字段定义见设计文档 §6。本模块仅定义数据结构,不涉及读写与解析。
``MemoryEntry`` 用 dataclass 轻量化;``UpdateDecision`` 为抽取器输出模型,
本阶段先定义字段结构(抽取器实现是阶段二)。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """一条记忆(对应 ``<category>/<slug>.md``)。

    字段层级(见设计文档 §6 表格):
      - ``title``/``category``/``slug``:全部层级必填。
      - ``summary``:L0 索引摘要(一句话),写入 ``index.md``。
      - ``updated``:更新时间(索引展示/排序)。
      - ``source``:L1 溯源引用(对话 id / 日期,可选)。
      - ``overview``:L1 概览(核心信息 + 使用场景)。
      - ``full_text``:L2 全文(完整原始内容,按需加载)。
    """

    title: str
    category: str
    slug: str
    summary: str
    updated: str
    overview: str = ""
    full_text: str = ""
    source: str = ""

    @property
    def relpath(self) -> str:
        """相对记忆根的路径标识(文件路径即 ID)。"""
        return f"{self.category}/{self.slug}.md"


@dataclass
class MemoryIndex:
    """``index.md`` 解析结果(L0 摘要集合)。

    ``entries`` 按分类白名单顺序分组保留;``updated`` 为索引头部声明
    的最近重建时间(解析时读取,重建时刷新)。
    """

    entries: list[MemoryEntry] = field(default_factory=list)
    updated: str = ""


@dataclass
class MemoryHit:
    """检索命中结果(L0→L1 入口)。

    ``score`` 为字符 2-gram Jaccard/Dice 与精确 token 重叠加权后的
    确定性得分,越高越相关;``entry`` 为命中条目引用。
    """

    title: str
    category: str
    slug: str
    summary: str
    score: float
    entry: MemoryEntry | None = None


@dataclass
class UpdateDecision:
    """抽取器输出模型(见设计文档 §8.5 JSON schema)。

    本阶段仅定义字段结构,抽取器实现是阶段二。``action`` 取值为
    ``NEW``/``UPDATE``/``DELETE``/``NOOP``;``target`` 为 UPDATE/DELETE
    必填的现有 slug;``entry`` 为 NEW/UPDATE 时的整篇改写结果。
    """

    action: str
    target: str = ""
    entry: MemoryEntry | None = None
