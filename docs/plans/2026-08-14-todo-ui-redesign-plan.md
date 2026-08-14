# 待办页面 UI 重设计实现计划

- **设计文档**：`docs/plans/2026-08-14-todo-ui-redesign-design.md`（规格唯一来源，冲突时以设计文档为准）
- **分支**：`feat/todo-ui-redesign`（基于 main，PR #9 已合入）
- **执行方式**：TDD + 子代理驱动 + 每任务双审查（规格 + 质量）
- **范围红线**：纯前端。不修改后端、`api/todo.ts`、`Header.tsx`、`App.tsx`、导航
- **验证命令**（frontend/）：`npx vitest run`、`npm run lint`、`npx tsc --noEmit`、`npm run build`

**环境注意（每个任务都适用）**：
1. 工作区有他人未提交改动：`frontend/src/App.css` 中部 ~14 行、`frontend/src/components/Layout/Sidebar.tsx`，以及未跟踪文件 `docs/plans/checkpoint-context-design.md`、`docs/plans/2026-08-14-interruptible-stop-design.md`——**全部不要碰、不要提交**
2. App.css 提交分离手法：`git stash push -- frontend/src/App.css` → 文件回到 HEAD → 重新应用自己的改动 → `git add App.css` → commit → `git stash pop`（三方合并恢复他人改动）。每次提交后 `git status` 验证他人改动仍原样在工作区
3. 测试红线：所有 `data-testid` 保留；checkbox 的 role 与按条目文本的 aria-label 保留；现有测试断言的英文文案（'Todo List'、'Add a new task…'、'Edit'、'Delete' 等）若因重设计变化，必须同步更新测试且保持断言强度，并在回报中列出
4. 每个任务单独 commit（conventional commits 中文描述）；提交前确保 `npx vitest run` 全量绿

---

## Task 1：i18n 键 + 统计头 TodoStatsBar + 骨架加载（TDD）

**文件**：`frontend/src/i18n/locales/en.json`、`zh-CN.json`、`frontend/src/components/Todo/TodoPage.tsx`、`TodoPage.test.tsx`、`frontend/src/App.css`

### 1.1 i18n：两个 locale 各新增 11 键（todo 段内）

| 键 | en | zh-CN |
|---|---|---|
| all | All | 全部 |
| active | Active | 未完成 |
| done | Done | 已完成 |
| remaining | pending | 待办 |
| doneCount | completed | 已完成 |
| noteCount | notes | 随手记 |
| progress | Completion progress | 完成进度 |
| noActive | All done! | 全部完成！ |
| noCompleted | Nothing completed yet | 还没有已完成项 |
| today | Today | 今天 |
| yesterday | Yesterday | 昨天 |

键序：en 与 zh 完全一致；追加在 todo 段末尾，2 空格缩进。

### 1.2 先写测试（TodoPage.test.tsx 追加）

- `renders stats bar with correct counts`：mock 2 条 items（1 条 done）+ 3 条 notes → 统计头显示 `1 pending`、`1 completed`、`3 notes`（getByText）；progressbar 元素存在且 `aria-valuenow="50"`、`aria-valuemin="0"`、`aria-valuemax="100"`
- `stats bar shows zero state`：空 items → `0 pending`、`0 completed`，progressbar `aria-valuenow="0"`（不除零崩溃）
- `loading renders skeletons`：mock fetch 返回挂起的 Promise（永不 resolve）→ 容器内出现 `.todo-skeleton` 元素（`container.querySelectorAll('.todo-skeleton').length > 0`），不渲染统计数字

运行 → 应失败（组件不存在）。

### 1.3 实现

**TodoStatsBar**（TodoPage.tsx 内函数组件）：
```tsx
interface TodoStatsBarProps { items: TodoItem[]; notes: TodoNote[] }
```
- 派生：total、done、remaining = total - done、pct = total === 0 ? 0 : Math.round((done/total)*100)
- 结构：`<div className="todo-stats card">` 内 flex：
  - `<ClipboardList className="todo-stats__icon" />` + `<span className="todo-stats__num">{remaining}</span>` + 标签 `t('todo.remaining')`
  - `<CheckCircle2 />`（success 色）+ done + `t('todo.doneCount')`
  - `<StickyNote />`（orange）+ notes.length + `t('todo.noteCount')`
  - 进度条：`<div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={t('todo.progress')} className="todo-stats__progress"><div className="todo-stats__progress-fill" style={{ width: `${pct}%` }} /></div>` + `<span className="todo-stats__pct">{pct}%</span>`
- lucide 导入追加 `CheckCircle2`

**骨架加载**：`loading` 分支改为渲染统计头骨架 + 两个面板骨架（`<div className="todo-skeleton" style 固定高度>` 若干块），保留 `data-testid="todo-loading"`。

**渲染位置**：TodoPage 正常分支中，`todo-page` 双栏之前插入 `<TodoStatsBar items={items} notes={notes} />`。

