# 码农（Coder）模式实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 WEB 顶部导航"聊天"右侧新增"码农"入口，提供绑定服务器工作区的 Code Agent 会话：工作区信息注入系统提示词、左侧按工作区分组、`mode` 区分会话类型、默认 `coder` 角色。

**Architecture:** 方案 A（轻量复用）：`conversations` 表加 `mode`/`workspace` 两列（`ensure_schema` 自动迁移），复用现有会话/角色/WebSocket/检查点管线；工具经 contextvar 感知工作区并做边界校验，新增 `search_files`；前端新增独立"码农"页（`CoderPage` = `CoderSidebar` + 复用 `ChatWindow`），复用 `App.tsx` 持有的 WebSocket。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2 / LangGraph；React 19 / TypeScript / Vite / Vitest / lucide-react。

**Spec:** `docs/plans/2026-08-22-coder-mode-design.md`

## Global Constraints

- 数据模型变更只依赖 `ensure_schema`（`repository/models.py`），不加 Alembic。
- 工具的 `workspace` 一律通过 contextvar 传递（`workspace_context.py`），**禁止**给工具函数加 `workspace` 形参（会污染 LangChain 工具 schema）。
- i18n 新键必须同时添加 `frontend/src/i18n/locales/en.json` 与 `zh-CN.json`。
- 后端测试命令：`python -m pytest`；前端：`cd frontend && npm test`；lint：`ruff check src tests`。
- 提交信息用中文，前缀 `feat:` / `fix:` / `docs:`；用选择性 `git add`（只加本任务涉及文件）。
- 路径边界校验一律 `Path.resolve()` 后判定，禁止用字符串前缀匹配。
- 工作区在创建后不变更；`PATCH /conversations/{id}` 只接受 `name`（现行为，不扩展）。

---

### Task 1: Conversation 模型与仓储支持 mode/workspace

**Files:**
- Modify: `src/thumbelina/repository/models.py`（`Conversation`，约 155-160 行 `role` 之后）
- Modify: `src/thumbelina/repository/repository.py`（`_create_conversation_sync` 56-63、`create_conversation` 65-80、`_get_conversations_sync` 186-212、`create_conversation` 调用 get_conversations 处、`_get_all_conversations_with_messages_sync` 224-259、`_get_conversation_sync` 268-289、`get_conversations` 214-222）
- Modify: `src/thumbelina/repository/manager.py`（`create_conversation` 41-56）
- Test: `tests/test_repository/test_repository.py`

**Interfaces:**
- Produces: `Conversation` ORM 新增 `mode: Mapped[str]`（默认 `"chat"`）与 `workspace: Mapped[str | None]`；`ConversationRepository.create_conversation(name, pinned, mode="chat", workspace=None, role=None)`、`get_conversations(mode: str | None = None)`；`RepositoryManager.create_conversation(name=None, pinned=False, mode="chat", workspace=None, role=None)`；所有会话 dict 均含 `mode`、`workspace` 键。

- [ ] **Step 1: 写入失败测试**

`tests/test_repository/test_repository.py` 追加：

```python
from thumbelina.repository.repository import ConversationRepository


def _repo(tmp_path) -> ConversationRepository:
    return ConversationRepository(f"sqlite:///{tmp_path / 'repo.db'}")


def test_create_conversation_with_coder_mode_and_workspace(tmp_path):
    repo = _repo(tmp_path)
    conv_id = repo.create_conversation(name="coder1", mode="coder", workspace=str(tmp_path), role="coder")
    conv = repo.get_conversation(conv_id)
    assert conv["mode"] == "coder"
    assert conv["workspace"] == str(tmp_path)
    assert conv["role"] == "coder"


def test_conversation_defaults_to_chat_mode(tmp_path):
    repo = _repo(tmp_path)
    conv_id = repo.create_conversation()
    conv = repo.get_conversation(conv_id)
    assert conv["mode"] == "chat"
    assert conv["workspace"] is None


def test_get_conversations_filters_by_mode(tmp_path):
    repo = _repo(tmp_path)
    coder_id = repo.create_conversation(mode="coder", workspace=str(tmp_path))
    chat_id = repo.create_conversation()
    coder_ids = {c["id"] for c in repo.get_conversations(mode="coder")}
    chat_ids = {c["id"] for c in repo.get_conversations(mode="chat")}
    assert coder_id in coder_ids
    assert chat_id in chat_ids
    assert coder_id not in chat_ids
    assert chat_id not in coder_ids
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_repository/test_repository.py -k "coder or mode" -v`
Expected: FAIL（TypeError：`create_conversation()` 收到意外的关键字参数 `mode`；`get_conversation` 结果无 `mode` 键）

- [ ] **Step 3: 实现模型字段**

`src/thumbelina/repository/models.py` 在 `role` 字段（155-160 行）之后插入：

```python
    mode: Mapped[str] = mapped_column(
        String(20),
        default="chat",
        comment="Conversation mode: 'chat' (normal) or 'coder' (workspace-bound code agent)",
    )
    workspace: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
        comment="Absolute workspace directory path for coder conversations; NULL for chat mode",
    )
```

- [ ] **Step 4: 实现仓储层**

`src/thumbelina/repository/repository.py`：

`_create_conversation_sync`（56-63 行）改为：

```python
    def _create_conversation_sync(
        self,
        name: str | None = None,
        pinned: bool = False,
        mode: str = "chat",
        workspace: str | None = None,
        role: str | None = None,
    ) -> str:
        """Synchronous implementation of create_conversation."""
        with self._get_session() as session:
            conversation = Conversation(
                name=name, pinned=pinned, mode=mode, workspace=workspace, role=role
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation.id
```

`create_conversation`（65-80 行）签名同步扩展并透传：

```python
    async def create_conversation(
        self,
        name: str | None = None,
        pinned: bool = False,
        mode: str = "chat",
        workspace: str | None = None,
        role: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._create_conversation_sync, name, pinned, mode, workspace, role
        )
```

`_get_conversations_sync`（186-212 行）加过滤参数，并在 dict 中补两键：

```python
    def _get_conversations_sync(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Synchronous implementation of get_conversations."""
        with self._get_session() as session:
            stmt = select(Conversation).order_by(
                Conversation.pinned.desc(),
                Conversation.updated_at.desc(),
            )
            if mode is not None:
                stmt = stmt.where(Conversation.mode == mode)
            result = session.execute(stmt)
            conversations = result.scalars().all()

            return [
                {
                    "id": conv.id,
                    "name": conv.name,
                    "pinned": conv.pinned or False,
                    "mode": conv.mode or "chat",
                    "workspace": conv.workspace,
                    "endpoint_id": conv.endpoint_id,
                    "model": conv.model,
                    "knowledge_base_id": conv.knowledge_base_id,
                    "role": conv.role,
                    "thinking_enabled": conv.thinking_enabled or False,
                    "thinking_effort": conv.thinking_effort or "medium",
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "summary": conv.summary,
                }
                for conv in conversations
            ]
```

