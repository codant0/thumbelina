# Git 状态栏设计

日期:2026-08-30
状态:已批准(进入实施计划阶段)

## 需求

新增一个 `git` 状态栏栏目,挂在码农(Coder)功能中:

- 在设置(状态栏栏目开关)中开启后才展示
- 仅当选中目录可以获取到 git 信息时展示,否则隐藏
- 展示当前分支
- **可点击**:点击弹出分支列表,可点击切换到对应分支
- 切换分支后状态栏实时刷新
- **不做轮询**:分支变化由后端通过已建立的 WebSocket 推送(回调),避免频繁接口调用

## 已确认决策

| 决策点 | 结论 |
|---|---|
| git 数据来源 | 后端只读端点执行 `git` 命令 |
| 分支切换方式 | 点击状态栏 → 下拉面板列分支 → 点击切换 |
| 实时刷新机制 | 应用内切换:checkout POST 响应 + WebSocket 广播(回调,无轮询) |
| 外部(终端/IDE)切分支 | **不检测**(用户确认仅更新应用内切换,无后台监听器) |
| 协议扩展 | 不加 `hide`/`refreshMs` 到只读 `StatusBarItem` 协议(YAGNI);交互组件自包含 |

## 架构总览

```
┌─ 前端 ─────────────────────────────────────────────┐
│ GitBranchSelector(自包含,RoleSelector 范式)         │
│  ├ 触发按钮:复用 StatusBarItemView(+ onClick→<button>)│
│  │   展示:GitBranch 图标 + 当前分支                   │
│  └ 下拉面板:role-float 同款,列出分支+✓当前分支        │
│    点击分支 → POST checkout → 关闭并立即刷新          │
│ 订阅 useWebSocket.subscribe() 接收 git_branch 事件    │
└─────────────────────────────────────────────────────┘
        │ ①初始 GET /fs/git(挂载 1 次)
        │ ②打开面板 GET /fs/git/branches
        │ ③点击分支 POST /fs/git/checkout
        │ ④广播 git_branch(所有 /ws/chat 客户端)
        ▼
┌─ 后端 ─────────────────────────────────────────────┐
│ api/routes/fs.py                                   │
│  GET  /fs/git?path=      → { is_git, branch }      │
│  GET  /fs/git/branches?path= → { current, branches }│
│  POST /fs/git/checkout {path,branch} → 切换+广播     │
└─────────────────────────────────────────────────────┘
```

## 组件与职责

### 后端 `api/routes/fs.py`(3 个端点)

- `GET /fs/git?path=` — 执行 `git -C <path> rev-parse --abbrev-ref HEAD`。
  非 git 目录(exit≠0)→ `{ is_git: false, branch: null }`;git 目录 → `{ is_git: true, branch }`。
- `GET /fs/git/branches?path=` — 执行 `git -C <path> for-each-ref refs/heads --format=%(refname:short)`,返回 `{ current, branches }`(current 由 `rev-parse --abbrev-ref HEAD` 得出)。
- `POST /fs/git/checkout` body `{ path, branch }` — 服务端先重新枚举分支集,校验 `branch` 在集合内;`git -C <path> checkout <branch>`(无 `--force`)。
  成功 → 返回 `{ branch }` 并通过 `broadcast_chat_message` 广播 `{ git_branch: { workspace: path, branch } }`;
  冲突(未提交改动被覆盖,exit≠0)→ `409` + git stderr 信息。

**安全**
- 所有 git 调用走 `subprocess.run(["git", "-C", path, ...])`:list 参数、无 `shell=True`,天然防注入。
- 路径复用工作区校验:绝对路径 + `resolve()`。
- checkout 前服务端校验目标分支存在于已枚举分支集,防任意参数。
- 一律带 `timeout`,不传 `--force`。

### 前端组件

**`GitBranchSelector.tsx`**(新,自包含)
- Props:`{ ws: ChatSocket, workspace: string | null }`
- 门槛(任一不满足 → 渲染 `null`):`useStatusBarConfig().config.git` 关 / `workspace` 为 null / 初始探测 `is_git === false`
- 挂载时调一次 `fetchGitInfo(workspace)` 拿初始分支与 is_git
- `useEffect` 订阅 `ws.subscribe(msg => msg.git_branch?.workspace === workspace && setBranch(msg.git_branch.branch))`
- 触发按钮复用 `StatusBarItemView`(加 `onClick` → 渲染 `<button>`):`GitBranch` 图标 + 分支名
- 点击 → 拉 `fetchGitBranches(workspace)` → 下拉面板(`role-float` 同款样式)
  - 当前分支带 ✓(与 RoleSelector 一致)
  - 点击分支 → `checkoutBranch(workspace, branch)` → 成功:关闭面板,分支取自响应/广播;失败:面板内显示 git stderr 错误