**CSS**（App.css Todo 区块追加，全部用令牌）：`.todo-stats`（flex、gap、card 样式复用）、数字 `--fs-md --fw-semi`、标签 `--fs-xs` secondary、进度条轨道 `var(--bg-hover)` 6px `radius-full`、填充渐变 `linear-gradient(90deg, var(--accent), var(--accent-hover))` + `transition: width var(--dur-slow) var(--ease-out)`；`.todo-skeleton`（bg `var(--bg-hover)` + `@keyframes todo-shimmer` 1.2s infinite）。

### 1.4 验证与提交

`npx vitest run` 全绿 → lint/tsc → 提交（locale JSON + Todo 组件/测试 + App.css 分离手法）：
`feat(frontend): 待办页添加统计头与骨架加载`

---

## Task 2：TodoEmptyState + TodoFilterTabs + 筛选（TDD）

**文件**：`TodoPage.tsx`、`TodoPage.test.tsx`、`App.css`

### 2.1 先写测试

- `filter tabs toggle visible items`：2 条 items（1 done）→ 点 `t('todo.active')` 按钮（"Active"）→ 已完成项文本不渲染、未完成项在；点 "Done" → 反之；点 "All" → 都在
- `filter tabs show aria-pressed`：激活标签 `aria-pressed="true"`，其余 false
- `active filter empty shows celebration`：仅 1 条 done 项 → 点 "Active" → 渲染 `All done!` 文案（todo.noActive）
- `done filter empty shows noCompleted`：仅 1 条未完成项 → 点 "Done" → 渲染 `Nothing completed yet`
- `filter tabs show counts`：标签内含计数数字（all=2、active=1、done=1）

运行 → 应失败。

### 2.2 实现

**TodoEmptyState**（函数组件）：`{ icon: LucideIcon, text: string }` → `<div className="todo-empty-state"><Icon size={32} /><p>{text}</p></div>`

**TodoFilterTabs**（函数组件）：
```tsx
interface TodoFilterTabsProps {
  value: 'all' | 'active' | 'done'
  counts: { all: number; active: number; done: number }
  onChange: (v: 'all' | 'active' | 'done') => void
}
```
三个 `<button aria-pressed={value===v} className={激活态类}>` + 文案 + 计数（`{label} {count}` 结构，计数用 `<span>`）。

**TodoPage**：`const [filter, setFilter] = useState<'all'|'active'|'done'>('all')`；`visibleItems = useMemo(filter)`：all→items、active→`!done`、done→`done`。TodoListPanel 接收 `items={visibleItems}` 但**面板空态判断用原始 items**：
- items.length === 0 → EmptyState（ClipboardList + todo.empty）
- visibleItems.length === 0 && filter==='active' → EmptyState（CheckCircle2，success 色 + todo.noActive）
- visibleItems.length === 0 && filter==='done' → EmptyState（Inbox + todo.noCompleted）
FilterTabs 渲染在面板 card-title 之后、todo-add 之前。

**CSS**：`.todo-filter-tabs`（flex、容器 `var(--bg)` 底 + 1px 边框 + `radius-full`、内边距 2px）；按钮激活态 `var(--accent-muted)` 底 + `var(--accent)` 文字 + `--fw-med`，非激活 secondary、hover primary；`.todo-empty-state`（垂直居中、`--sp-8` 上下边距、图标 32px 60% 透明、文案 `--fs-sm` secondary）。

### 2.3 验证与提交

全绿后提交：`feat(frontend): 待办添加筛选标签与多态空状态`

---

## Task 3：TodoItemRow 重设计（TDD + 现有测试适配）

**文件**：`TodoPage.tsx`、`TodoPage.test.tsx`、`App.css`

### 3.1 先改测试（红）

- 现有用例中 `getByText('Edit')`/`getByText('Delete')` 类断言：行内操作改为纯图标按钮后文案移到 `aria-label`，改为 `getByLabelText('Edit')` / `getByLabelText('Delete')`（或 getByTitle）——**逐一核对测试文件实际写法后适配，保持断言强度不降级**
- 新增 `item action buttons have accessible labels`：渲染 1 条 item → `getByLabelText('Edit')` 与 `getByLabelText('Delete')` 均为可聚焦的 button
- checkbox 相关断言不变（getByLabelText(条目文本) 仍是 checkbox）

### 3.2 实现

**TSX 变更**（TodoListPanel 行渲染）：
- 编辑/删除按钮改为纯图标：`<button className="todo-item__action" aria-label={t('todo.edit')} title={t('todo.edit')}><Pencil size={14}/></button>`；删除同款（保留 `btn-danger` 语义色，用新类承载）
- 编辑模式内的保存/取消按钮**保持带文字**（不变）
- 条目容器类名不变（`todo-item`、`todo-item--done`），`data-testid="todo-item"` 保留
- 条目挂入场动画类（CSS 层实现，TSX 无需改）

