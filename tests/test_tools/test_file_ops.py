"""Tests for file operation tools."""

from __future__ import annotations

import pytest

from thumbelina.tools.file_ops import list_directory, read_file, write_file


@pytest.mark.asyncio
async def test_write_and_read_file(tmp_path):
    path = str(tmp_path / "test.txt")
    result = await write_file.ainvoke({"path": path, "content": "hello world"})
    assert "Successfully wrote" in result

    content = await read_file.ainvoke({"path": path})
    assert content == "hello world"


@pytest.mark.asyncio
async def test_read_nonexistent_file():
    result = await read_file.ainvoke({"path": "/nonexistent/file.txt"})
    assert "Error: File not found" in result


@pytest.mark.asyncio
async def test_list_directory(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = await list_directory.ainvoke({"path": str(tmp_path)})
    assert "[f] a.txt" in result
    assert "[f] b.txt" in result


@pytest.mark.asyncio
async def test_list_directory_empty(tmp_path):
    result = await list_directory.ainvoke({"path": str(tmp_path)})
    assert "(empty directory)" in result


@pytest.mark.asyncio
async def test_list_nonexistent_directory():
    result = await list_directory.ainvoke({"path": "/nonexistent/dir"})
    assert "Error: Directory not found" in result
