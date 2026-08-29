"""ThumbelinaBaseTool 模板方法契约测试。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from thumbelina.tools.base import (
    Confirm,
    Reject,
    Suspect,
    ThumbelinaBaseTool,
    ToolCategory,
)


class _Args(BaseModel):
    text: str = ""


class ProbeTool(ThumbelinaBaseTool):
    name: str = "probe"
    description: str = "probe tool"
    args_schema: type[BaseModel] = _Args
    category: ToolCategory = ToolCategory.PERCEPTION

    calls: list = []

    async def _execute(self, text: str = "", **kwargs) -> str:  # type: ignore[override]
        self.calls.append(text)
        return f"ok:{text}"


class RejectingTool(ProbeTool):
    name: str = "rejecting"
    category: ToolCategory = ToolCategory.EXECUTION

    async def security_review(self, args):
        return Reject("测试拒绝")


class ConfirmingTool(ProbeTool):
    name: str = "confirming"

    async def security_review(self, args):
        return Confirm("需要确认")


class SuspectingTool(ProbeTool):
    name: str = "suspecting"

    async def self_verify(self, args, result):
        return Suspect("结果可疑")


class RaisingTool(ProbeTool):
    name: str = "raising"

    async def _execute(self, text: str = "", **kwargs):
        raise ValueError("boom")


async def test_arun_executes_and_returns():
    t = ProbeTool(calls=[])
    assert await t._arun(text="hi") == "ok:hi"
    assert t.calls == ["hi"]


def test_run_is_async_only():
    t = ProbeTool(calls=[])
    assert "异步" in t._run(text="hi")


@pytest.mark.asyncio
async def test_reject_blocks_execution():
    t = RejectingTool(calls=[])
    result = await t._arun(text="hi")
    assert t.calls == []
    assert result.startswith("Error:")
    assert "测试拒绝" in result


@pytest.mark.asyncio
async def test_confirm_allows_with_log(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        t = ConfirmingTool(calls=[])
        assert await t._arun(text="hi") == "ok:hi"
    assert "需要确认" in caplog.text


@pytest.mark.asyncio
async def test_suspect_appends_warn():
    t = SuspectingTool(calls=[])
    result = await t._arun(text="hi")
    assert result == "ok:hi\n[warn] 结果可疑"


@pytest.mark.asyncio
async def test_exception_converted_to_error_string():
    t = RaisingTool(calls=[])
    result = await t._arun(text="hi")
    assert result.startswith("Error:")
    assert "boom" in result


def test_category_required():
    with pytest.raises(Exception):

        class NoCategory(ProbeTool):
            name: str = "no-category"
            category = None  # 显式清空默认,验证字段必填

        NoCategory()