**CSS 重写**（App.css Todo 区块内替换 todo-item 相关规则）：
- 容器：去边框，`padding: var(--sp-2) var(--sp-3)`、`radius-sm`、hover `var(--bg-hover)`；`--done` 整行 `opacity: .68`
- 自定义复选框：`appearance: none`、18px 圆形、2px `var(--border)` 边、`cursor: pointer`、`transition`；`:checked` 背景 `var(--accent)`、边框同色、`::after` 白色对勾（旋转边框法：宽 4px 高 8px、border-right/bottom 2px 白、rotate(45deg)、居中）；`:focus-visible` 用 `box-shadow: var(--focus-ring)` 等效
- 操作区 `.todo-item__actions`：`opacity: 0`、容器 `:hover`/`:focus-within` 时 `opacity: 1`、`transition: opacity var(--dur-fast)`；图标按钮 28px 方形 ghost 样式、hover `var(--bg-active)`；删除图标色 `var(--error)`
- 入场动画：`@keyframes todo-item-in { from { opacity: 0; transform: translateY(-4px) } to { opacity: 1; transform: none } }`，`.todo-item { animation: todo-item-in var(--dur-base) var(--ease-out) }`
- `@media (prefers-reduced-motion: reduce)`：禁用 todo-item-in 与 todo-shimmer

### 3.3 验证与提交

全量测试绿 + lint + tsc → 提交：`feat(frontend): 重设计待办条目（圆形复选框+悬停操作+入场动画）`

---

## Task 4：随手记日期分组与便签卡片（TDD）

**文件**：`TodoPage.tsx`、`TodoPage.test.tsx`、`App.css`

### 4.1 先写测试

- `notes grouped by day`：mock 两条 note，timestamp 分别为今天 `HH:MM`（用 `new Date()` 构造当天日期字符串）与昨天 → 渲染两个分组头，文本为 'Today' 与 'Yesterday'（英文 locale）
- `older notes show date header`：timestamp '2026-01-01 10:00' → 分组头文本 '2026-01-01'
- 组内顺序：同组两条 note，先渲染 index 小的（API 顺序，新在上）——断言两个 note 卡片的 DOM 先后
- 现有 delete/edit 用例仍绿（note-delete testid 保留）

### 4.2 实现

**分组辅助**（TodoPage.tsx 内，纯函数可单测）：
```ts
type NoteGroup = { key: string; label: string; notes: TodoNote[] }
function groupNotesByDay(notes: TodoNote[], now: Date): NoteGroup[]
```
- 取 `note.timestamp.slice(0, 10)` 为日期键；与 now 的本地日期比较：今天→`t('todo.today')`、昨天→`t('todo.yesterday')`、其余→日期键原样
- t 在组件层传入或返回键由组件翻译（实现者选择，保持纯函数可测：建议纯函数返回 `{key, date}`，label 由组件查表翻译）
- 保持输入顺序，不排序（API 已按新在上）；"昨天"计算：`now - 1 天` 的本地日期字符串比较

**渲染**：TodoNotesPanel 列表区改为 `groupNotesByDay(notes, new Date())` 的 flatMap：每组先渲染 `<div className="todo-note-group__header">{label}</div>` 再渲染组内卡片。

**CSS**：
- 分组头：`--fs-xs` secondary、flex 布局两侧 1px `var(--border)` 细线（`::before/::after` flex:1）、上下 `--sp-3` 边距
- `.todo-note` 便签化：背景 `var(--bg)`、`radius`、`border-left: 3px solid var(--accent-secondary)`、hover `translateY(-1px)` + `var(--shadow-sm)`、`transition: transform/box-shadow var(--dur-fast)`
- 时间戳 `--fs-xs` secondary；操作按钮复用 3.2 的悬停显示规则（`.todo-note__actions` 同款 opacity 规则）
- 编辑/删除按钮同样改纯图标 + aria-label + title（与 Task 3 一致），测试适配同 Task 3 手法

### 4.3 验证与提交

全绿 → 提交：`feat(frontend): 随手记便签卡片化与日期分组`

---

## Task 5：全量验证与文档检查

1. `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit && npm run build` 全绿
2. 三主题自查：代码 grep 确认 Todo 区块无硬编码色值（hex/rgb），全部 `var(--*)`
3. 1023px 断点行为自查（CSS 审阅：统计条换行、双栏堆叠）
4. README 检查：本次为纯 UI 重设计，功能描述未变——确认 README.md/README_CN.md 无需改动（在回报中说明检查结论）
5. 如有收尾性 CSS 微调（间距/对齐），合并为一个提交：`style(frontend): 待办页重设计收尾微调`（无改动则跳过）

---

## 验收标准（对齐设计文档第 7 节）

- [ ] 统计头数字与进度条与列表数据实时一致（写操作后自动更新——组件派生自 items/notes state，天然满足）
- [ ] 三档筛选即时切换、筛选空态文案正确（noActive/noCompleted）
- [ ] 随手记按 今天/昨天/日期 分组，组内新在上
- [ ] 行内操作默认隐藏，悬停/键盘聚焦（:focus-within）可见可操作
- [ ] 三主题无硬编码色；prefers-reduced-motion 禁用动画
- [ ] ≤1023px 单栏堆叠
- [ ] 现有测试适配后全绿 + 新增用例通过；lint/tsc/build 全绿
- [ ] 他人未提交改动（App.css 中部、Sidebar.tsx）全程未被污染
