"""感知工具迁移后行为回归: 名称、schema、错误文案不变。"""

from __future__ import annotations

import pytest

from thumbelina.tools import perception as p
from thumbelina.tools.base import ToolCategory


@pytest.mark.asyncio
async def test_read_file_missing(tmp_path):
    t = p.ReadFileTool()
    missing = str(tmp_path / "nope")
    assert await t._arun(path=missing) == f"Error: File not found: {missing}"


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
    assert names == {
        "read_file",
        "list_directory",
        "search_files",
        "fetch_url",
        "parse_json",
        "parse_csv",
        "analyze_text",
        "search_text",
    }
    # web_search 受 config 门控,默认不在列表中
    assert "web_search" not in names


@pytest.mark.asyncio
async def test_read_file_ainvoke_lifecycle(tmp_path):
    """经 langchain ainvoke 入口走完整生命周期(security_review→_execute→self_verify)。"""
    f = tmp_path / "life.txt"
    f.write_text("via ainvoke", encoding="utf-8")
    out = await p.ReadFileTool().ainvoke({"path": str(f)})
    assert out == "via ainvoke"


@pytest.mark.asyncio
async def test_search_files_excludes_dependency_dirs(tmp_path):
    """依赖/venv 目录整个子树不进入遍历(2026-09-06 事故:全盘 6 万文件)。"""
    (tmp_path / "root.txt").write_text("needle", encoding="utf-8")
    dep = tmp_path / "node_modules" / "somepkg"
    dep.mkdir(parents=True)
    (dep / "dep.txt").write_text("needle", encoding="utf-8")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "v.txt").write_text("needle", encoding="utf-8")
    gitdir = tmp_path / ".git" / "objects"
    gitdir.mkdir(parents=True)
    (gitdir / "g.txt").write_text("needle", encoding="utf-8")

    result = await p.SearchFilesTool()._arun(pattern="needle", path=str(tmp_path))

    assert "root.txt:1" in result
    assert "node_modules" not in result
    assert ".venv" not in result
    assert ".git" not in result


@pytest.mark.asyncio
async def test_search_files_keeps_event_loop_responsive(tmp_path):
    """同步遍历必须整体放入工作线程:搜索进行中事件循环仍可调度其他协程。

    回归锚点:旧实现把 rglob+read_text 直接跑在事件循环上,一次
    path="." 的全盘搜索冻结整个进程 78 秒(WS 心跳/流式/轮询全部停摆)。
    """
    import asyncio

    # 造一棵没有命中的文件树,迫使搜索完整走完(600 个文件,约 5MB)。
    for i in range(40):
        d = tmp_path / f"d{i:02d}"
        d.mkdir()
        for j in range(15):
            (d / f"f{j:02d}.txt").write_text(("haystack" + chr(10)) * 1000, encoding="utf-8")

    tool = p.SearchFilesTool()
    search_task = asyncio.create_task(
        tool._arun(pattern="zzz-no-hit", path=str(tmp_path))
    )

    ticks = 0
    while not search_task.done():
        ticks += 1
        await asyncio.sleep(0)
        if ticks > 200000:  # 防御性上限,避免病态情况挂死测试
            break
    await search_task

    # 旧实现(阻塞循环)整个搜索期间协程几乎得不到调度(ticks≈2);
    # 新实现搜索在工作线程,主循环空闲自旋,ticks 远大于 5。
    assert ticks > 5, f"event loop starved during search (ticks={ticks})"
