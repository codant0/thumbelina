"""Tool 分类基类与统一执行生命周期(模板方法)。

设计见 docs/specs/2026-08-29-tools-taxonomy-design.md。

所有 agent 工具继承 ``ThumbelinaBaseTool``(langchain BaseTool 子类)。
公共生命周期下沉到 ``_arun``: security_review → _execute → self_verify,
异常统一转为 ``Error:`` 字符串,不抛到 tool_node。
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class ToolCategory(StrEnum):
    PERCEPTION = "perception"
    EXECUTION = "execution"
    COMMUNICATION = "communication"
    COLLABORATION = "collaboration"
    EVENT_TRIGGER = "event_trigger"


# --- 安全审查结论 -----------------------------------------------------------


@dataclass
class Allow:
    pass


@dataclass
class Confirm:
    reason: str


@dataclass
class Reject:
    reason: str


# --- 结果自验证结论 ---------------------------------------------------------


@dataclass
class Ok:
    pass


@dataclass
class Suspect:
    reason: str


class ThumbelinaBaseTool(BaseTool):
    """公共基类:category 元数据 + 模板方法生命周期 + 默认审查/验证全放行。"""

    category: ToolCategory

    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        return Allow()

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        return Ok()

    @abstractmethod
    async def _execute(self, **kwargs: Any) -> str:
        """子类唯一必写方法;失败返回 ``Error: ...`` 字符串。"""

    async def _arun(self, **kwargs: Any) -> str:
        verdict = await self.security_review(kwargs)
        if isinstance(verdict, Reject):
            return f"Error: {self.name}: 安全审查拒绝: {verdict.reason}"
        if isinstance(verdict, Confirm):
            # 本期无人机交互:放行 + 日志,枚举保留三态为 HITL 留接口。
            logger.warning(
                "tool %s: 安全审查建议确认(已放行): %s", self.name, verdict.reason
            )
        try:
            result = await self._execute(**kwargs)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {self.name}: {exc}"
        verify = await self.self_verify(kwargs, result)
        if isinstance(verify, Suspect):
            result = f"{result}\n[warn] {verify.reason}"
        return result

    def _run(self, **kwargs: Any) -> str:
        return f"{self.name} 仅支持异步调用(_arun);请在异步 agent 循环中使用。"
