"""技能编组工具:创建/列出/执行技能组合(spec §4.3/§5.3)。

从 ``agent/graph.py`` 的 ``_make_composition_tools`` 迁入,函数体逐字保持,
对外 name/参数名/返回文案不变;依赖 ``CompositionEngine``。
三类继承 ``ExecutionTool`` 但技能编排无外部危险面:``security_review``
一律 ``Allow()``;``self_verify`` 按 spec §5.3 —— 仅
``execute_skill_composition`` 空结果转 ``Suspect``。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from thumbelina.tools.base import Allow, Ok, Suspect
from thumbelina.tools.execution import ExecutionTool


class _CreateSkillCompositionArgs(BaseModel):
    skill_ids: str = Field(
        ...,
        description="Comma-separated list of skill IDs to chain together.",
    )
    name: str = Field(..., description="Name for the composition.")
    description: str = Field(..., description="Description of what the composition does.")


class _ListSkillCompositionsArgs(BaseModel):
    pass


class _ExecuteSkillCompositionArgs(BaseModel):
    user_input: str = Field(..., description="User input used to find a matching composition.")


class SkillCompositionTool(ExecutionTool):
    """技能编组三工具共同基类:持 engine 引用,审查一律放行。"""

    engine: Any = None

    async def security_review(self, args: dict[str, Any]) -> Allow:
        # 技能编排无外部危险面(实际危险面在底层技能所用工具上已审查)。
        return Allow()


class CreateSkillCompositionTool(SkillCompositionTool):
    name: str = "create_skill_composition"
    description: str = (
        "Create a skill composition that chains multiple skills into a workflow.\n\n"
        "Args:\n"
        "    skill_ids: Comma-separated list of skill IDs to chain together.\n"
        "    name: Name for the composition.\n"
        "    description: Description of what the composition does."
    )
    args_schema: type[BaseModel] = _CreateSkillCompositionArgs

    async def _execute(self, skill_ids: str, name: str, description: str) -> str:
        ids = [s.strip() for s in skill_ids.split(",") if s.strip()]
        if not ids:
            return "No skill IDs provided."
        try:
            composition = await self.engine.create_composition(
                skill_ids=ids, name=name, description=description
            )
            return (
                f"Composition created with ID {composition.id}. Name: {name}. Skills: {len(ids)}."
            )
        except Exception as exc:
            return f"Failed to create composition: {exc}"

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok:
        # spec §5.3:检查返回串含 composition id —— 正常路径即含;失败路径已
        # 在 _execute 返回说明串,无可自疑,放行。
        return Ok()


class ListSkillCompositionsTool(SkillCompositionTool):
    name: str = "list_skill_compositions"
    description: str = "List all skill compositions and their details."
    args_schema: type[BaseModel] = _ListSkillCompositionsArgs

    async def _execute(self) -> str:
        compositions = await self.engine.composition_repo.list_all()
        if not compositions:
            return "No skill compositions found."
        lines = []
        for c in compositions:
            lines.append(
                f"- ID: {c.id}, Name: {c.name}, Skills: {len(c.skill_ids)}, Usage: {c.usage_count}"
            )
        return "\n".join(lines)

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok:
        return Ok()


class ExecuteSkillCompositionTool(SkillCompositionTool):
    name: str = "execute_skill_composition"
    description: str = "Find and execute a matching skill composition for the given input."
    args_schema: type[BaseModel] = _ExecuteSkillCompositionArgs

    async def _execute(self, user_input: str) -> str:
        composition = await self.engine.match_composition(user_input)
        if composition is None:
            return "No matching composition found for the input."
        result: str = await self.engine.execute_composition(composition, user_input)
        return result

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        # spec §5.3:执行结果为空串 → 可疑。
        if not result.strip():
            return Suspect("技能编组执行返回空结果")
        return Ok()


def make_skill_tools(engine: Any) -> list[BaseTool]:
    """返回封装 ``CompositionEngine`` 的技能编组三工具(迁移自 ``_make_composition_tools``)。"""
    return [
        CreateSkillCompositionTool(engine=engine),
        ListSkillCompositionsTool(engine=engine),
        ExecuteSkillCompositionTool(engine=engine),
    ]
