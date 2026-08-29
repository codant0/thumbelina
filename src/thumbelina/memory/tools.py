"""Agent 记忆工具(见设计文档 §7.3 表)。

三个分类体系工具子类,供 ``ThumbelinaAgent`` 装配并入 ``self.tools``:

  - :class:`SearchMemoryTool` —— 对索引摘要 n-gram 检索,返回命中条目
    的标题/摘要/链接文本(L0→L1 入口)。
  - :class:`ReadMemoryTool` —— 分层读取某条记忆(overview/full)。
  - :class:`RememberTool` —— 记录一条事实,走抽取器同一写路径入库
    (受单轮配额与去重 §8.6)。

工具出错(条目不存在/服务不可用)返回友好的错误字符串,不抛出中断
agent 循环。``RememberTool`` 维护一个**实例级单轮配额计数器**
(每轮 ≤3),阶段三在每轮对话开始时调用 :meth:`reset_turn_quota`
重置(或经 :func:`make_memory_tools` 返回的列表中找到该工具实例重置)。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.memory.exceptions import MemoryEntryNotFoundError, MemoryServiceError
from thumbelina.memory.extractor import MemoryExtractor
from thumbelina.memory.search import search_entries
from thumbelina.memory.service import DEFAULT_USER_ID, MemoryService
from thumbelina.tools.base import Allow, Ok
from thumbelina.tools.execution import ExecutionTool
from thumbelina.tools.perception import PerceptionTool

logger = logging.getLogger(__name__)

# 单轮 remember 调用上限(§8.6)。
REMEMBER_PER_TURN_LIMIT = 3


# ---------------------------------------------------------------------------
# Pydantic args_schema
# ---------------------------------------------------------------------------


class _SearchArgs(BaseModel):
    search_memory_query: str = Field(
        ...,
        description="检索关键词或问题(中文/英文均可,用关键词更准)",
    )


class _ReadArgs(BaseModel):
    read_memory_category: str = Field(
        ...,
        description="分类名,如 user/project/decision/topic",
    )
    read_memory_slug: str = Field(
        ...,
        description="条目 slug(短横线小写,如 programming-preference)",
    )
    read_memory_depth: str = Field(
        default="overview",
        description="读取深度:overview(概览,默认)或 full(全文)",
    )


class _RememberArgs(BaseModel):
    remember_fact: str = Field(
        ...,
        description="用户想记住的一条事实/偏好(自然语言一句话即可)",
    )


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


class SearchMemoryTool(PerceptionTool):
    """对记忆索引摘要做 n-gram 检索,返回命中条目的标题/摘要/链接。

    用于从 L0 索引找到相关记忆入口,再用 ``read_memory`` 拉取详情。
    """

    name: str = "search_memory"
    description: str = (
        "搜索长期记忆库。输入关键词或问题,返回最相关的若干条记忆的"
        "标题、摘要与相对路径(如 user/programming-preference.md)。"
        "用于查找关于用户偏好、项目事实、历史决策、兴趣主题的已有记忆。"
        "参数:query(检索关键词或问题)。返回:命中条目列表或无命中提示。"
    )
    args_schema: type[BaseModel] = _SearchArgs

    service: MemoryService
    top_k: int = 8

    async def _execute(
        self,
        search_memory_query: str,
        **kwargs: Any,
    ) -> str:
        del kwargs  # 接受 langchain 透传的无关 kwargs
        try:
            index = await self.service.load_index(user_id=DEFAULT_USER_ID)
        except Exception:  # noqa: BLE001
            logger.warning("search_memory 加载索引失败", exc_info=True)
            return "记忆服务暂不可用。"
        if not index.entries:
            return "当前没有任何记忆。"
        hits = search_entries(index.entries, search_memory_query, top_k=self.top_k)
        if not hits:
            return f"未找到与 {search_memory_query!r} 相关的记忆。"
        lines = [
            f"- {h.title} [{h.category}/{h.slug}.md] (score={h.score:.2f}) — {h.summary}"
            for h in hits
        ]
        return f"找到 {len(hits)} 条相关记忆:\n" + "\n".join(lines)


class ReadMemoryTool(PerceptionTool):
    """分层读取一条记忆的概览(默认)或全文。"""

    name: str = "read_memory"
    description: str = (
        "读取一条长期记忆的详情。参数:category(分类,如 user/project/"
        "decision/topic)、slug(短横线小写标识)、depth(读取深度,overview"
        "=概览 2-5 行,默认;full=完整全文,较长)。先用 search_memory 找到"
        "category/slug,再用本工具拉取详情。返回:该条记忆的概览或全文文本;"
        "条目不存在时返回错误提示。"
    )
    args_schema: type[BaseModel] = _ReadArgs

    service: MemoryService

    async def _execute(
        self,
        read_memory_category: str,
        read_memory_slug: str,
        read_memory_depth: str = "overview",
        **kwargs: Any,
    ) -> str:
        del kwargs
        depth = read_memory_depth.strip().lower() if isinstance(read_memory_depth, str) else ""
        if depth not in ("overview", "full"):
            depth = "overview"  # 非法值默认 overview
        try:
            if depth == "overview":
                entry = await self.service.read_overview(
                    read_memory_category, read_memory_slug, user_id=DEFAULT_USER_ID
                )
                body = entry.overview.strip() or "(概览为空)"
                header = f"# {entry.title}\n> 分类:{entry.category} · 更新:{entry.updated}"
                if entry.source:
                    header += f" · 来源:{entry.source}"
                return f"{header}\n\n## 概览\n{body}"
            entry = await self.service.read_full(
                read_memory_category, read_memory_slug, user_id=DEFAULT_USER_ID
            )
            overview = entry.overview.strip() or "(概览为空)"
            full = entry.full_text.strip() or "(全文为空)"
            header = f"# {entry.title}\n> 分类:{entry.category} · 更新:{entry.updated}"
            if entry.source:
                header += f" · 来源:{entry.source}"
            return f"{header}\n\n## 概览\n{overview}\n\n## 全文\n{full}"
        except MemoryEntryNotFoundError:
            return f"记忆条目不存在: {read_memory_category}/{read_memory_slug}"
        except MemoryServiceError as exc:
            return f"读取记忆失败: {exc}"
        except Exception:  # noqa: BLE001
            logger.warning("read_memory 读取失败", exc_info=True)
            return "读取记忆时发生意外错误。"


class RememberTool(ExecutionTool):
    """记录一条事实,走抽取器同一写路径入库(受单轮配额与去重)。

    单轮配额计数器为实例级 ``_turn_count``(默认 0);阶段三在每轮
    对话开始时调用 :meth:`reset_turn_quota` 重置。超过
    :data:`REMEMBER_PER_TURN_LIMIT` 后返回配额上限提示(NOOP,不落盘)。
    """

    name: str = "remember"
    description: str = (
        "把一条用户想长期记住的事实或偏好写入记忆库。参数:fact(自然语言"
        "一句话描述要记的内容,如'我偏好 Python 和类型注解')。本工具会"
        "经 LLM 抽取/改写后入库,可能新建、更新已有同义记忆或判定无需记录。"
        "每轮对话最多调用 3 次。返回:入库结果说明(新建/更新/忽略/配额上限)。"
    )
    args_schema: type[BaseModel] = _RememberArgs

    service: MemoryService
    extractor: MemoryExtractor
    # Pydantic v2 允许任意类型字段(BaseTool 为 Pydantic 模型);显式声明默认。
    _turn_count: int = 0

    def reset_turn_quota(self) -> None:
        """重置单轮 remember 配额计数器为 0。

        供阶段三在每轮对话开始时调用(如 ``_build_initial_messages`` 内,
        或在 agent 循环开始前)。也可由调用方通过
        :func:`make_memory_tools` 返回的列表中找到 ``RememberTool`` 实例
        后调用。
        """
        self._turn_count = 0

    def turn_quota_used(self) -> int:
        """返回本轮已使用的 remember 配额数。"""
        return self._turn_count

    async def security_review(self, args: dict[str, Any]) -> Allow:
        # 写入走抽取器既有安全路径(§8.6 去重/配额),无额外静态危险模式可审。
        return Allow()

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok:
        # decision 合法性已由 _execute 的 _format_result 兜底(getattr 默认 NOOP);
        # NOOP 说明文案在 _execute 返回,不追加 warn(spec §5.3)。
        return Ok()

    async def _execute(self, remember_fact: str, **kwargs: Any) -> str:
        del kwargs
        if self._turn_count >= REMEMBER_PER_TURN_LIMIT:
            return f"本轮 remember 调用已达上限({REMEMBER_PER_TURN_LIMIT} 次),其余事实请下轮再记。"
        self._turn_count += 1
        # 构造为单条用户消息走抽取器同一写路径
        messages = [{"role": "user", "content": remember_fact}]
        try:
            decision = await self.extractor.extract_from_messages(messages, user_id=DEFAULT_USER_ID)
        except Exception:  # noqa: BLE001
            logger.warning("remember 抽取失败", exc_info=True)
            return "记录事实时发生错误,未能写入记忆库。"
        return self._format_result(decision, remember_fact)

    @staticmethod
    def _format_result(decision: Any, fact: str) -> str:
        action = getattr(decision, "action", "NOOP")
        if action == "NEW":
            entry = getattr(decision, "entry", None)
            where = f"{entry.category}/{entry.slug}.md" if entry is not None else "?"
            return f"已记下(新建 {where}):{fact[:60]}"
        if action == "UPDATE":
            entry = getattr(decision, "entry", None)
            where = f"{entry.category}/{entry.slug}.md" if entry is not None else "?"
            return f"已更新已有记忆({where}):{fact[:60]}"
        if action == "DELETE":
            target = getattr(decision, "target", "") or "?"
            return f"已删除记忆({target})。"
        return f"无需记录(本轮没有新的稳定事实):{fact[:60]}"


# ---------------------------------------------------------------------------
# 组装函数
# ---------------------------------------------------------------------------


def make_memory_tools(
    service: MemoryService | None,
    *,
    enabled: bool = True,
    extractor: MemoryExtractor | None = None,
    search_top_k: int = 8,
) -> list[BaseTool]:
    """组装记忆工具列表,供 ``ThumbelinaAgent`` 装配。

    Parameters
    ----------
    service:
        记忆存储服务。``None`` 时返回空列表(降级)。
    enabled:
        工具是否启用(对应 ``memory.tools.enabled``);``False`` 返回空列表。
    extractor:
        抽取器实例。``RememberTool`` 需要它;为 ``None`` 时不注册
        ``remember`` 工具(仅注册 search/read)。

    Returns
    -------
    list[BaseTool]
        可并入 ``agent.tools`` 的工具列表。
    """
    if service is None or not enabled:
        return []
    tools: list[BaseTool] = [
        SearchMemoryTool(service=service, top_k=search_top_k),
        ReadMemoryTool(service=service),
    ]
    if extractor is not None:
        tools.append(RememberTool(service=service, extractor=extractor))
    return tools
