# Git 状态栏实施计划

> **For implementer:** Use TDD throughout. Write failing test first. Watch it fail. Then implement.

**Goal:** 在码农状态栏新增 git 栏目,展示当前分支、可点击弹出分支列表并切换,切换后经 WebSocket 广播实时刷新(无轮询)。

**Architecture:** 后端在 `api/routes/fs.py` 加 3 个只读/短写 git 端点(执行 `git` 子进程);前端新建自包含 `GitBranchSelector`(复刻 RoleSelector 交互),初始挂载探测一次 + checkout 后更新;`useWebSocket` 加 `subscribe` 订阅后端广播的 `{ git_branch }` 事件。不做后台监听/轮询。

**Tech Stack:** FastAPI + subprocess,React 19 + TypeScript,Vitest + React Testing Library,pytest。

**设计文档:** `docs/plans/2026-08-30-git-statusbar-design.md`(已批准)

---

## Task 1: 后端 — git 子进程助手 + `GET /fs/git`

**Files:**
- Modify: `src/thumbelina/api/routes/fs.py`
- Test: `tests/test_api/test_fs.py`

**Step 1: 写失败测试**(追加到 `tests/test_api/test_fs.py`)

```python
import shutil
import subprocess
import pathlib

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _init_repo(tmp_path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=repo, check=True,
    )
    return repo


def test_git_info_in_repo(client, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    resp = client.get("/api/v1/fs/git", params={"path": str(repo)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_git"] is True
    assert isinstance(data["branch"], str) and data["branch"]


def test_git_info_non_repo(client, tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    resp = client.get("/api/v1/fs/git", params={"path": str(plain)})
    assert resp.status_code == 200
    assert resp.json() == {"is_git": False, "branch": None}


def test_git_info_invalid_path(client, tmp_path) -> None:
    resp = client.get("/api/v1/fs/git", params={"path": str(tmp_path / "missing")})
    assert resp.status_code == 422


def test_git_info_relative_path_rejected(client, tmp_path) -> None:
    resp = client.get("/api/v1/fs/git", params={"path": "some/relative"})
    assert resp.status_code == 422
```

**Step 2: 运行确认失败**
```
pytest tests/test_api/test_fs.py -k git -v
```
Expected: FAIL(422 或 404)。

**Step 3: 最小实现**(在 `src/thumbelina/api/routes/fs.py` 顶部 import 后追加)

```python
import shutil
import subprocess

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
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return 1, "", "git timeout"
    return (
        proc.returncode,
        (proc.stdout or "").strip(),
        (proc.stderr or "").strip(),
    )


@router.get("/fs/git", response_model=GitInfo)
def git_info(path: str = Query(...)) -> GitInfo:
    """返回工作区 git 状态;非 git 目录返回 is_git=False。"""
    resolved = _resolve_dir(path)
    code, branch, _ = _run_git(str(resolved), ["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0 or not branch:
        return GitInfo(is_git=False, branch=None)
    return GitInfo(is_git=True, branch=branch)
```

**Step 4: 运行确认通过**
```
pytest tests/test_api/test_fs.py -k git -v
```
Expected: 4 passed。

**Step 5: Commit**
```
git add src/thumbelina/api/routes/fs.py tests/test_api/test_fs.py
git commit -m "feat(fs): git 状态探测端点 GET /fs/git"
```

---

## Task 2: 后端 — `GET /fs/git/branches`

**Files:**
- Modify: `src/thumbelina/api/routes/fs.py`
- Test: `tests/test_api/test_fs.py`

**Step 1: 失败测试**

```python
def test_git_branches(client, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature-a"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-q", "feature-b"], cwd=repo, check=True)
    resp = client.get("/api/v1/fs/git/branches", params={"path": str(repo)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_git"] is True
    assert data["current"] == "main"
    assert data["branches"] == ["feature-a", "feature-b", "main"]


def test_git_branches_non_repo(client, tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    resp = client.get("/api/v1/fs/git/branches", params={"path": str(plain)})
    assert resp.status_code == 200
    assert resp.json() == {"is_git": False, "current": None, "branches": []}
```

**Step 2: 运行失败**
```
pytest tests/test_api/test_fs.py -k branches -v
```

**Step 3: 实现**

