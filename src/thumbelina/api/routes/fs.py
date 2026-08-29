"""Filesystem browsing API routes (server-side directory listing).

Used by the coder workspace picker: the browser has no access to the
server's absolute paths (native directory pickers only expose a name),
so the picker navigates a server-side directory tree instead. Read-only
enumeration of subdirectories; POST /conversations remains the
authoritative workspace validator.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["fs"])

_MAX_LIST_ENTRIES = 1000


class DirEntry(BaseModel):
    name: str
    path: str


class DirListing(BaseModel):
    path: str | None
    parent: str | None
    children: list[DirEntry]
    truncated: bool


class GitInfo(BaseModel):
    is_git: bool
    branch: str | None = None


def _resolve_dir(path: str) -> Path:
    """解析绝对目录路径,非法则 422。"""
    if not path or not path.strip():
        raise HTTPException(status_code=422, detail="路径不能为空")
    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(status_code=422, detail=f"路径必须是绝对路径: {path}")
    try:
        resolved = p.resolve()
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"无效的路径: {exc}")
    if not resolved.is_dir():
        raise HTTPException(status_code=422, detail=f"路径不是有效目录: {path}")
    return resolved


def _run_git(path: str, args: list[str]) -> tuple[int, str, str]:
    """执行只读/短写 git 命令,返回 (returncode, stdout, stderr)。

    git 不存在时返回非零。带超时防挂起。
    """
    if shutil.which("git") is None:
        return 1, "", "git not found"
    try:
        proc = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return 1, "", "git timeout"
    return (
        proc.returncode,
        (proc.stdout or "").strip(),
        (proc.stderr or "").strip(),
    )


def _current_branch(resolved: Path) -> str | None:
    """当前分支名;unborn 分支经 symbolic-ref 返回候选名,detached HEAD 退回 rev-parse。"""
    code, out, _ = _run_git(str(resolved), ["symbolic-ref", "--short", "-q", "HEAD"])
    if code == 0 and out:
        return out
    code, out, _ = _run_git(str(resolved), ["rev-parse", "--abbrev-ref", "HEAD"])
    if code == 0 and out:
        return out
    return None


@router.get("/fs/git", response_model=GitInfo)
def git_info(path: str = Query(...)) -> GitInfo:
    """返回工作区 git 状态;非 git 目录返回 is_git=False。

    用 --is-inside-work-tree 判定仓库(空仓/unborn 分支也是 git 仓库),
    分支名遍历 symbolic-ref → rev-parse 兜底。
    """
    resolved = _resolve_dir(path)
    code, ok, _ = _run_git(str(resolved), ["rev-parse", "--is-inside-work-tree"])
    if code != 0 or ok.strip() != "true":
        return GitInfo(is_git=False, branch=None)
    return GitInfo(is_git=True, branch=_current_branch(resolved))


class GitBranches(BaseModel):
    is_git: bool
    current: str | None = None
    branches: list[str] = []


@router.get("/fs/git/branches", response_model=GitBranches)
def git_branches(path: str = Query(...)) -> GitBranches:
    """列出所有本地分支及当前分支。"""
    resolved = _resolve_dir(path)
    code, out, _ = _run_git(
        str(resolved), ["for-each-ref", "refs/heads", "--format=%(refname:short)"]
    )
    if code != 0:
        return GitBranches(is_git=False)
    branches = sorted(out.splitlines()) if out else []
    return GitBranches(is_git=True, current=_current_branch(resolved), branches=branches)


class GitCheckoutRequest(BaseModel):
    path: str
    branch: str


@router.post("/fs/git/checkout", response_model=GitInfo)
async def git_checkout(body: GitCheckoutRequest) -> GitInfo:
    """切换到指定本地分支;服务端重新枚举校验分支存在,不传 --force。

    分支名只作为 ``git checkout`` 的单独 argv 参数传给 ``_run_git``
    (list-args,无 shell 注入);校验基于服务端枚举结果,不信任客户端。
    冲突等失败返回 409,detail 取 git stderr。
    """
    resolved = _resolve_dir(body.path)
    code, out, _ = await asyncio.to_thread(
        _run_git, str(resolved), ["for-each-ref", "refs/heads", "--format=%(refname:short)"]
    )
    if code != 0:
        raise HTTPException(status_code=422, detail="目录不是 git 仓库")
    branches = out.splitlines()
    if body.branch not in branches:
        raise HTTPException(status_code=422, detail=f"分支不存在: {body.branch}")
    code, _stdout, stderr = await asyncio.to_thread(
        _run_git, str(resolved), ["checkout", body.branch]
    )
    if code != 0:
        raise HTTPException(status_code=409, detail=stderr or f"切换失败: {body.branch}")
    # 广播到所有已连接的 /ws/chat 客户端,前端据此实时刷新状态栏。
    # 函数内导入避免与 websocket 模块潜在循环依赖;内部已吞异常,不影响响应。
    from thumbelina.api.websocket import broadcast_chat_message

    await broadcast_chat_message(
        {"git_branch": {"workspace": str(resolved), "branch": body.branch}}
    )
    return GitInfo(is_git=True, branch=body.branch)


def _list_roots() -> list[DirEntry]:
    listdrives = getattr(os, "listdrives", None)
    if listdrives is not None:
        drives = list(listdrives())
    else:
        drives = [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").exists()]
    return [DirEntry(name=d, path=d) for d in drives]


@router.get("/fs/dirs", response_model=DirListing)
def list_dirs(path: str | None = Query(default=None)) -> DirListing:
    """List subdirectories of a server-side directory.

    With ``path`` omitted, returns the filesystem roots (drive letters on
    Windows, ``/`` on POSIX). With ``path`` given, returns the normalized
    absolute path, its parent (None at a root), and sorted subdirectories.
    Symlinks are skipped: they can point anywhere (outside-workspace
    escapes) and make the picker ambiguous.
    """
    if not path or not path.strip():
        if os.name == "nt":
            return DirListing(path=None, parent=None, children=_list_roots(), truncated=False)
        path = "/"
    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(status_code=422, detail=f"路径必须是绝对路径: {path}")
    try:
        resolved = p.resolve()
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"无效的路径: {exc}")
    if not resolved.is_dir():
        raise HTTPException(status_code=422, detail=f"路径不是有效目录: {path}")
    if resolved.parent != resolved and resolved.parent.exists():
        parent = str(resolved.parent)
    else:
        parent = None
    children: list[DirEntry] = []
    try:
        with os.scandir(str(resolved)) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    children.append(DirEntry(name=entry.name, path=entry.path))
                except OSError:
                    continue
    except (PermissionError, OSError) as exc:
        raise HTTPException(status_code=422, detail=f"目录不可读: {exc}")
    children.sort(key=lambda c: c.name.casefold())
    truncated = len(children) > _MAX_LIST_ENTRIES
    return DirListing(
        path=str(resolved),
        parent=parent,
        children=children[:_MAX_LIST_ENTRIES],
        truncated=truncated,
    )