`get_conversations`（214-222 行）：

```python
    async def get_conversations(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Get conversations, optionally filtered by mode."""
        return await asyncio.to_thread(self._get_conversations_sync, mode)
```

其余两处 dict 构造补键：`_get_all_conversations_with_messages_sync`（约 235-248 行，在 `"role": conv.role,` 后加 `"mode": conv.mode or "chat", "workspace": conv.workspace,`）与 `_get_conversation_sync`（约 280-288 行，同样位置加两键）。

`src/thumbelina/repository/manager.py` 的 `create_conversation`（41-56 行）签名与透传同步扩展：

```python
    async def create_conversation(
        self,
        name: str | None = None,
        pinned: bool = False,
        mode: str = "chat",
        workspace: str | None = None,
        role: str | None = None,
    ) -> str:
        """Create a new conversation.

        Parameters
        ----------
        name:
            Optional human-readable name for the conversation.
        pinned:
            Whether to pin the conversation to the top of the list.
        mode:
            Conversation mode: 'chat' (default) or 'coder'.
        workspace:
            Absolute workspace directory path for coder conversations.
        role:
            Optional persona role; coder conversations default to 'coder' (set by the API layer).

        Returns
        -------
        str
            The ID of the newly created conversation.
        """
        return await self.conversation_repository.create_conversation(
            name=name, pinned=pinned, mode=mode, workspace=workspace, role=role
        )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_repository/test_repository.py -k "coder or mode" -v`
Expected: PASS（3 个新测试全过，存量测试不受影响——可再跑 `python -m pytest tests/test_repository` 确认无回归）

- [ ] **Step 6: 提交**

```bash
git add src/thumbelina/repository/models.py src/thumbelina/repository/repository.py src/thumbelina/repository/manager.py tests/test_repository/test_repository.py
git commit -m "feat: 会话模型与仓储支持 mode/workspace 字段"
```

---

### Task 2: 会话 API 的创建校验与 mode 过滤

**Files:**
- Modify: `src/thumbelina/api/schemas.py`（`ConversationSchema` 35-49、`ConversationDetailSchema` 52-67）
- Modify: `src/thumbelina/api/routes/conversations.py`（`CreateConversationRequest` 43-47、`create_conversation` 112-124、`list_conversations` 140-148；文件顶部需 `from pathlib import Path`，`Query` 若未导入则从 fastapi 补）
- Test: `tests/test_api/test_conversations.py`

**Interfaces:**
- Consumes: Task 1 的 `RepositoryManager.create_conversation(..., mode, workspace, role)` 与 `get_conversations(mode)`。
- Produces: `POST /api/v1/conversations` 接受 `{mode, workspace}`；`GET /api/v1/conversations?mode=coder|chat`；响应含 `mode`/`workspace`。

- [ ] **Step 1: 写入失败测试**

`tests/test_api/test_conversations.py` 追加（`client` fixture 已存在）：

```python
def test_create_coder_conversation_with_workspace(client, tmp_path):
    response = client.post(
        "/api/v1/conversations",
        json={"mode": "coder", "workspace": str(tmp_path)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "coder"
    assert data["workspace"] == str(tmp_path.resolve())
    assert data["role"] == "coder"


def test_create_coder_without_workspace_rejected(client):
    response = client.post("/api/v1/conversations", json={"mode": "coder"})
    assert response.status_code == 422


def test_create_coder_with_missing_workspace_rejected(client, tmp_path):
    response = client.post(
        "/api/v1/conversations",
        json={"mode": "coder", "workspace": str(tmp_path / "nonexistent")},
    )
    assert response.status_code == 422


def test_chat_conversation_with_workspace_rejected(client):
    response = client.post("/api/v1/conversations", json={"workspace": "C:\\"})
    assert response.status_code == 422


def test_list_conversations_filters_by_mode(client, tmp_path):
    client.post("/api/v1/conversations", json={"mode": "coder", "workspace": str(tmp_path)})
    client.post("/api/v1/conversations", json={})
    coder_ids = [c["id"] for c in client.get("/api/v1/conversations?mode=coder").json()]
    chat_ids = [c["id"] for c in client.get("/api/v1/conversations?mode=chat").json()]
    assert len(coder_ids) == 1
    assert all(cid not in chat_ids for cid in coder_ids)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api/test_conversations.py -k "coder or workspace or filters_by_mode" -v`
Expected: FAIL（422 vs 200 之类——现端点不接受 mode/workspace：未过滤时列表包含全部）

- [ ] **Step 3: 实现 Schema**

`src/thumbelina/api/schemas.py` 在 `ConversationSchema` 与 `ConversationDetailSchema` 中 `pinned` 之后各加：

```python
    mode: str = "chat"
    workspace: str | None = None
```

- [ ] **Step 4: 实现创建校验与列表过滤**

`src/thumbelina/api/routes/conversations.py`：

`CreateConversationRequest` 改为：

```python
class CreateConversationRequest(BaseModel):
    """Request body for creating a new conversation."""

    name: str | None = Field(default=None, description="Optional conversation name")
    pinned: bool = Field(default=False, description="Whether to pin the conversation")
    mode: Literal["chat", "coder"] = Field(
        default="chat", description="Conversation mode: 'chat' or 'coder'"
    )
    workspace: str | None = Field(
        default=None,
        description="Absolute workspace directory path; required when mode='coder'",
    )
```

在 `_clear_checkpoint`（文件头部辅助函数区）旁新增校验辅助函数：

```python
def _validate_workspace(mode: str, workspace: str | None) -> str | None:
    """校验并规范化工作区路径；非法时抛 422。"""
    if mode == "coder":
        if not workspace or not workspace.strip():
            raise HTTPException(
                status_code=422, detail="mode='coder' 需要提供 workspace 路径"
            )
        try:
            path = Path(workspace).resolve()
        except OSError as exc:
            raise HTTPException(status_code=422, detail=f"无效的工作区路径: {exc}")
        if not path.is_dir():
            raise HTTPException(
                status_code=422, detail=f"工作区不是有效目录: {workspace}"
            )
        try:
            next(path.iterdir(), None)
        except (PermissionError, OSError) as exc:
            raise HTTPException(
                status_code=422, detail=f"工作区不可读: {exc}"
            )
        return str(path)
    if workspace:
        raise HTTPException(status_code=422, detail="普通会话不允许设置 workspace")
    return None
```

`create_conversation` 端点改为：

```python
@router.post("/conversations", response_model=ConversationSchema)
async def create_conversation(
    body: CreateConversationRequest | None = None,
    repository: RepositoryManager = Depends(get_repository_manager),
) -> ConversationSchema:
    """Create a new conversation."""
    name = body.name if body else None
    pinned = body.pinned if body else False
    mode = body.mode if body else "chat"
    workspace = _validate_workspace(mode, body.workspace) if body else None
    role = "coder" if mode == "coder" else None
    conv_id = await repository.create_conversation(
        name=name, pinned=pinned, mode=mode, workspace=workspace, role=role
    )
    conv = await repository.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=500, detail="Failed to create conversation")
    return ConversationSchema(**conv)
```

