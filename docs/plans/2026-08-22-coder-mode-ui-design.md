# 码农（Coder）页面 UI 设计规格

- 日期：2026-08-22
- 状态：草案（待确认后实施）
- 范围：码农页面视觉与交互美化 —— IDE/终端风格；覆盖 CoderSidebar、WorkspacePicker、CoderPage 空态与容器级装饰；不改动 ChatWindow 内部组件
- 依赖现状：`frontend/src/components/Coder/*`（PR #16）、`frontend/src/styles/themes.css`（dark/light/warm 三主题 token）、手写 CSS 体系、i18n 双语言

## 1. 用户与场景

- 目标用户：开发者，用码农模式对某个服务器工作区做编码任务（读代码、改文件、跑命令）。
- 产品目标：让"码农页"一眼可辨为工作区导向的编码环境，而非普通聊天；降低"选工作区→开始干活"的摩擦。
- 场景：同机部署（服务器+浏览器同机）；浏览器为 Chromium 系为主，须兼容无 File System Access API 的环境。
- 约束：现有 token 体系（三主题）必须继续生效，新增样式全部基于既有 CSS 变量；普通聊天页零改动；可访问性对齐现有组件（键盘操作、aria、testid 测试约定）。

## 2. 视觉差异原则（IDE/终端风格）

与聊天页的差异靠**结构质感 + 色彩分离**，不靠图标堆砌：

| 维度 | 聊天页（现状） | 码农页（目标） |
|---|---|---|
| 强调色 | `--accent`（青绿） | `--accent-secondary`（橙）作为 coder 专属强调 |
| 侧栏形态 | 扁平列表、圆角卡片 | 目录树：缩进层级、等宽目录名、折叠动画、左侧 2px 指示条 |
| 圆角 | 中等圆角（卡片） | 收敛：面板 `4px`、控件仍用现有圆角，弱化气泡感 |
| 字体 | 默认 UI 栈 | 目录名、状态行、弹窗标题用等宽栈 `--coder-mono` |
| 面板 | 背景 $bg-surface | 关键面板叠加 `--code-bg` 色调与细边框 `--border-subtle` |
| 纹理 | 无 | 顶部细条（orange）作为"模式标记"，导航 active 态同步 |

新增局部变量（定义在 css 作用域类 `.coder-*` 上，引用既有主题 token，避免触碰 themes.css 全局）：

```css
.coder-shell {
  --coder-accent: var(--accent-secondary);
  --coder-accent-hover: var(--accent-secondary-hover);
  --coder-accent-muted: var(--accent-secondary-muted);
  --coder-accent-border: var(--accent-secondary-border);
  --coder-mono: ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace;
  --coder-panel: var(--code-bg);
  --coder-border: var(--border-subtle);
}
```

## 3. 流程与状态

### 3.1 主流程（New Session）

1. 用户点击导航「码农」→ CoderPage。
2. 无会话：空态（新设计）→ 点击「选择工作区」或按 `N` → WorkspacePicker。
3. Picker 中：输入绝对路径（或点「选择目录」辅助、或点「最近工作区」回填）→ 提交 → 后端校验。
4. 成功：关闭弹窗 → 回拉列表 → 自动选中新会话 → ChatWindow 呈现。
5. 失败（422）：弹窗内错误区显示 detail，输入保留。

### 3.2 状态清单

| 状态 | 触发 | 表现 |
|---|---|---|
| 空态 | 无 coder 会话 | 居中 hero：Code2 大图标 + 标题 + 引导文案 + 主按钮「选择工作区」+ `N` 快捷键提示；**不要** mini 空洞提示 |
| 加载中 | coder 列表 fetch 中 | 侧栏显示 3 条骨架；页面不闪跳 |
| 列表加载失败 | fetch 拒绝 | 侧栏错误行 + 「重试」按钮（沿用 `common.retry`） |
| 无有效选中（chat 会话或未选中） | 跨页/新建前 | 现有 `coder-no-selection` 占位升级为 hero 的一半高度引导（含按钮） |
| Picker：能力缺失 | 无 `showDirectoryPicker` | 「选择目录」按钮隐藏；`aria-live` 提示"可直接输入完整路径" |
| Picker：校验中 | 提交后 | 按钮置禁用 + `common.saving` 文案 |
| Picker：错误 | 后端 422/网络失败 | 错误区（等宽小字、`--error` 色）`aria-live=assertive`；输入不清空 |
| Picker：目录辅助成功 | user 选到目录 | 输入框下方 hint 行回填 `handle.name`，颜色用 `--success` |

## 4. 组件规格

### 4.1 CoderSidebar（目录树重设计）

- 结构：`<ul role="tree">`；每个 workspace 组 = `role="treeitem" aria-expanded` 的树节点，其下会话项为子节点缩进。
- 组头：`FolderOpen`/`FolderClosed`（折叠态）+ 等宽目录名（取末段，`--coder-mono`）+ 计数 badge（`--coder-accent-muted` 底）+ chevron 旋转动画（`--dur-fast`/`--ease-out`）；`title` 属性暴露完整路径。
- 组头 hover：`--bg-hover`；active 会话项：左侧 2px 橙条 `border-left: 2px solid var(--coder-accent)` + `--bg-active`。
- 会话项：保留现有图标/重命名/删除按钮（复用现有交互），文字仍用默认栈（只有目录名等宽，可读性优先）。
- 折叠动画：`max-height: 0 ↔ 子列表高度`，`--dur-fast`；首屏默认全部展开。
- 空列表：沿用 `.sidebar-empty` 但文案升级（见空态）。
- a11y：组头为 `button`，`aria-expanded` 反映状态；键盘方向键左右折叠/展开（与 treemap 惯例一致，此项可与实现确认降级为 Tab 可达）。