```python
class GitBranches(BaseModel):
    is_git: bool
    current: str | None = None
    branches: list[str] = []


@router.get("/fs/git/branches", response_model=GitBranches)
def git_branches(path: str = Query(...)) -> GitBranches:
    """列出所有本地分支及当前分支。"""
    resolved = _resolve_dir(path)
    code, cur, _ = _run_git(str(resolved), ["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return GitBranches(is_git=False)
    code2, out, _ = _run_git(
        str(resolved), ["for-each-ref", "refs/heads", "--format=%(refname:short)"]
    )
    if code2 != 0:
        return GitBranches(is_git=False)
    branches = sorted(out.splitlines()) if out else []
    return GitBranches(is_git=True, current=cur, branches=branches)
```

**Step 4: 运行通过**
```
pytest tests/test_api/test_fs.py -k branches -v
```

**Step 5: Commit**
```
git commit -am "feat(fs): 分支列表端点 GET /fs/git/branches"
```

---

## Task 3: 后端 — `POST /fs/git/checkout` + 广播

**Files:**
- Modify: `src/thumbelina/api/routes/fs.py`
- Test: `tests/test_api/test_fs.py`

**Step 1: 失败测试**

```python
def test_checkout_success(client, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    resp = client.post(
        "/api/v1/fs/git/checkout",
        json={"path": str(repo), "branch": "feature-a"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_git"] is True
    assert data["branch"] == "feature-a"
    # 切换确实生效:重新探测当前分支
    probe = client.get("/api/v1/fs/git", params={"path": str(repo)}).json()
    assert probe["branch"] == "feature-a"


def test_checkout_unknown_branch(client, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    resp = client.post(
        "/api/v1/fs/git/checkout",
        json={"path": str(repo), "branch": "nope"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]
```

**Step 2: 运行失败**
```
pytest tests/test_api/test_fs.py -k checkout -v
```

**Step 3: 实现**(`post("/fs/git/checkout", ...)` 需 `async def`;`/fs/git`、`/fs/git/branches` 保持 sync `def`)

```python
class GitCheckoutRequest(BaseModel):
    path: str
    branch: str


@router.post("/fs/git/checkout", response_model=GitInfo)
async def git_checkout(body: GitCheckoutRequest) -> GitInfo:
    """切换到指定本地分支;服务端重新校验分支存在,不传 --force。"""
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
    # 广播到所有已连接的 /ws/chat 客户端(回调刷新)
    from thumbelina.api.websocket import broadcast_chat_message
    await broadcast_chat_message(
        {"git_branch": {"workspace": str(resolved), "branch": body.branch}}
    )
    return GitInfo(is_git=True, branch=body.branch)
```

`fs.py` 顶部需加 `import asyncio`。

**Step 4: 运行通过**
```
pytest tests/test_api/test_fs.py -k checkout -v
```

**Step 5: 广播断言测试(可选强化)**

```python
def test_checkout_broadcasts(client, tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock
    broadcast = AsyncMock()
    monkeypatch.setattr(
        "thumbelina.api.routes.fs.broadcast_chat_message", broadcast
    )
    repo = _init_repo(tmp_path)
    resp = client.post(
        "/api/v1/fs/git/checkout",
        json={"path": str(repo), "branch": "feature-a"},
    )
    assert resp.status_code == 200
    broadcast.assert_awaited_once()
    kwargs = broadcast.await_args.args[0]
    assert kwargs["git_branch"]["branch"] == "feature-a"
```

**Step 6: Commit**
```
git add src/thumbelina/api/routes/fs.py tests/test_api/test_fs.py
git commit -m "feat(fs): git 分支切换端点 POST /fs/git/checkout + WebSocket 广播"
```

---

## Task 4: 前端 — `useWebSocket` 事件订阅

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`

**Step 1: 写失败测试**(新建 `frontend/src/hooks/useWebSocket.test.tsx`;若已有,追加)

```ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from './useWebSocket'