`list_conversations` 端点改为：

```python
@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations(
    mode: Literal["chat", "coder"] | None = Query(
        default=None, description="Filter conversations by mode"
    ),
    repository: RepositoryManager = Depends(get_repository_manager),
) -> list[ConversationSchema]:
    """List conversations, optionally filtered by mode."""
    try:
        conversations = await repository.get_conversations(mode=mode)
        logger.debug("Fetched %d conversations", len(conversations))
        return [ConversationSchema(**c) for c in conversations]
    except Exception:
        ...
```

（省略号处保留文件原有 except 逻辑不动。）若 `Query` 未导入，在 fastapi 导入行加 `Query`；确认 `from typing import Literal` 已导入（`SetConversationThinkingRequest` 已在用 Literal）。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_api/test_conversations.py -v`
Expected: PASS（新 5 个 + 存量全过）

- [ ] **Step 6: 提交**

```bash
git add src/thumbelina/api/schemas.py src/thumbelina/api/routes/conversations.py tests/test_api/test_conversations.py
git commit -m "feat: 会话 API 支持 mode/workspace 创建校验与过滤"
```

---

### Task 3: 工具工作区上下文、边界校验与 search_files

**Files:**
- Create: `src/thumbelina/tools/workspace_context.py`
- Modify: `src/thumbelina/tools/file_ops.py`（全部）
- Modify: `src/thumbelina/tools/shell.py`（`run_shell` 12-31）
- Modify: `src/thumbelina/tools/__init__.py`（导入、`__all__`、`get_all_tools`）
- Test: `tests/test_tools/test_file_ops.py`、`tests/test_tools/test_shell.py`、`tests/test_tools/test_workspace_context.py`（新建）

**Interfaces:**
- Produces: `workspace_context.py` 暴露 `set_workspace(workspace: str | None) -> None`、`get_workspace() -> str | None`、`resolve_workspace_path(path: str) -> Path | None`（无工作区返回 `None`；越界抛 `ValueError`，消息以「路径超出工作区」开头）。`file_ops` 新增 `search_files(pattern: str, path: str = ".") -> str` 工具；有工作区时四个文件工具相对路径以工作区为根。`run_shell` 有工作区时 `cwd=workspace`。

- [ ] **Step 1: 写入失败测试**

`tests/test_tools/test_workspace_context.py`（新建）：

```python
"""Tests for per-conversation workspace context propagation."""

from __future__ import annotations

import asyncio

import pytest

from thumbelina.tools.file_ops import read_file
from thumbelina.tools.workspace_context import get_workspace, set_workspace


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
```

`tests/test_tools/test_file_ops.py` 追加：

```python
from thumbelina.tools.file_ops import list_directory, read_file, write_file, search_files
from thumbelina.tools.workspace_context import set_workspace


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
```

`tests/test_tools/test_shell.py` 追加：

```python
from thumbelina.tools.shell import run_shell
from thumbelina.tools.workspace_context import set_workspace


@pytest.mark.asyncio
async def test_run_shell_uses_workspace_cwd(tmp_path):
    set_workspace(str(tmp_path))
    try:
        result = await run_shell.ainvoke(
            {"command": "python -c \"import os; print(os.getcwd())\""}
        )
        assert str(tmp_path) in result
    finally:
        set_workspace(None)
```

（若 `test_shell.py` 已有 `run_shell` 导入，合并导入行，勿重复。）

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_tools -v`
Expected: FAIL（`workspace_context` 模块不存在 → ImportError；`search_files` 不存在 → ImportError）

- [ ] **Step 3: 创建 workspace_context 模块**

`src/thumbelina/tools/workspace_context.py`：

```python
"""Per-conversation workspace context for built-in tools.

工作区通过 ``ContextVar`` 注入：``apply_conversation_runtime`` 在每个
会话各自的 asyncio 任务开头设置，工具函数内部读取；对 LLM 不可见，
也不会出现在工具 schema 中。无工作区（普通会话）时所有行为与既有一致。
"""

from __future__ import annotations

import contextvars
from pathlib import Path

_current_workspace: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_workspace", default=None
)


def set_workspace(workspace: str | None) -> None:
    """Set the workspace path for the current execution context."""
    _current_workspace.set(workspace)


def get_workspace() -> str | None:
    """Return the workspace path active in the current context, if any."""
    return _current_workspace.get()


def resolve_workspace_path(path: str) -> Path | None:
    """Resolve *path* against the active workspace, enforcing its boundary.

    Returns ``None`` when no workspace is active (legacy behavior).
    Raises ``ValueError`` (message starts with 路径超出工作区) when the
    resolved path escapes the workspace.
    """
    workspace = _current_workspace.get()
    if not workspace:
        return None
    workspace_root = Path(workspace).resolve()
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(workspace_root):
        raise ValueError(f"路径超出工作区 {workspace_root}: {path}")
    return resolved
```

- [ ] **Step 4: 改造 file_ops 与 shell**

`src/thumbelina/tools/file_ops.py` 整体改为（保留原行为，增加工作区分支与 search_files）：

```python
"""File operation tools for the Thumbelina agent."""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from thumbelina.tools.workspace_context import resolve_workspace_path

_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
_SEARCH_MAX_HITS = 50
_SEARCH_MAX_LINE = 500
_SEARCH_MAX_FILE = 1 * 1024 * 1024


def _resolve_target(path: str) -> Path:
    """解析路径；有工作区时按工作区根解析并强制边界，无则保持原行为。"""
    resolved = resolve_workspace_path(path)
    if resolved is None:
        return Path(path).resolve()
    return resolved


@tool
async def read_file(path: str) -> str:
    """Read the contents of a file. Returns up to 1MB of text."""
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


@tool
async def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    try:
        p = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except OSError as exc:
        return f"Error writing file: {exc}"


@tool
async def list_directory(path: str = ".") -> str:
    """List files and directories in the given path."""
    try:
        p = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    if not p.exists():
        return f"Error: Directory not found: {path}"
    if not p.is_dir():
        return f"Error: Not a directory: {path}"
    try:
        entries = sorted(p.iterdir())
        lines = []
        for entry in entries:
            kind = "d" if entry.is_dir() else "f"
            lines.append(f"[{kind}] {entry.name}")
        if not lines:
            return "(empty directory)"
        return "\n".join(lines)
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except OSError as exc:
        return f"Error listing directory: {exc}"


@tool
async def search_files(pattern: str, path: str = ".") -> str:
    """Search for a regex pattern in files under the given path.

    Returns up to 50 matches as 'path:line: content' lines. Binary files
    and files larger than 1MB are skipped.
    """
    try:
        root = _resolve_target(path)
    except ValueError as exc:
        return f"Error: {exc}"
    if not root.exists():
        return f"Error: Directory not found: {path}"
    if not root.is_dir():
        return f"Error: Not a directory: {path}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: Invalid pattern: {exc}"
    hits: list[str] = []
    try:
        for entry in root.rglob("*"):
            if not entry.is_file():
                continue
            if entry.stat().st_size > _SEARCH_MAX_FILE:
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="ignore")
            except (PermissionError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{entry}:{lineno}: {line[:_SEARCH_MAX_LINE]}")
                if len(hits) >= _SEARCH_MAX_HITS:
                    break
            if len(hits) >= _SEARCH_MAX_HITS:
                break
    except (PermissionError, OSError) as exc:
        return f"Error searching: {exc}"
    if not hits:
        return f"No matches for {pattern!r} under {path}"
    return "\n".join(hits)
```