### 4.2 WorkspacePicker（终端弹窗重设计）

- 外观：顶部 `--bg-elevated` 标题栏——左侧三个交通灯圆点（`--error`/`--warning`/`--success` 各 8px，纯装饰，`aria-hidden`）+ 等宽标题「new workspace session」；正文 `--bg` 底 + `--coder-border` 细边。
- 内容区：
  1. 标签 + 路径输入框（mono，`--bg-input`），Enter 提交；
  2. 「选择目录」按钮（侦探到 `showDirectoryPicker` 才渲染）：点击 → 请求 `read` 权限 → 成功后显示 `--success` 的 hint：`已确认目录（名称）: <name>`；取消/失败静默；
  3. 「最近工作区」区（可选，建议做）：从现有 coder 会话 `workspace` 去重取前 5，`chips` 渲染，点击回填输入框；
  4. 错误区：`--error` 等宽小字，`role="status"`；
  5. footer 右对齐：取消 / 创建（主按钮，用 `--coder-accent`）。
- 交互：点击遮罩/Esc 关闭；打开时焦点入输入框；关闭还原焦点（复用现有模态行为）。
- 提交载荷不变：`{mode:'coder', workspace}`；创建成功回调 `onCreated(id)` 由 CoderPage 关闭弹窗。

### 4.3 CoderPage（容器级装饰 + 空态）

- 根：`.coder-shell` 包裹 CoderSidebar + ChatWindow，顶部 2px `--coder-accent` 细条作为模式标记。
- ChatWindow 容器装饰：给其外层加 `.coder-viewport`（背景叠 `--code-bg` 至 30% 透明度、右侧/底部细边框），**不改 ChatWindow / InputBox 内部**——仅容器级视觉，消息区本身沿用聊天页。
- 空态 hero：居中（图标 Code2 56px，`--coder-accent-muted` 光环）+ 标题 + 描述 + 主按钮「选择工作区」+ 快捷键 hint `N`（`<kbd>`）；`data-testid="coder-hero-empty"`。
- `coder-no-selection` 占位：升级为同 hero 风格但精简（不再要求二次开发，纯样式调整）。
- 快捷键 `N`：在 hero 显示时按 `n`/`N` 打开 Picker（页面级 keydown，仅当 Picker 未开且弹窗未开；防抖重复触发）。此项若实现成本高可降级为仅按钮。

### 4.4 导航态

- `nav-coder` 激活态：文本/图标用 `--coder-accent`（现为 `--accent`），形成"当前处于编码模式"的信号。改法：Header 的 active 样式加 `[data-page="coder"]` 类或 `.nav-coder.active` 覆盖，仅在 coder 页生效。

## 5. 可访问性与响应式

- 对比度：全部引用现有主题 token（已在三主题中满足 WCAG 近似标准），不引入裸色值。
- 键盘：弹窗焦点管理（复用现有 `.modal` 行为）；目录树项 Tab 可达；Esc 关弹窗；错误即时播报。
- 响应式：延续现状（桌面优先）；侧栏最小宽 220px，窄屏下弹窗 `max-width: min(560px, 92vw)`。
- 测试：新增/更新测试全部用 `data-testid`，不依赖译文；i18n 新键双语言必填。

## 6. 设计 Token 与 i18n 新增键

- 样式：不新增大主题切换变量；局部变量归入 `.coder-shell` 作用域（见第 2 节）。
- i18n 新增（en/zh 同时）：
  - `coder.selectToStart`（已有）沿用
  - `coder.heroTitle`：开始一个编码会话 / Start a coding session
  - `coder.heroDesc`：选择服务器上的工作区，让码农在真实项目里工作 / Pick a workspace on the server so Coder works in your real project
  - `coder.heroCta`：选择工作区 / Choose workspace
  - `coder.heroShortcut`：快捷键 N / Shortcut N
  - `coder.recentWorkspaces`：最近工作区 / Recent workspaces
  - `coder.pickerTitle`：new workspace session（双语一致，终端文案风格）
  - `coder.dirUnavailable`：当前浏览器不支持目录选择，请直接输入完整路径 / Directory picker unsupported — type the full path
  - `coder.dirConfirmed`：已确认目录（名称）/ Directory confirmed (name)
  - `coder.loadFailed`：会话列表加载失败 / Failed to load sessions
  - `coder.retry`：重试（可复用 `common.retry` 时省略）

## 7. 工程交付

- 目标：React 19 + Vite + 手写 CSS 的纯 SPA（仓库无 Tailwind），沿用 `frontend/src/styles` token、现有组件测试惯例（Vitest + Testing Library + data-testid）。
- 建议分支：从 `main` 起新分支 `feat/coder-mode-ui`（与 PR #16 分离），完成后单独 PR。
- 实施边界：
  1. 只改 `frontend/src/components/Coder/*`、`Header.tsx`（active 态一行）、`App.css`（追加 `.coder-*` 作用域样式，不改既有规则）、两个 locale 文件、相关测试；
  2. 不触碰 `ChatWindow.tsx`、`InputBox.tsx`、`Sidebar.tsx`、`themes.css`、后端；
  3. `showDirectoryPicker`：仅作辅助（回填目录名）+ 能力探测隐藏按钮；不改变"路径必须由用户输入"的提交模型。
- 验收标准：
  - `cd frontend && npm test` 全绿（含新增/更新测试：目录树分组折叠、空态 hero、Picker 能力缺失分支、最近工作区回填）；
  - `npx tsc -b`、eslint 通过；
  - 三主题（dark/light/warm）手工检查 coder 页无坏对比度；
  - 聊天页视觉回归无变化；
  - 后端无改动、PR #16 行为不受影响。