describe('useWebSocket.git_branch 订阅', () => {
  it('subscribe 收到 git_branch 消息并可取消', async () => {
    const wsMock = {
      ...new WebSocket('ws://localhost/x'),
      send: vi.fn(),
      close: vi.fn(),
      readyState: WebSocket.OPEN,
    }
    vi.stubGlobal('WebSocket', class {
      static OPEN = 1
      readyState = 1
      send = wsMock.send
      close = wsMock.close
      constructor() {
        setTimeout(() => this.onopen?.(), 0)
      }
    })
    const { result } = renderHook(() => useWebSocket('ws://localhost/x'))
    const seen: unknown[] = []
    const unsub = result.current.subscribe((msg: any) => { seen.push(msg.git_branch) })
    await act(async () => { await new Promise(r => setTimeout(r, 0)) })
    // 模拟后端推送
    const onmessage = (wsMock as any).onmessage
    await act(async () => {
      onmessage({ data: JSON.stringify({ git_branch: { workspace: '/ws', branch: 'main' } }) })
      await new Promise(r => setTimeout(r, 0))
    })
    expect(seen).toHaveLength(1)
    unsub()
  })
})
```

**Step 2/3: 实现**

在 `WsIncoming` 加字段,加订阅,并在 `onmessage` 派发,返回 `subscribe`:

```ts
interface WsIncoming {
  // ... 现有字段 ...
  git_branch?: { workspace: string; branch: string }
}
type WsListener = (msg: WsIncoming) => void
```

hook 内(靠近其它 ref):

```ts
const listenersRef = useRef<Set<WsListener>>(new Set())
const subscribe = useCallback((fn: WsListener) => {
  listenersRef.current.add(fn)
  return () => { listenersRef.current.delete(fn) }
}, [])
```

`onmessage` 内,在 `data = JSON.parse(...)` 之后、`if (data.error)` 之前插入:

```ts
if (data.git_branch) {
  for (const fn of listenersRef.current) {
    try { fn(data) } catch { /* 监听者异常不影响主流程 */ }
  }
}
```

返回对象末尾加 `subscribe`。

**Step 4: 运行通过**
```
cd frontend && npx vitest run src/hooks/useWebSocket.test.tsx
```

**Step 5: Commit**
```
git add frontend/src/hooks/useWebSocket.ts frontend/src/hooks/useWebSocket.test.tsx
git commit -m "feat(ws): useWebSocket 支持 git_branch 事件订阅"
```

---

## Task 5: 前端 — `StatusBarItemView` 支持 onClick(渲染为 button)

**Files:**
- Modify: `frontend/src/components/StatusBar/StatusBarItem.tsx`
- Modify: `frontend/src/components/StatusBar/StatusBarItem.test.tsx`(如无则新建)

**Step 1: 失败测试**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { StatusBarItemView } from './StatusBarItem'

describe('StatusBarItemView onClick', () => {
  it('提供 onClick 时渲染 button 并触发', () => {
    const onClick = vi.fn()
    render(<StatusBarItemView label="main" state="ok" onClick={onClick} />)
    const el = screen.getByTestId('statusbar-item') as HTMLButtonElement
    expect(el.tagName).toBe('BUTTON')
    fireEvent.click(el)
    expect(onClick).toHaveBeenCalledOnce()
  })
})
```

**Step 2: 实现** — `StatusBarItemViewProps` 加 `onClick?: () => void`,渲染 `<button type="button">`(保留同一批 class 与 data-testid)。

**Step 3: 运行通过 + Commit**
```
cd frontend && npx vitest run src/components/StatusBar/StatusBarItem.test.tsx
git add frontend/src/components/StatusBar/StatusBarItem.tsx
git commit -m "feat(statusbar): StatusBarItemView 支持 onClick 渲染为按钮"
```

---

## Task 6: 前端 — `useStatusBarConfig` 加 `git`

**Files:**
- Modify: `frontend/src/components/StatusBar/useStatusBarConfig.ts`
- Modify: `frontend/src/components/StatusBar/useStatusBarConfig.test.ts`

**Step 1: 失败测试**(在 `useStatusBarConfig.test.ts` 追加)

```ts
describe('useStatusBarConfig git 栏目', () => {
  beforeEach(() => { localStorage.clear() })

  it('默认展示 git 栏目', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.git).toBe(true)
  })

  it('旧配置(无 git 键)回落默认开启', () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: false }))
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.git).toBe(true)
  })

  it('toggle 切换并持久化', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    act(() => result.current.toggle('git'))
    expect(result.current.config.git).toBe(false)
    const saved = JSON.parse(localStorage.getItem('thumbelina-statusbar-items') ?? '{}')
    expect(saved.git).toBe(false)
  })
})
```

**Step 2: 实现** — `StatusBarConfig` 接口加 `git: boolean`;`DEFAULTS` 加 `git: true`;`load()` 加 `git: typeof parsed.git === 'boolean' ? parsed.git : DEFAULTS.git`。

**Step 3: 修复其它测试里的字面量配置**(`git grep 'config={{' frontend/src --include='*.test.tsx'` 找字面量,把 `{ context: false, cacheHit: true }` 之类补上 `git: true`;`StatusBarCardGrid.test.tsx` 有 4 处)。