`src/thumbelina/tools/shell.py` 的 `run_shell` 增加 `cwd`：

```python
@tool
async def run_shell(command: str) -> str:
    """Execute a shell command and return stdout+stderr. Timeout: 30 seconds."""
    cwd = get_workspace()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            shell=True,
            cwd=cwd,
        )
```

并在导入区加 `from thumbelina.tools.workspace_context import get_workspace`。

`src/thumbelina/tools/__init__.py`：

```python
from thumbelina.tools.file_ops import list_directory, read_file, search_files, write_file
```

`__all__` 加 `"search_files"`；`get_all_tools()` 列表在 `list_directory` 后加 `search_files`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_tools -v`
Expected: PASS（全部新测试 + 存量）

- [ ] **Step 6: 提交**

```bash
git add src/thumbelina/tools/workspace_context.py src/thumbelina/tools/file_ops.py src/thumbelina/tools/shell.py src/thumbelina/tools/__init__.py tests/test_tools/
git commit -m "feat: 工具增加工作区上下文边界校验与 search_files"
```

---

### Task 4: 运行时注入工作区：提示词、contextvar 与 coder 角色提示微调

**Files:**
- Modify: `src/thumbelina/api/routes/chat.py`（`apply_conversation_runtime` 257-266，新增 `_apply_conversation_workspace`）
- Modify: `src/thumbelina/agent/graph.py`（模块级新增 `build_workspace_context`；`__init__` 增加 `workspace` 参数；`clone()` 1124-1148 透传；`_build_initial_messages` 927-981 首轮注入）
- Modify: `src/thumbelina/prompts/roles/coder.md`（追加一行）
- Test: `tests/test_agent/test_workspace_context.py`（新建）、`tests/test_api/test_conversations.py` 或 `tests/test_api` 下新增 `test_workspace_runtime.py`

**Interfaces:**
- Consumes: Task 3 的 `set_workspace` / `get_workspace`。
- Produces: `apply_conversation_runtime` 会顺带设置 `agent.workspace` 与 contextvar；`build_workspace_context(workspace: str | None) -> str | None`（纯函数，供测试直接调用）；`ThumbelinaAgent.__init__` 新增 `workspace: str | None = None`。

- [ ] **Step 1: 写入失败测试**

`tests/test_agent/test_workspace_context.py`（新建）：

```python
"""Tests for workspace context building and runtime injection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thumbelina.agent.graph import build_workspace_context


def test_build_workspace_context_none():
    assert build_workspace_context(None) is None
    assert build_workspace_context("") is None


def test_build_workspace_context_contains_path_and_snapshot(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    ctx = build_workspace_context(str(tmp_path))
    assert ctx is not None
    assert str(tmp_path) in ctx
    assert "pyproject.toml" in ctx
    assert "禁止越界" in ctx


def test_build_workspace_context_missing_dir_degrades_to_path(tmp_path):
    missing = str(tmp_path / "gone")
    ctx = build_workspace_context(missing)
    assert ctx is not None
    assert missing in ctx


@pytest.mark.asyncio
async def test_apply_conversation_runtime_sets_workspace(tmp_path):
    from thumbelina.api.routes.chat import apply_conversation_runtime
    from thumbelina.tools.workspace_context import get_workspace, set_workspace

    repo = SimpleNamespace(
        get_conversation=AsyncMock(return_value={"role": None, "workspace": str(tmp_path)})
    )
    agent = SimpleNamespace(
        repository_manager=repo, role="assistant", role_prompt="x", workspace=None
    )
    context = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(endpoint_manager=None))
    )
    try:
        await apply_conversation_runtime(context, agent, "cid")
        assert agent.workspace == str(tmp_path)
        assert get_workspace() == str(tmp_path)
    finally:
        set_workspace(None)


@pytest.mark.asyncio
async def test_apply_conversation_runtime_without_workspace(tmp_path):
    from thumbelina.api.routes.chat import apply_conversation_runtime
    from thumbelina.tools.workspace_context import get_workspace, set_workspace

    repo = SimpleNamespace(
        get_conversation=AsyncMock(return_value={"role": None, "workspace": None})
    )
    agent = SimpleNamespace(
        repository_manager=repo, role="assistant", role_prompt="x", workspace=None
    )
    context = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(endpoint_manager=None))
    )
    try:
        await apply_conversation_runtime(context, agent, "cid")
        assert agent.workspace is None
        assert get_workspace() is None
    finally:
        set_workspace(None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent/test_workspace_context.py -v`
Expected: FAIL（`build_workspace_context` 不存在 → ImportError；`apply_conversation_runtime` 未设置 workspace）

- [ ] **Step 3: 实现 build_workspace_context 与首轮注入**

`src/thumbelina/agent/graph.py`：

文件顶部（`from pathlib import Path` 若未导入则补上）模块级新增：

```python
WORKSPACE_SNAPSHOT_LIMIT = 50


def build_workspace_context(workspace: str | None) -> str | None:
    """构造工作区 SystemMessage 内容。

    工作区路径 + 顶层目录快照（深度 1，最多 50 条）；目录不可读或
    已删除时退化为仅路径。
    """
    if not workspace:
        return None
    lines = [
        f"当前工作区：{workspace}",
        "文件工具的相对路径以该工作区为根，禁止越界访问。",
    ]
    try:
        root = Path(workspace).resolve()
        if root.is_dir():
            entries = sorted(root.iterdir())[:WORKSPACE_SNAPSHOT_LIMIT]
            if entries:
                lines.append("工作区顶层内容：")
                for entry in entries:
                    kind = "d" if entry.is_dir() else "f"
                    lines.append(f"- [{kind}] {entry.name}")
            else:
                lines.append("工作区顶层为空。")
    except OSError:
        pass
    return "\n".join(lines)
```

`ThumbelinaAgent.__init__` 增加参数（在 `role` 参数附近）：

```python
            workspace: str | None = None,  # 码农会话绑定的工作区路径
```

并在 __init__ 内赋值 `self.workspace = workspace`。

`clone()`（1124-1148）的构造调用中，`role=self.role,` 之后加一行 `workspace=self.workspace,`。

`_build_initial_messages` 中，`if first_turn:` 块内、`memory_context` 注入之后追加：

```python
            workspace_context = build_workspace_context(self.workspace)
            if workspace_context:
                messages.append(SystemMessage(content=workspace_context))
                traj_items.append({"kind": "workspace", "content": workspace_context})
```

- [ ] **Step 4: 实现 apply_conversation_runtime 注入**

`src/thumbelina/api/routes/chat.py`：

文件顶部导入（与 `get_role_prompt` 同一处导入区）：

```python
from thumbelina.tools.workspace_context import set_workspace
```

`apply_conversation_runtime` 改为：

```python
async def apply_conversation_runtime(
    context: Any, agent: ThumbelinaAgent, conversation_id: str
) -> None:
    """应用会话的端点、角色与工作区（HTTP / WebSocket / 通道共用）。

    ``context`` 只需暴露 ``app.state``（``Request``、``WebSocket`` 或
    指向 ``app.state`` 的轻量 shim 均可）。
    """
    await _apply_conversation_endpoint(context, agent, conversation_id)
    await _apply_conversation_role(agent, conversation_id)
    await _apply_conversation_workspace(agent, conversation_id)


async def _apply_conversation_workspace(
    agent: ThumbelinaAgent, conversation_id: str
) -> None:
    """将会话绑定的工作区注入 agent 克隆与工具执行上下文。"""
    repository = agent.repository_manager
    if repository is None:
        return
    try:
        conv = await repository.get_conversation(conversation_id)
    except Exception:
        return
    if conv is None:
        return
    workspace = conv.get("workspace")
    agent.workspace = workspace
    set_workspace(workspace)
```

- [ ] **Step 5: 微调 coder 角色提示**

`src/thumbelina/prompts/roles/coder.md` 追加一行：

```markdown
- 工作区内的文件操作优先使用相对路径；动手前先用 search_files / list_directory 了解项目结构。
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_agent/test_workspace_context.py tests/test_prompts -v`
Expected: PASS（新测试 + 角色文件解析测试不回归）

- [ ] **Step 7: 提交**

```bash
git add src/thumbelina/api/routes/chat.py src/thumbelina/agent/graph.py src/thumbelina/prompts/roles/coder.md tests/test_agent/test_workspace_context.py
git commit -m "feat: 会话运行时注入工作区上下文与提示词"
```

---

### Task 5: 前端基础——类型、API 助手、导航入口与 i18n

**Files:**
- Modify: `frontend/src/types/chat.ts`（`Conversation` 18-32）
- Modify: `frontend/src/api/conversations.ts`（首部）
- Modify: `frontend/src/components/Layout/Header.tsx`（`Page` 17、`navKeys` 19、`NAV_ICONS` 21-32、`NAV_I18N` 39-50、lucide 导入）
- Modify: `frontend/src/i18n/locales/zh-CN.json`、`frontend/src/i18n/locales/en.json`（`nav` 段）
- Test: `frontend/src/components/Layout/Header.test.tsx`

**Interfaces:**
- Produces: `fetchConversations(mode?: 'chat' | 'coder')`、`createConversation(options?: { name?, pinned?, mode?, workspace? })`（均抛 `Error(data.detail)`）；`Page` 含 `'coder'`，`nav-coder` testid 存在。

- [ ] **Step 1: 写入失败测试**

`frontend/src/components/Layout/Header.test.tsx` 追加：

```tsx
  it('renders the coder nav entry after chat', () => {
    render(<Header activePage="chat" onNavigate={vi.fn()} />)
    expect(screen.getByTestId('nav-coder')).toBeInTheDocument()
    const nav = screen.getByRole('navigation')
    const labels = Array.from(nav.querySelectorAll('button')).map(b => b.getAttribute('data-testid'))
    expect(labels.indexOf('nav-coder')).toBe(labels.indexOf('nav-chat') + 1)
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/components/Layout/Header.test.tsx`
Expected: FAIL（`nav-coder` 不存在）

- [ ] **Step 3: 实现类型与 API 助手**

`frontend/src/types/chat.ts`，`Conversation` 中 `pinned` 之后加：

```ts
  mode?: 'chat' | 'coder'
  workspace?: string | null
```

`frontend/src/api/conversations.ts`，`API_BASE` 定义之后加：

```ts
export async function fetchConversations(mode?: 'chat' | 'coder'): Promise<Conversation[]> {
  const query = mode ? `?mode=${mode}` : ''
  const res = await fetch(`${API_BASE}/conversations${query}`)
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? data : []
}

export async function createConversation(options: {
  name?: string
  pinned?: boolean
  mode?: 'chat' | 'coder'
  workspace?: string
} = {}): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}
```

- [ ] **Step 4: 实现导航入口与 i18n**

`frontend/src/components/Layout/Header.tsx`：

- lucide 导入加 `Code2`；
- `Page` 联合类型与 `navKeys` 中 `'chat'` 之后插入 `'coder'`；
- `NAV_ICONS` 加 `coder: Code2`；
- `NAV_I18N` 加 `coder: 'nav.coder'`。

`zh-CN.json` 的 `nav` 段 `"chat"` 之后加 `"coder": "码农"`；`en.json` 的 `nav` 段 `"chat"` 之后加 `"coder": "Coder"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/components/Layout/Header.test.tsx`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/src/types/chat.ts frontend/src/api/conversations.ts frontend/src/components/Layout/Header.tsx frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json frontend/src/components/Layout/Header.test.tsx
git commit -m "feat: 前端新增码农导航入口与类型/API 助手"
```

---

### Task 6: CoderPage、CoderSidebar、WorkspacePicker 与 App 集成

**Files:**
- Create: `frontend/src/components/Coder/CoderSidebar.tsx`
- Create: `frontend/src/components/Coder/WorkspacePicker.tsx`
- Create: `frontend/src/components/Coder/CoderPage.tsx`
- Modify: `frontend/src/App.tsx`（imports、coder 状态与回调、`renderPage` 新增 `case 'coder'`、聊天页 fetch 加 `mode=chat`）
- Modify: `frontend/src/App.css`（coder 分组样式）
- Modify: `frontend/src/i18n/locales/zh-CN.json`、`en.json`（`coder.*` 键）
- Test: `frontend/src/components/Coder/CoderSidebar.test.tsx`、`frontend/src/components/Coder/WorkspacePicker.test.tsx`、`frontend/src/App.pageSwitch.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `fetchConversations` / `createConversation`；既有 `ChatWindow` props。
- Produces: `<CoderPage ws conversations selectedId onSelect onCreated onDelete onRename onRefresh onSetEndpoint onSetKnowledgeBase onSetRole onSetThinking onViewTrajectory />`（`onCreated: (id: string) => void`，由 WorkspacePicker 创建成功后回调新会话 id）。

- [ ] **Step 1: 写入失败测试**

`frontend/src/components/Coder/CoderSidebar.test.tsx`（新建）：

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CoderSidebar } from './CoderSidebar'
import type { Conversation } from '../../types/chat'

const conv = (id: string, workspace: string | null, updatedAt: string, name?: string): Conversation => ({
  id,
  name: name ?? null,
  workspace,
  mode: 'coder',
  created_at: updatedAt,
  updated_at: updatedAt,
})

describe('CoderSidebar', () => {
  const base = {
    onSelect: vi.fn(),
    onNew: vi.fn(),
    onDelete: vi.fn(),
    selectedId: undefined,
  }

  it('groups conversations by workspace', () => {
    render(<CoderSidebar {...base} conversations={[
      conv('c1', 'C:\\proj\\alpha', '2026-08-22T10:00:00Z', 'fix bug'),
      conv('c2', 'C:\\proj\\alpha', '2026-08-22T09:00:00Z', 'add tests'),
      conv('c3', 'D:\\other', '2026-08-22T08:00:00Z', 'docs'),
    ]} />)
    expect(screen.getAllByTestId('coder-group')).toHaveLength(2)
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('other')).toBeInTheDocument()
    expect(screen.getAllByTestId('coder-conversation-item')).toHaveLength(3)
  })

  it('collapses a group when its header is clicked', () => {
    render(<CoderSidebar {...base} conversations={[conv('c1', 'ws-a', '2026-08-22T10:00:00Z')]} />)
    expect(screen.getAllByTestId('coder-conversation-item')).toHaveLength(1)
    fireEvent.click(screen.getByTestId('coder-group-toggle'))
    expect(screen.queryAllByTestId('coder-conversation-item')).toHaveLength(0)
  })

  it('shows empty state when there are no conversations', () => {
    render(<CoderSidebar {...base} conversations={[]} />)
    expect(screen.getByTestId('coder-sidebar-empty')).toBeInTheDocument()
  })

  it('calls onNew and onDelete', () => {
    const onNew = vi.fn()
    const onDelete = vi.fn()
    render(<CoderSidebar {...base} onNew={onNew} onDelete={onDelete} conversations={[conv('c1', 'ws-a', '2026-08-22T10:00:00Z')]} />)
    fireEvent.click(screen.getByTitle('New coder conversation'))
    expect(onNew).toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('delete-conversation'))
    expect(onDelete).toHaveBeenCalledWith('c1')
  })
})
```

`frontend/src/components/Coder/WorkspacePicker.test.tsx`（新建）：

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { WorkspacePicker } from './WorkspacePicker'

describe('WorkspacePicker', () => {
  const onClose = vi.fn()
  const onCreated = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    onClose.mockClear()
    onCreated.mockClear()
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: 'new-coder-id', mode: 'coder', workspace: 'C:\\ws' }),
    })) as unknown as typeof fetch
  })

  it('creates a coder conversation with the workspace path', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\ws' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('new-coder-id'))
    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toBe('/api/v1/conversations')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ mode: 'coder', workspace: 'C:\\ws' })
  })

  it('requires a path before submitting', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    expect(await screen.findByTestId('workspace-picker-error')).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('shows the server error message when creation fails', async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      json: async () => ({ detail: '工作区不是有效目录: C:\\nope' }),
    })) as unknown as typeof fetch
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\nope' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    expect(await screen.findByTestId('workspace-picker-error')).toHaveTextContent('工作区不是有效目录')
  })

  it('closes on cancel', () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.click(screen.getByText('Cancel'))
    expect(onClose).toHaveBeenCalled()
  })
})
```

（若测试环境 locale 为 zh-CN，「Cancel」按钮文案需用 `screen.getByText(/cancel|cancel/i)` 或改用 `getByRole('button')` 按顺序；如报文案不匹配，改用 `screen.getAllByRole('button')` 最后一个或为取消按钮补 `data-testid="workspace-cancel"` 并相应改测试。）

`frontend/src/App.pageSwitch.test.tsx` 追加：

```tsx
  it('switches to the coder page and shows the coder sidebar', async () => {
    render(<App />)
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    fireEvent.click(screen.getByTestId('nav-coder'))
    expect(await screen.findByTestId('coder-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('coder-sidebar-empty')).toBeInTheDocument()
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/components/Coder src/App.pageSwitch.test.tsx`
Expected: FAIL（模块不存在 → 无法渲染）

- [ ] **Step 3: 实现 CoderSidebar**

`frontend/src/components/Coder/CoderSidebar.tsx`:

```tsx
import { useMemo, useState } from 'react'
import type { Conversation } from '../../types/chat'
import { ChevronDown, ChevronRight, FileText, FolderOpen, Pencil, Plus, X, Check } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface CoderSidebarProps {
  conversations: Conversation[]
  onSelect: (id: string) => void
  onNew?: () => void
  onDelete?: (id: string) => void
  onRename?: (id: string, name: string) => void
  selectedId?: string
}

export function CoderSidebar({ conversations, onSelect, onNew, onDelete, onRename, selectedId }: CoderSidebarProps) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const groups = useMemo(() => {
    const map = new Map<string, Conversation[]>()
    for (const conv of conversations) {
      const ws = conv.workspace || t('coder.unknownWorkspace')
      const list = map.get(ws) ?? []
      list.push(conv)
      map.set(ws, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
    }
    return new Map([...map.entries()].sort((a, b) =>
      (b[1][0]?.updated_at ?? '').localeCompare(a[1][0]?.updated_at ?? ''),
    ))
  }, [conversations, t])

  const toggleGroup = (ws: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(ws)) next.delete(ws)
      else next.add(ws)
      return next
    })
  }

  const workspaceName = (ws: string) => ws.split(/[\\/]/).filter(Boolean).pop() || ws

  const startEdit = (conv: Conversation) => {
    if (!onRename) return
    setEditingId(conv.id)
    setDraft(conv.name || '')
  }

  const commitEdit = () => {
    if (editingId && onRename) {
      const trimmed = draft.trim()
      if (trimmed) onRename(editingId, trimmed)
    }
    setEditingId(null)
    setDraft('')
  }

  return (
    <aside className="sidebar coder-sidebar" data-testid="coder-sidebar">
      <div className="sidebar-header">
        <span>{t('coder.sidebarTitle')}</span>
        {onNew && (
          <button onClick={onNew} title={t('coder.newConversation')} aria-label={t('coder.newConversation')}>
            <Plus size={16} />
          </button>
        )}
      </div>
      <div className="sidebar-list">
        {groups.size === 0 ? (
          <div className="sidebar-empty" data-testid="coder-sidebar-empty">
            {t('coder.emptyHint')}
          </div>
        ) : (
          [...groups.entries()].map(([ws, list]) => (
            <div key={ws} className="coder-group" data-testid="coder-group">
              <button className="coder-group__header" data-testid="coder-group-toggle" onClick={() => toggleGroup(ws)} title={ws}>
                {collapsed.has(ws) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                <FolderOpen size={14} />
                <span className="coder-group__name">{workspaceName(ws)}</span>
                <span className="coder-group__count">{list.length}</span>
              </button>
              {!collapsed.has(ws) && (
                <div className="coder-group__items">
                  {list.map(conv => (
                    <div
                      key={conv.id}
                      data-testid="coder-conversation-item"
                      className={`sidebar-item${selectedId === conv.id ? ' active' : ''}`}
                      onClick={() => editingId !== conv.id && onSelect(conv.id)}
                    >
                      {editingId === conv.id ? (
                        <div className="sidebar-item__edit" onClick={e => e.stopPropagation()}>
                          <input
                            data-testid="rename-input"
                            className="sidebar-item__input"
                            value={draft}
                            onChange={e => setDraft(e.target.value)}
                            onBlur={commitEdit}
                            onKeyDown={e => {
                              if (e.key === 'Enter') commitEdit()
                              else if (e.key === 'Escape') { setEditingId(null); setDraft('') }
                            }}
                            maxLength={100}
                            aria-label={t('chat.renameConversation')}
                          />
                          <button className="btn btn-ghost btn-sm sidebar-item__confirm" data-testid="rename-confirm"
                            title={t('chat.saveName')} aria-label={t('chat.saveName')}
                            onMouseDown={e => e.preventDefault()}
                            onClick={e => { e.stopPropagation(); commitEdit() }}>
                            <Check size={14} />
                          </button>
                        </div>
                      ) : (
                        <>
                          <FileText size={13} className="coder-item-icon" />
                          <span className="item-title__text">{conv.name || conv.summary || conv.id.slice(0, 8)}</span>
                          {onRename && (
                            <button className="btn btn-ghost btn-sm sidebar-action" data-testid="rename-conversation"
                              title={t('chat.renameConversation')} aria-label={t('chat.renameConversation')}
                              onClick={e => { e.stopPropagation(); startEdit(conv) }}>
                              <Pencil size={13} />
                            </button>
                          )}
                          {onDelete && (
                            <button className="btn btn-ghost btn-sm sidebar-delete" data-testid="delete-conversation"
                              title={t('chat.deleteConversation')} aria-label={t('chat.deleteConversation')}
                              onClick={e => { e.stopPropagation(); onDelete(conv.id) }}>
                              <X size={14} />
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
```

- [ ] **Step 4: 实现 WorkspacePicker**

`frontend/src/components/Coder/WorkspacePicker.tsx`:

```tsx
import { useState } from 'react'
import { useTranslation } from '../../i18n'
import { createConversation } from '../../api/conversations'

interface DirectoryHandle { name: string }

interface WorkspacePickerProps {
  onClose: () => void
  onCreated: (id: string) => void
}

export function WorkspacePicker({ onClose, onCreated }: WorkspacePickerProps) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [dirName, setDirName] = useState<string | null>(null)

  const pickDirectory = async () => {
    try {
      const picker = (window as unknown as {
        showDirectoryPicker?: () => Promise<DirectoryHandle>
      }).showDirectoryPicker
      const handle = picker ? await picker.call(window) : null
      if (handle) {
        setDirName(handle.name)
        setError(null)
      }
    } catch {
      // user cancelled or the API is unavailable — ignore
    }
  }

  const submit = async () => {
    const trimmed = path.trim()
    if (!trimmed) {
      setError(t('coder.workspaceRequired'))
      return
    }
    setCreating(true)
    setError(null)
    try {
      const conv = await createConversation({ mode: 'coder', workspace: trimmed })
      onCreated(conv.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('coder.createFailed'))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="modal-overlay" data-testid="workspace-picker" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>{t('coder.pickWorkspaceTitle')}</h3>
        <input
          data-testid="workspace-path-input"
          type="text"
          value={path}
          onChange={e => setPath(e.target.value)}
          placeholder={t('coder.workspacePlaceholder')}
          onKeyDown={e => { if (e.key === 'Enter') submit() }}
        />
        {dirName && (
          <div className="workspace-picker__hint">
            {t('coder.dirPickerHint')}: {dirName}
          </div>
        )}
        <button data-testid="workspace-pick-native" onClick={pickDirectory} type="button">
          {t('coder.pickDirButton')}
        </button>
        {error && (
          <div className="workspace-picker__error" data-testid="workspace-picker-error">{error}</div>
        )}
        <div className="modal-actions">
          <button onClick={onClose}>{t('common.cancel')}</button>
          <button data-testid="workspace-confirm" onClick={submit} disabled={creating}>
            {creating ? t('common.saving') : t('coder.confirmCreate')}
          </button>
        </div>
      </div>
    </div>
  )
}
```

注意：成功后不立即 `onClose()`，由 `CoderPage` 在 `onCreated` 回调里关闭，避免竞态。

- [ ] **Step 5: 实现 CoderPage**

`frontend/src/components/Coder/CoderPage.tsx`:

```tsx
import { useState } from 'react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import type { Conversation, ThinkingEffort } from '../../types/chat'
import { ChatWindow } from '../Chat/ChatWindow'
import { CoderSidebar } from './CoderSidebar'
import { WorkspacePicker } from './WorkspacePicker'

interface CoderPageProps {
  ws: ChatSocket
  conversations: Conversation[]
  selectedId?: string
  onSelect: (id: string) => void
  onCreated: (id: string) => void
  onDelete?: (id: string) => void
  onRename?: (id: string, name: string) => void
  onRefresh: () => void
  onSetEndpoint?: (id: string, endpointId: string | null, model: string | null) => void
  onSetKnowledgeBase?: (id: string, knowledgeBaseId: string | null) => void
  onSetRole?: (id: string, role: string | null) => void
  onSetThinking?: (id: string, enabled: boolean, effort: ThinkingEffort) => void
  onViewTrajectory?: (id: string) => void
}

export function CoderPage({ ws, conversations, selectedId, onSelect, onCreated, onDelete, onRename, onRefresh, onSetEndpoint, onSetKnowledgeBase, onSetRole, onSetThinking, onViewTrajectory }: CoderPageProps) {
  const [pickerOpen, setPickerOpen] = useState(false)

  return (
    <>
      {pickerOpen && (
        <WorkspacePicker
          onClose={() => setPickerOpen(false)}
          onCreated={id => {
            setPickerOpen(false)
            onCreated(id)
          }}
        />
      )}
      <CoderSidebar
        conversations={conversations}
        onSelect={onSelect}
        onNew={() => setPickerOpen(true)}
        onDelete={onDelete}
        onRename={onRename}
        selectedId={selectedId}
      />
      <ChatWindow
        ws={ws}
        conversationId={selectedId}
        conversations={conversations}
        onConversationCreated={onRefresh}
        onDefaultConversation={onSelect}
        onSetEndpoint={onSetEndpoint}
        onSetKnowledgeBase={onSetKnowledgeBase}
        onSetRole={onSetRole}
        onSetThinking={onSetThinking}
        onViewTrajectory={onViewTrajectory}
      />
    </>
  )
}
```

注：`onCreated(id: string)` 由 WorkspacePicker 创建成功后回调新会话 id；`CoderPage` 内部把成功回调包装为「关闭弹窗 + 交由 App 选中并回拉列表」。

- [ ] **Step 6: App 集成**

`frontend/src/App.tsx`：

1. imports：`import { CoderPage } from './components/Coder/CoderPage'`；`import { createConversation, fetchConversations } from './api/conversations'`（删除原来的 `renameConversation, setConversationEndpoint, ...` 行的重复项——`renameConversation` 等仍在 `./api/conversations` 中）。
2. 状态：

```tsx
  const [coderConversations, setCoderConversations] = useState<Conversation[]>([])
```

3. `fetchConversations` 回调改为带 mode（聊天页）：

```tsx
  const fetchConversations = useCallback(() => {
    const fetchId = ++latestFetchRef.current
    fetchConversationsApi('chat')
      .then(data => {
        if (fetchId === latestFetchRef.current) {
          setConversations(Array.isArray(data) ? data : [])
        }
      })
      .catch(() => {
        if (fetchId === latestFetchRef.current) {
          setConversations([])
        }
      })
  }, [])
```

（将 API 助手改名为 `fetchConversationsApi` 以消除与本地回调同名冲突；或把本地回调改名 `refreshChatConversations`——二选一，改本地回调名更简单，全文替换引用。）

4. 码农列表回拉：

```tsx
  const fetchCoderConversations = useCallback(() => {
    fetchConversations('coder')
      .then(data => setCoderConversations(Array.isArray(data) ? data : []))
      .catch(() => setCoderConversations([]))
  }, [])

  useEffect(() => {
    fetchCoderConversations()
  }, [fetchCoderConversations])
```

5. `handleNewConversation` 改用 `createConversation({})`；新增：

```tsx
  const handleCoderConversationCreated = useCallback((id: string) => {
    setSelectedId(id)
    fetchCoderConversations()
  }, [fetchCoderConversations])
```

6. `updateConversationInState` 同时更新两个列表；`handleDelete` 同时从两个列表移除，且若删除的是码农会话则选中清空逻辑不变：

```tsx
  const updateConversationInState = useCallback((conv: Conversation) => {
    const apply = (list: Conversation[]) => (Array.isArray(list) ? list : []).map(c => (c.id === conv.id ? { ...c, ...conv } : c))
    setConversations(prev => apply(prev))
    setCoderConversations(prev => apply(prev))
  }, [])

  const handleDelete = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/v1/conversations/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        setCoderConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        if (selectedId === id) setSelectedId(undefined)
      }
    } catch { /* ignore */ }
  }, [selectedId])
```

7. `renderPage` 增加：

```tsx
      case 'coder':
        return (
          <CoderPage
            ws={chatSocket}
            conversations={coderConversations}
            selectedId={selectedId}
            onSelect={handleSelect}
            onCreated={handleCoderConversationCreated}
            onDelete={handleDelete}
            onRename={handleRename}
            onRefresh={fetchCoderConversations}
            onSetEndpoint={handleSetEndpoint}
            onSetKnowledgeBase={handleSetKnowledgeBase}
            onSetRole={handleSetRole}
            onSetThinking={handleSetThinking}
            onViewTrajectory={handleViewTrajectory}
          />
        )
```

8. `case 'chat'` 的 `Sidebar` 部分不变（`conversations` 已是过滤后的聊天会话）；WebSocket 切换会话逻辑不变。

`frontend/src/App.css` 追加（最小样式，测试不依赖）：

```css
.coder-group__header {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 10px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  color: inherit;
}
.coder-group__name { flex: 1; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.coder-group__count { color: var(--muted-text, #888); font-size: 11px; }
.coder-group__items { padding-left: 8px; }
.coder-item-icon { flex-shrink: 0; opacity: 0.6; }
.workspace-picker__error { color: var(--danger, #d33); font-size: 12px; margin-top: 6px; }
.workspace-picker__hint { font-size: 12px; opacity: 0.7; margin-top: 4px; }
```

i18n 新增（两个文件同结构）：

`zh-CN.json`：

```json
  "coder": {
    "sidebarTitle": "码农会话",
    "newConversation": "新建码农会话",
    "emptyHint": "选择一个工作区，开始第一个码农会话。",
    "unknownWorkspace": "未知工作区",
    "pickWorkspaceTitle": "选择工作区",
    "workspacePlaceholder": "输入服务器上的目录绝对路径",
    "workspaceRequired": "请输入工作区路径",
    "createFailed": "创建会话失败",
    "pickDirButton": "选择目录…",
    "dirPickerHint": "已确认目录（名称）",
    "confirmCreate": "创建"
  }
```

`en.json`：

```json
  "coder": {
    "sidebarTitle": "Coder Sessions",
    "newConversation": "New coder conversation",
    "emptyHint": "Pick a workspace to start your first coder conversation.",
    "unknownWorkspace": "Unknown workspace",
    "pickWorkspaceTitle": "Choose workspace",
    "workspacePlaceholder": "Absolute path to a directory on the server",
    "workspaceRequired": "Workspace path is required",
    "createFailed": "Failed to create conversation",
    "pickDirButton": "Choose directory…",
    "dirPickerHint": "Directory confirmed (name)",
    "confirmCreate": "Create"
  }
```

- [ ] **Step 7: 运行测试并修复存量**

Run: `cd frontend && npx vitest run src/components/Coder src/App.pageSwitch.test.tsx src/components/Layout/Header.test.tsx`
Expected: PASS

然后跑全量前端测试：

Run: `cd frontend && npm test`
Expected: PASS（若有存量用例因 `fetch('/api/v1/conversations')` 的 URL 断言失败——现在聊天页带 `?mode=chat`——把断言 URL 更新为 `'/api/v1/conversations?mode=chat'` 或断言 `String(url).startsWith('/api/v1/conversations')`）

再跑后端全量：

Run: `python -m pytest -q`
Expected: PASS

Run: `ruff check src tests`
Expected: 无错误

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/Coder frontend/src/App.tsx frontend/src/App.css frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json frontend/src/App.pageSwitch.test.tsx
git commit -m "feat: 码农页面：按工作区分组侧栏、工作区选择弹窗与 App 集成"
```

---

## Self-Review

- **Spec 覆盖**：数据模型（Task 1）✓；API 创建校验与 mode 过滤（Task 2）✓；工具边界与 search_files（Task 3）✓；提示词注入 + 角色默认与 coder.md 微调（Task 2 role='coder' + Task 4）✓；前端导航/分组弹窗/复用 ChatWindow（Task 5-6）✓；错误处理（422 文案、越界返回文本、快照降级）分散在各 Task ✓；测试策略全量覆盖 ✓。
- **占位符**：无 TBD/TODO；所有代码步骤均给出具体实现。
- **类型一致性**：`build_workspace_context` / `set_workspace` / `get_workspace` / `resolve_workspace_path` / `fetchConversations` / `createConversation` / `CoderPage` props 在各 Task 之间签名一致；`mode` 取值统一 `'chat'|'coder'`。