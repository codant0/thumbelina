"""Filesystem browsing API routes (server-side directory listing).

Used by the coder workspace picker: the browser has no access to the
server's absolute paths (native directory pickers only expose a name),
so the picker navigates a server-side directory tree instead. Read-only
enumeration of subdirectories; POST /conversations remains the
authoritative workspace validator.
"""

from __future__ import annotations

import os
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