**Step 4: 运行通过 + Commit**
```
cd frontend && npx vitest run src/components/StatusBar/useStatusBarConfig.test.ts src/components/StatusBar/StatusBarCardGrid.test.tsx
git add frontend/src/components/StatusBar/useStatusBarConfig.ts
git commit -m "feat(statusbar): 配置新增 git 栏目开关"
```

---

## Task 7: 前端 — API 客户端 + i18n 键

**Files:**
- Modify: `frontend/src/api/fs.ts`
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/i18n/locales/zh-CN.json`

**Step 1: 实现 `frontend/src/api/fs.ts` 追加**

```ts
export interface GitInfo {
  is_git: boolean
  branch: string | null
}

export interface GitBranches {
  is_git: boolean
  current: string | null
  branches: string[]
}

const api = <T = unknown>(url: string, init?: RequestInit): Promise<T> =>
  fetch(url, init).then(res => {
    if (!res.ok) {
      return res.json().then(d => { throw new Error((d as { detail?: string }).detail || `HTTP ${res.status}`) })
    }
    return res.json() as Promise<T>
  })

export function fetchGitInfo(path: string): Promise<GitInfo> {
  return api(`/api/v1/fs/git?path=${encodeURIComponent(path)}`)
}

export function fetchGitBranches(path: string): Promise<GitBranches> {
  return api(`/api/v1/fs/git/branches?path=${encodeURIComponent(path)}`)
}

