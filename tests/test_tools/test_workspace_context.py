"""Tests for per-conversation workspace context propagation."""

from __future__ import annotations

import asyncio

import pytest

from thumbelina.tools.perception import ReadFileTool
from thumbelina.tools.workspace_context import get_workspace, set_workspace

read_file = ReadFileTool()


@pytest.mark.asyncio
async def test_set_and_get_workspace():
    set_workspace("/tmp/ws")
    try:
        assert get_workspace() == "/tmp/ws"
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_workspace_contextvar_isolation(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "f.txt").write_text("A")
    (b / "f.txt").write_text("B")

    async def work(ws: str):
        set_workspace(ws)
        await asyncio.sleep(0.01)
        return await read_file.ainvoke({"path": "f.txt"})

    results = await asyncio.gather(work(str(a)), work(str(b)))
    assert set(results) == {"A", "B"}
