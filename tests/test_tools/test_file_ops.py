"""Tests for file operation tools."""

from __future__ import annotations

import pytest

from thumbelina.tools.file_ops import list_directory, read_file, search_files, write_file
from thumbelina.tools.workspace_context import set_workspace


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


@pytest.mark.asyncio
async def test_workspace_relative_read(tmp_path):
    set_workspace(str(tmp_path))
    try:
        (tmp_path / "in.txt").write_text("inside")
        result = await read_file.ainvoke({"path": "in.txt"})
        assert result == "inside"
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_workspace_boundary_read_rejected(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    set_workspace(str(tmp_path))
    try:
        result = await read_file.ainvoke({"path": str(outside)})
        assert "超出工作区" in result
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_workspace_boundary_traversal_rejected(tmp_path):
    (tmp_path / "sub").mkdir()
    set_workspace(str(tmp_path / "sub"))
    try:
        result = await read_file.ainvoke({"path": "../escape.txt"})
        assert "超出工作区" in result
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_workspace_relative_write(tmp_path):
    set_workspace(str(tmp_path))
    try:
        result = await write_file.ainvoke({"path": "new.txt", "content": "x"})
        assert "Successfully wrote" in result
        assert (tmp_path / "new.txt").read_text() == "x"
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_search_files_finds_regex(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    (tmp_path / "b.txt").write_text("no match here")
    result = await search_files.ainvoke({"pattern": "foo"})
    assert "a.py:1:" in result
    assert "b.txt" not in result


@pytest.mark.asyncio
async def test_search_files_respects_workspace_boundary(tmp_path):
    outside = tmp_path.parent / "outside_search"
    outside.mkdir(exist_ok=True)
    (outside / "hit.txt").write_text("token")
    set_workspace(str(tmp_path))
    try:
        result = await search_files.ainvoke({"pattern": "token", "path": str(outside)})
        assert "超出工作区" in result
    finally:
        set_workspace(None)