export function checkoutBranch(path: string, branch: string): Promise<GitInfo> {
  return api('/api/v1/fs/git/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, branch }),
  })
}
```

**Step 2: i18n 键**

`en.json` 的 `settings.statusbarColumns` 内加:
```json
"git": "Git branch",
"gitDesc": "Show current branch in the coder workspace; click to switch"
```
顶层新增 `"git"` 块:
```json
"git": {
  "chooseBranch": "Switch branch",
  "loadFailed": "Failed to load branches",
  "switchFailed": "Failed to switch branch",
  "noBranches": "No local branches"
}
```
`statusbar` 块加:`"gitTitle": "Current branch {branch}"`。

`zh-CN.json` 对应:
```json
"git": "Git 分支",
"gitDesc": "在码农工作区显示当前分支,点击可切换"
"git": {
  "chooseBranch": "切换分支",
  "loadFailed": "加载分支列表失败",
  "switchFailed": "切换分支失败",
  "noBranches": "没有可切换的本地分支"
}
"gitTitle": "当前分支 {branch}"
```

**Step 3: 校验 JSON + Commit**
```
python -c "import json; [json.load(open(f,encoding='utf-8')) for f in ['frontend/src/i18n/locales/en.json','frontend/src/i18n/locales/zh-CN.json']]"
git add frontend/src/api/fs.ts frontend/src/i18n/locales/en.json frontend/src/i18n/locales/zh-CN.json
git commit -m "feat(fs): git API 客户端 + i18n 键"
```

---

## Task 8: 前端 — `GitBranchSelector` + ChatWindow + SettingsPanel

**Files:**
- Create: `frontend/src/components/StatusBar/GitBranchSelector.tsx`
- Create: `frontend/src/components/StatusBar/GitBranchSelector.test.tsx`
- Modify: `frontend/src/components/Chat/ChatWindow.tsx`
- Modify: `frontend/src/components/Settings/SettingsPanel.tsx`

**Step 1: 失败测试**(mock `api/fs` 与 `ws`)

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LocaleProvider } from '../../i18n'
import { GitBranchSelector } from './GitBranchSelector'
import * as fsApi from '../../api/fs'

const ws = {
  subscribe: vi.fn(() => () => {}),
} as any

function localGit(on: boolean) {
  localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ git: on }))
}

function mock(info: Partial<fsApi.GitInfo>) {
  vi.spyOn(fsApi, 'fetchGitInfo').mockResolvedValue({ is_git: true, branch: 'main', ...info })
}

describe('GitBranchSelector', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
    localGit(true)
  })

  it('配置关闭时不渲染', () => {
    localGit(false)
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    expect(screen.queryByTestId('git-branch-selector')).not.toBeInTheDocument()
  })

  it('无 workspace(非码农)时不渲染', () => {
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace={null} /></LocaleProvider>)
    expect(screen.queryByTestId('git-branch-selector')).not.toBeInTheDocument()
  })

  it('非 git 目录隐藏', async () => {
    mock({ is_git: false, branch: null })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    await waitFor(() => expect(screen.queryByTestId('git-branch-selector')).not.toBeInTheDocument())
  })

  it('git 目录显示当前分支', async () => {
    mock({ is_git: true, branch: 'main' })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    expect(await screen.findByText('main')).toBeInTheDocument()
    expect(screen.getByTestId('statusbar-item')).toHaveAttribute('title', '当前分支 main')
  })

  it('点击打开面板并列出分支', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['feature-a', 'main'],
    })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    const trigger = await screen.findByTestId('statusbar-item')
    fireEvent.click(trigger)
    expect(await screen.findByTestId('git-branch-menu')).toBeInTheDocument()
    expect(screen.getByTestId('git-branch-option-feature-a')).toBeInTheDocument()
  })

  it('点击分支调用 checkout 并刷新', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['feature-a', 'main'],
    })
    const checkout = vi.spyOn(fsApi, 'checkoutBranch').mockResolvedValue({ is_git: true, branch: 'feature-a' })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    fireEvent.click(await screen.findByTestId('statusbar-item'))
    fireEvent.click(await screen.findByTestId('git-branch-option-feature-a'))
    await waitFor(() => {
      expect(checkout).toHaveBeenCalledWith('/ws', 'feature-a')
      expect(screen.queryByTestId('git-branch-menu')).not.toBeInTheDocument()
    })
    expect(await screen.findByText('feature-a')).toBeInTheDocument()
  })

  it('checkout 失败显示错误并保持面板', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['feature-a', 'main'],
    })
    vi.spyOn(fsApi, 'checkoutBranch').mockRejectedValue(new Error('本地改动会丢失'))
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    fireEvent.click(await screen.findByTestId('statusbar-item'))
    fireEvent.click(await screen.findByTestId('git-branch-option-feature-a'))
    expect(await screen.findByTestId('git-branch-error')).toBeInTheDocument()
    expect(screen.getByTestId('git-branch-menu')).toBeInTheDocument()
  })

  it('Esc 关闭面板', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['main'],
    })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    fireEvent.click(await screen.findByTestId('statusbar-item'))
    await screen.findByTestId('git-branch-menu')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('git-branch-menu')).not.toBeInTheDocument()
  })

  it('收到 git_branch 事件刷新分支', async () => {
    let listener: (msg: any) => void = () => {}
    const subscribe = vi.fn(cb => { listener = cb; return () => {} })
    const ws2 = { subscribe } as any
    mock({ is_git: true, branch: 'main' })
    render(<LocaleProvider><GitBranchSelector ws={ws2} workspace="/ws" /></LocaleProvider>)
    await screen.findByText('main')
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    const cb = subscribe.mock.calls[0][0]
    cb({ git_branch: { workspace: '/ws', branch: 'feature-2' } })
    expect(await screen.findByText('feature-2')).toBeInTheDocument()
  })
})
```

**Step 2: 实现 `GitBranchSelector.tsx`**

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GitBranch, Check, ChevronUp } from 'lucide-react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import { fetchGitInfo, fetchGitBranches, checkoutBranch } from '../../api/fs'
import { useTranslation } from '../../i18n'
import { useStatusBarConfig } from './useStatusBarConfig'
import { StatusBarItemView } from './StatusBarItem'

interface GitBranchSelectorProps {
  ws: ChatSocket
  workspace: string | null
}

export function GitBranchSelector({ ws, workspace }: GitBranchSelectorProps) {
  const { config } = useStatusBarConfig()
  if (!config.git) return null
  if (!workspace) return null
  return <GitBranchSelectorInner ws={ws} workspace={workspace} />
}