- 关闭:外部点击 / Esc

**`StatusBarItemView.tsx`**(改):加可选 `onClick?: () => void`,提供时渲染 `<button>`(保留 `statusbar__item` 类与状态点/图标)。

**`useWebSocket.ts`**(改):加事件订阅
- `subscribe(listener: (msg: WsIncoming) => void): () => void`,返回取消函数
- `onmessage` 中识别 `{ git_branch: {...} }` 消息并派发给所有监听者
- 返回值追加 `subscribe`

**`useStatusBarConfig.ts`**(改):`StatusBarConfig` 加 `git: boolean`(默认 `true`),`load()`/`toggle()` 同步。

**`SettingsPanel.tsx`**(改):状态栏卡片网格加一张 `git` 卡片(lucide `GitBranch` 图标)。

**`api/fs.ts`**(改):加 `fetchGitInfo(path)` / `fetchGitBranches(path)` / `checkoutBranch(path, branch)`。

**`ChatWindow.tsx`**(改):`.statusbar-group` 内、`CacheHitRateItem` 之后加
`<GitBranchSelector ws={ws} workspace={activeConversation?.workspace ?? null} />`。

### i18n

- `settings.statusbarColumns.git` / `settings.statusbarColumns.gitDesc`
- `statusbar.gitTitle`(悬浮提示:"当前分支 {branch}")
- 面板文案:`git.chooseBranch` / `git.switching` / `git.switchFailed`(可并入现有 key 风格)

## 数据流

1. **挂载**:`GitBranchSelector` 渲染 → 门槛检查(config/workspace)→ 调 `GET /fs/git` → `is_git=false` 则整体不渲染;`true` 则显示分支。
2. **打开面板**:点击触发按钮 → `GET /fs/git/branches` → 渲染分支列表(当前分支 ✓)。
3. **切换**:点击分支 → `POST /fs/git/checkout` → 成功:关闭面板 + 分支更新(响应立即生效);失败:面板内错误提示。
4. **回调刷新**:后端在 checkout 成功后广播 `{ git_branch }` → 前端 `subscribe` 监听者更新分支显示(多标签页/多会话同工作区也同步)。

## 错误处理

- git 端点异常 / 非 git 目录 → `is_git: false`,前端隐藏(静默)。
- checkout 冲突(未提交改动)→ `409` + stderr 文案,面板内展示,不强制切换。
- 目标分支不在服务端枚举集 → `422`,前端面板提示。
- 非法/相对路径 → `422`(复用现有路径校验语义)。

## 测试策略

**后端 `tests/test_api/`(fs 路由)**:用 `tmp_path` 建真实 git 仓库(`git init` + `git checkout -b`),`shutil.which("git")` 为空则 skip。
- `GET /fs/git`:git 目录 → `is_git:true` 且 branch 非空;非 git 目录 → `is_git:false`;非法路径 → 422。
- `GET /fs/git/branches`:列分支且 current 正确。
- `POST /fs/git/checkout`:切到 `feature-x` 成功;目标分支不存在 → 422;未提交改动冲突 → 409。
- 广播:`checkout` 后 `broadcast_chat_message` 被调用(可 patch 断言)。

**前端 Vitest**:
- `GitBranchSelector.test.tsx`(mock `api/fs`):config 关 → null;workspace 空 → null;非 git → 不渲染;git → 显示分支;点击 → 面板列分支;点分支 → 调 checkout;checkout 失败 → 面板显示错误;Esc/外部点击 → 关闭;收到 `git_branch` 事件 → 更新。
- `StatusBarItemView.test.tsx`:有 onClick → 渲染 `<button>` 且点击触发。
- `useWebSocket.test.ts`:subscribe 收到 `git_branch` 消息、取消订阅生效。
- `useStatusBarConfig.test.ts`:git 默认 true、toggle 持久化。
- `SettingsPanel.test.tsx`:卡片网格含 `statusbar-card-git`。

## 不做的事(边界)

- 不检测终端/IDE 外部切分支。
- 不创建新分支、不删分支、不 `--force`。
- 不在只读 `StatusBarItem` 协议上加 `hide`/`refreshMs`。
- 不加后台监听器/新依赖。
