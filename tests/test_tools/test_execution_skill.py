"""技能编组工具迁移测试(Task 5)。

假 engine 覆盖 CompositionEngine 契约:
create_composition / match_composition / execute_composition / composition_repo。
"""
from __future__ import annotations

import pytest

from thumbelina.tools.base import Allow, Ok, ToolCategory
from thumbelina.tools.execution import ExecutionTool
from thumbelina.tools.execution_skill import (
    CreateSkillCompositionTool,
    ExecuteSkillCompositionTool,
    ListSkillCompositionsTool,
    make_skill_tools,
)


class FakeComposition:
    def __init__(self, id="comp-42", name="Daily", skill_ids=("a", "b"), usage_count=3):
        self.id, self.name = id, name
        self.skill_ids, self.usage_count = list(skill_ids), usage_count


class FakeCompositionRepo:
    def __init__(self, compositions):
        self._compositions = compositions

    async def list_all(self):
        return self._compositions


class FakeEngine:
    def __init__(
        self,
        compositions=None,
        match=None,
        exec_result="skill chain output",
        create_error=None,
    ):
        self.composition_repo = FakeCompositionRepo(
            compositions if compositions is not None else []
        )
        self._match = match
        self._exec_result = exec_result
        self._create_error = create_error
        self.create_calls: list[dict] = []

    async def create_composition(self, skill_ids, name, description):
        if self._create_error is not None:
            raise self._create_error
        self.create_calls.append({"skill_ids": skill_ids, "name": name, "description": description})
        return FakeComposition(name=name)

    async def match_composition(self, user_input):
        return self._match

    async def execute_composition(self, composition, user_input):
        return self._exec_result


# --- create_skill_composition ------------------------------------------------


@pytest.mark.asyncio
async def test_create_success_includes_composition_id():
    t = CreateSkillCompositionTool(engine=FakeEngine())
    out = await t._arun(skill_ids="a, b", name="Daily", description="chain")
    assert "Composition created with ID comp-42" in out
    assert "Skills: 2" in out
    assert "[warn]" not in out  # 正常结果不自疑


@pytest.mark.asyncio
async def test_create_empty_skill_ids():
    t = CreateSkillCompositionTool(engine=FakeEngine())
    out = await t._arun(skill_ids=" , ", name="x", description="y")
    assert out == "No skill IDs provided."


@pytest.mark.asyncio
async def test_create_engine_error_returns_failure_string():
    t = CreateSkillCompositionTool(engine=FakeEngine(create_error=RuntimeError("boom")))
    out = await t._arun(skill_ids="a", name="x", description="y")
    assert out.startswith("Failed to create composition:")
    assert "boom" in out


# --- execute_skill_composition ------------------------------------------------


@pytest.mark.asyncio
async def test_execute_no_match():
    t = ExecuteSkillCompositionTool(engine=FakeEngine(match=None))
    out = await t._arun(user_input="do the thing")
    assert out == "No matching composition found for the input."


@pytest.mark.asyncio
async def test_execute_returns_result():
    comp = FakeComposition()
    t = ExecuteSkillCompositionTool(engine=FakeEngine(match=comp, exec_result="chain ran"))
    out = await t._arun(user_input="go")
    assert out == "chain ran"


@pytest.mark.asyncio
async def test_execute_empty_result_flagged_suspect():
    comp = FakeComposition()
    t = ExecuteSkillCompositionTool(engine=FakeEngine(match=comp, exec_result=""))
    out = await t._arun(user_input="go")
    assert "[warn]" in out
    assert "技能编组执行返回空结果" in out


# --- list_skill_compositions --------------------------------------------------


@pytest.mark.asyncio
async def test_list_empty():
    t = ListSkillCompositionsTool(engine=FakeEngine(compositions=[]))
    out = await t._arun()
    assert out == "No skill compositions found."


@pytest.mark.asyncio
async def test_list_non_empty():
    comp = FakeComposition(id="c1", name="Alpha", skill_ids=("a", "b", "c"), usage_count=7)
    t = ListSkillCompositionsTool(engine=FakeEngine(compositions=[comp]))
    out = await t._arun()
    assert "- ID: c1, Name: Alpha, Skills: 3, Usage: 7" in out


# --- 分类 / 生命周期 / 工厂 ----------------------------------------------------


@pytest.mark.asyncio
async def test_all_three_are_execution_tools_allow_all():
    engine = FakeEngine()
    tools = [
        CreateSkillCompositionTool(engine=engine),
        ListSkillCompositionsTool(engine=engine),
        ExecuteSkillCompositionTool(engine=engine),
    ]
    for t in tools:
        assert isinstance(t, ExecutionTool)
        assert t.category == ToolCategory.EXECUTION
        assert isinstance(await t.security_review({}), Allow)
        assert isinstance(await t.self_verify({}, "non-empty result"), Ok)


def test_category_and_factory_and_schemas():
    engine = FakeEngine()
    tools = make_skill_tools(engine)
    assert [t.name for t in tools] == [
        "create_skill_composition",
        "list_skill_compositions",
        "execute_skill_composition",
    ]
    assert set(tools[0].args_schema.model_fields) == {
        "skill_ids",
        "name",
        "description",
    }
    assert set(tools[1].args_schema.model_fields) == set()
    assert set(tools[2].args_schema.model_fields) == {"user_input"}