function GitBranchSelectorInner({ ws, workspace }: { ws: ChatSocket; workspace: string }) {
  const { t } = useTranslation()
  const [branch, setBranch] = useState<string | null>(null)
  const [probeDone, setProbeDone] = useState(false)
  const [open, setOpen] = useState(false)
  const [branches, setBranches] = useState<string[]>([])
  const [loadingBranches, setLoadingBranches] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    fetchGitInfo(workspace)
      .then(d => {
        if (cancelled) return
        setBranch(d.is_git ? d.branch : null)
        setProbeDone(true)
      })
      .catch(() => {
        if (!cancelled) { setBranch(null); setProbeDone(true) }
      })
    return () => { cancelled = true }
  }, [workspace])

  useEffect(() => {
    const unsub = ws.subscribe(msg => {
      const gb = msg.git_branch
      if (gb && gb.workspace === workspace) setBranch(gb.branch)
    })
    return unsub
  }, [ws, workspace])

  const openPanel = useCallback(() => {
    setOpen(true)
    setLoadingBranches(true)
    setError(null)
    fetchGitBranches(workspace)
      .then(d => setBranches(d.branches))
      .catch(() => setError(t('git.loadFailed')))
      .finally(() => setLoadingBranches(false))
  }, [workspace, t])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  // 探测完成前不渲染,避免闪错;探测到非 git 则隐藏
  if (!probeDone) return null
  if (!branch) return null

  const handleSwitch = async (target: string) => {
    if (switching) return
    setSwitching(true)
    setError(null)
    try {
      const d = await checkoutBranch(workspace, target)
      setBranch(d.branch)
      setOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('git.switchFailed'))
    } finally {
      setSwitching(false)
    }
  }

  return (
    <div className="role-float" ref={wrapRef} data-testid="git-branch-selector">
      <StatusBarItemView
        icon={<GitBranch size={13} aria-hidden="true" />}
        label={branch}
        state="ok"
        title={t('statusbar.gitTitle').replace('{branch}', branch)}
        onClick={() => (open ? setOpen(false) : openPanel())}
      />
      {open && (
        <div className="role-float__panel" role="listbox" data-testid="git-branch-menu">
          <div className="role-float__heading">{t('git.chooseBranch')}</div>
          {loadingBranches && <div className="role-float__empty">{t('common.loading')}</div>}
          {error && (
            <div className="role-float__empty" role="alert" data-testid="git-branch-error">
              {error}
            </div>
          )}
          {!loadingBranches && !error && branches.map(name => {
            const selected = name === branch
            return (
              <button
                key={name}
                type="button"
                role="option"
                aria-selected={selected}
                className={`role-float__option${selected ? ' is-selected' : ''}`}
                data-testid={`git-branch-option-${name}`}
                disabled={switching || selected}
                onClick={() => handleSwitch(name)}
              >
                <span className="role-float__option-body">
                  <span className="role-float__name">{name}</span>
                </span>
                {selected && <Check size={14} className="role-float__check" />}
              </button>
            )
          })}
          {!loadingBranches && !error && branches.length === 0 && (
            <div className="role-float__empty">{t('git.noBranches')}</div>
          )}
        </div>
      )}
    </div>
  )
}
```

**Step 3: 接线 `ChatWindow.tsx`**
- import:`import { GitBranchSelector } from '../StatusBar/GitBranchSelector'`
- 在 `.statusbar-group` 内 `<CacheHitRateItem conversationId={conversationId} />` 之后加:
  `<GitBranchSelector ws={ws} workspace={activeConversation?.workspace ?? null} />`

**Step 4: 接线 `SettingsPanel.tsx`**
- import lucide 加 `GitBranch`;import `GitBranchSelector` 不需要
- `StatusBarCardGrid cards` 数组加:
```tsx
{
  key: 'git',
  label: t('settings.statusbarColumns.git'),
  description: t('settings.statusbarColumns.gitDesc'),
  icon: <GitBranch size={18} />,
},
```

**Step 5: 运行全部前端测试**
```
cd frontend && npx vitest run src/components/StatusBar/GitBranchSelector.test.tsx src/components/StatusBar src/components/Settings/SettingsPanel.test.tsx
cd frontend && npx eslint src/components/StatusBar/GitBranchSelector.tsx src/components/Chat/ChatWindow.tsx src/components/Settings/SettingsPanel.tsx && npx tsc -b
```

**Step 6: Commit**
```
git add frontend/src/components/StatusBar/GitBranchSelector.tsx frontend/src/components/StatusBar/GitBranchSelector.test.tsx frontend/src/components/Chat/ChatWindow.tsx frontend/src/components/Settings/SettingsPanel.tsx
git commit -m "feat(coder): git 状态栏栏目,可点击切换分支(WebSocket 回调刷新)"
```

---

## 收尾

- 跑后端全量:`pytest tests/test_api/test_fs.py tests/test_api/ -q`
- 跑前端全量:`cd frontend && npx vitest run && npx eslint src && npx tsc -b`
- 更新 README(本项目约定:功能修改后同步 README)
- 汇报:每个 Task 状态、测试结果、提交哈希