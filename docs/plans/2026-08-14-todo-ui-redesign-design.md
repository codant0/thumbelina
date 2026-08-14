# 待办页面 UI 重设计（设计交接文档）

- **日期**：2026-08-14
- **技能**：frontend-design-ui-ux（本文档为设计规范，不含实现代码）
- **对象页面**：`frontend/src/components/Todo/TodoPage.tsx`
- **设计深度**：结构性重设计（用户确认）
- **布局方向**：统计头 + 双栏（用户确认）
- **关键约束**：纯前端改动，不改后端 API；沿用现有设计令牌体系

---

## 1. 用户与上下文摘要

| 维度 | 结论 |
|---|---|
| 目标用户 | Thumbelina 个人助手使用者（单用户、本人） |
| 产品目标 | 将 TODO 页从"功能清单"升级为**个人信息仪表盘**：一眼看到完成进度，快速记录待办与灵感 |
| 使用场景 | 桌面为主、高频短操作（<5 秒的记一条/勾一条），偶尔回顾随手记 |
| 设备上下文 | 桌面浏览器宽屏为主，向下响应式适配到窄屏堆叠 |
| 设计系统 | 必须沿用：teal（待办身份色）+ orange（随手记身份色）、BEM、`--sp-*/--fs-*/--radius*/--dur-*` 令牌、三主题（dark/light/warm）、lucide-react |
| 无障碍基线 | 现有 aria-label/role 已达标，重设计必须保持或提升；支持 `prefers-reduced-motion` |

### 问题陈述（设计前）

现有页面视觉偏"素"：原生复选框、边框行列表、编辑/删除按钮常驻造成视觉噪声、随手记无便签质感、空状态仅一行灰字、无完成进度反馈、无筛选能力。

### 设计目标（验收导向）

1. **进度可见**：页面顶部一眼看到 剩余/已完成/进度百分比
2. **噪声降低**：行内操作按钮悬停才显示，界面静态时干净
3. **身份区分**：待办 = teal 语义，随手记 = orange 便签语义
4. **可筛选**：待办支持 全部/未完成/已完成 切换（纯前端）
5. **可回顾**：随手记按日期分组（今天/昨天/日期）

---

## 2. 流程与状态模型

### 2.1 主用户旅程

```
[进入待办页]
    │
    ▼
◇ 模块状态？(GET /todo/status)
    ├── enabled=false ──▶ [降级提示页]（保持现状）
    ├── 请求失败 ──────▶ [错误页 + 重试]（保持现状）
    └── enabled=true
    │
    ▼
[统计头 + 双栏渲染]（骨架屏加载态）
    │
    ├──▶ 记待办：输入 → Enter/按钮 → 条目入场动画 → 进度条更新
    ├──▶ 勾完成：点复选框 → 勾选动画+划线 → 该项在"未完成"筛选下淡出 → 进度条动画前进
    ├──▶ 筛选：点标签 → 列表即时切换（无请求）→ 空筛选结果显示专属空态
    ├──▶ 记随手记：输入 → 追加 → 卡片出现在"今天"分组顶部
    └──▶ 回顾随手记：滚动浏览日期分组 → 悬停卡片 → 编辑/删除
```

### 2.2 状态矩阵（必须全部覆盖）

| 状态 | 统计头 | 待办面板 | 随手记面板 |
|---|---|---|---|
| 初始加载 | 骨架占位（数字块灰底微光） | 3 条骨架行 | 2 条骨架卡片 |
| 加载失败 | 不渲染 | 错误卡 + 重试按钮（保持现状） | 同左 |
| 模块禁用 | 不渲染 | 降级提示（保持现状） | 同左 |
| 全空（无任何数据） | 显示 0 值与 0% | 空态 A：图标 + "暂无待办"引导文案 | 空态：图标 + "写点什么吧"引导文案 |
| 筛选后为空 | 正常 | 空态 B：如筛选"未完成"且全部完成 → "全部完成 🎉"（用 CheckCircle 图标，不用 emoji） | —（无筛选） |
| 写操作中（busy） | 正常 | 控件 disabled（保持现状语义） | 同左 |
| 写失败 | 正常 | 错误横幅 + 数据保留（保持现状） | 同左 |
| 正常 | 实时数字 + 进度条 | 列表 | 日期分组列表 |

### 2.3 边缘情况

| 场景 | 处理 |
|---|---|
| 勾选条目时正处于"未完成"筛选 | 条目完成动画播放后从列表消失（列表由 API 返回全量替换，React key=index 自然移除）；统计头同步更新 |
| 跨天停留页面（随手记"今天"分组过期） | 不处理（下次进入页面自然刷新）——YAGNI |
| 随手记时间戳为未来时间（用户改系统时钟） | 归入"今天"之后的分组按日期原样显示 |
| 筛选状态在写操作后 | 筛选是纯前端视图层，写操作返回全量列表后继续按当前筛选渲染 |
| `prefers-reduced-motion` | 所有入场/勾选/进度动画退化为即时呈现 |

---

## 3. 组件规格

### 3.1 组件树

```
TodoPage
├── TodoStatsBar            ★新增
├── todo-page（双栏 grid）
│   ├── TodoListPanel
│   │   ├── TodoFilterTabs  ★新增
│   │   ├── todo-add（输入行，样式增强）
│   │   ├── TodoItemRow × N ★重设计
│   │   └── TodoEmptyState  ★新增（多变体）
│   └── TodoNotesPanel
│       ├── todo-note-form（样式增强）
│       ├── DateGroupHeader + TodoNoteCard × N ★重设计
│       └── TodoEmptyState
```

### 3.2 Component: TodoStatsBar

**目的**：全宽展示待办进度概览，是页面的"仪表盘"焦点。

**结构**（单个 `card` 容器，内部 flex）：
- 左：`ListTodo` 图标 + `{剩余} 待办`（剩余 = 总数 − 完成数）
- 中：`CheckCircle2` 图标（success 色）+ `{n} 已完成`；`StickyNote` 图标（orange）+ `{n} 随手记`
- 右：进度条（flex: 1，最小宽度 120px）+ 百分比文本

**Props**：`items: TodoItem[]`、`notes: TodoNote[]`（派生计算，无新请求）

**进度条规格**：
- 容器：`role="progressbar"` `aria-valuemin=0` `aria-valuemax=100` `aria-valuenow={pct}` `aria-label={t('todo.progress')}`
- 轨道：高 6px、`radius-full`、背景 `var(--bg-hover)`
- 填充：宽度 `{pct}%`、背景 `linear-gradient(90deg, var(--accent), var(--accent-hover))`、`transition: width var(--dur-slow) var(--ease-out)`
- 0 条待办时 pct=0，显示空轨道（不显示除零错误）

**状态**：加载态渲染骨架（3 个灰底圆角块，复用 shimmer 动画类 `.todo-skeleton`）

**响应式**：≤1023px 时统计项 wrap 为两行，进度条占满第二行

### 3.3 Component: TodoFilterTabs

**目的**：待办筛选切换（全部/未完成/已完成），纯前端过滤。

**实现形态**：分段控件（segmented control），容器 `var(--bg)` 底色 + 1px 边框 + `radius-full`，三个按钮。

**Props 与状态**：

```typescript
interface TodoFilterTabsProps {
  value: 'all' | 'active' | 'done';
  counts: { all: number; active: number; done: number };
  onChange: (v: 'all' | 'active' | 'done') => void;
}
```

**视觉**：
- 激活按钮：背景 `var(--accent-muted)`、文字 `var(--accent)`、`--fw-med`
- 未激活：文字 `var(--text-secondary)`，hover 时 `var(--text-primary)`
- 每个标签显示计数徽标（如 `未完成 3`），计数为 0 时仍显示（灰显）

**无障碍**：三个原生 `<button>` + `aria-pressed={value===v}`；不用 role="tablist"（筛选不是标签页语义）

**状态记忆**：仅组件内 state，默认 `'all'`，不持久化（YAGNI）

### 3.4 Component: TodoItemRow（重设计）

**保留**：`data-testid="todo-item"`、原生 `<input type="checkbox">`（测试 `getByRole('checkbox')`/`getByLabelText` 依赖）、aria-label=item.text、编辑模式结构与快捷键（Enter/Esc）。

**视觉重设计**：

| 部位 | 现状 | 新设计 |
|---|---|---|
| 容器 | 边框行 | 无边框行，`padding: var(--sp-2) var(--sp-3)`、`radius-sm`、hover 背景 `var(--bg-hover)`；完成态整行 `opacity: .68` |
| 复选框 | 原生 14px | 自定义圆形：`appearance: none`、18px 圆、2px `var(--border)` 边；checked 时背景 `var(--accent)` + 白色对勾（`::after` 旋转边框法或背景 SVG）；过渡 `var(--dur-fast)` |
| 文本 | 13px | `--fs-base`；完成态划线 + `var(--text-secondary)`（保持） |
| 操作按钮 | 常驻、带文字 | **悬停/焦点才显示**（容器 `:hover`/`:focus-within` 时 opacity 0→1）、收缩为纯图标按钮（Pencil/Trash2，保留 aria-label 与 title 提供文案）；编辑模式下保存/取消按钮保持带文字 |

**入场动画**：新条目 `fadeIn + translateY(-4px→0)`，`var(--dur-base) var(--ease-out)`；用 CSS `@keyframes todo-item-in`，仅对挂载应用（不加 FLIP 重排动画——YAGNI）

**键盘**：Tab 序 = 复选框 → （悬停显示但始终可聚焦的）编辑 → 删除；编辑输入框 Enter 保存 / Esc 取消（保持）

### 3.5 Component: TodoNoteCard（重设计）

**保留**：`data-testid="todo-note"`、`note-delete` testid、编辑/删除交互、timestamp 显示、aria-label。

**视觉（便签身份）**：
- 卡片：背景 `var(--bg)`、`radius`、**左侧 3px `var(--accent-secondary)` 边条**（orange = 随手记身份色）
- 悬停：`translateY(-1px)` + `var(--shadow-sm)`，过渡 `var(--dur-fast)`
- 头部：timestamp 用 `--fs-xs` `var(--text-secondary)`；操作按钮同 3.4 悬停显示规则
- 内容：`white-space: pre-wrap`、`--fs-sm`、行高 1.6

**日期分组（DateGroupHeader）**：
- 分组键：由 `note.timestamp`（格式 `YYYY-MM-DD HH:MM`，前端可安全解析）取日期部分，与"今天/昨天"比较（本地时区）
- 分隔样式：`--fs-xs` `var(--text-secondary)`，两侧细线（`flex + ::before/::after` 1px `var(--border)`）或单侧线 + 文本，二者取实现简单者
- 文案：今天 → `todo.today`；昨天 → `todo.yesterday`；更早 → 原样显示 `YYYY-MM-DD`
- 分组内卡片顺序保持 API 返回顺序（新在上）

### 3.6 Component: TodoEmptyState（新增，多变体）

**Props**：`icon: LucideIcon`、`text: string`（已翻译）、`variant?: 'default' | 'celebrate'`

**视觉**：垂直居中、`padding: var(--sp-8) 0`、图标 32px `var(--text-secondary)` 透明度 60%、文案 `--fs-sm` secondary

**变体使用**：
- 待办无任何数据：`ClipboardList` + `todo.empty`
- 筛选"未完成"为空（有已完成项）：`CheckCircle2`（success 色）+ `todo.noActive`（"全部完成"）
- 筛选"已完成"为空：`Inbox` + `todo.noCompleted`
- 随手记无数据：`StickyNote` + `todo.emptyNotes`

### 3.7 加载骨架（新增）

`.todo-skeleton`：`background: var(--bg-hover)` + `border-radius: var(--radius-sm)` + shimmer 动画（`@keyframes todo-shimmer` 背景位置平移，`1.2s infinite`）。统计头与两个面板加载时各渲染固定形状。**禁止**用随机数控制骨架尺寸（SSR/测试稳定性）。

---

## 4. 设计令牌决策（仅新增/约定，不改全局令牌）

| 决策 | 值 | 理由 |
|---|---|---|
| 待办身份色 | `--accent`（teal）系列 | 与全局主色一致，复选框/筛选激活/进度条 |
| 随手记身份色 | `--accent-secondary`（orange）系列 | 便签左边条、随手记统计图标 |
| 完成反馈色 | `--success`（仅"全部完成"空态图标） | 克制的庆祝感 |
| 进度条轨道 | `var(--bg-hover)` | 三主题自适应，无需新令牌 |
| 进度条填充 | `linear-gradient(90deg, var(--accent), var(--accent-hover))` | 微质感，不引入新色 |
| 动效时长 | 全部复用 `--dur-fast/base/slow` + `--ease-out` | 不新增时长令牌 |
| 入场动画 | `todo-item-in`（fadeIn+translateY）、`todo-shimmer` | 两个 keyframes，加入 App.css Todo 区块 |
| 动效降级 | `@media (prefers-reduced-motion: reduce)` 内禁用上述动画 | 与 index.css 既有约定一致 |
| 断点 | 复用 1023px（双栏→单栏、统计条换行） | 与项目既有断点一致 |

**排版层级**：统计数字 `--fs-md --fw-semi`；统计标签 `--fs-xs` secondary；分组头 `--fs-xs`；卡片内容 `--fs-sm`。

---

## 5. i18n 新增键（en / zh-CN）

| 键 | en | zh-CN |
|---|---|---|
| `todo.all` | All | 全部 |
| `todo.active` | Active | 未完成 |
| `todo.done` | Done | 已完成 |
| `todo.remaining` | pending | 待办 |
| `todo.doneCount` | completed | 已完成 |
| `todo.noteCount` | notes | 随手记 |
| `todo.progress` | Completion progress | 完成进度 |
| `todo.noActive` | All done! | 全部完成！ |
| `todo.noCompleted` | Nothing completed yet | 还没有已完成项 |
| `todo.today` | Today | 今天 |
| `todo.yesterday` | Yesterday | 昨天 |

现有 `todo.*` 键全部保留不改动（测试断言依赖英文文案：'Todo List'、'Add a new task…' 等）。

---

## 6. 测试影响与新增用例

**必须保持不破**（现有 TodoPage.test.tsx 14 个用例）：
- 所有 `data-testid`（todo-item/todo-note/note-delete/todo-page/面板/loading/error/disabled）
- checkbox 的 role 与 aria-label（按条目文本定位）
- 默认渲染 = 全部筛选，现有条目渲染断言不变
- 按钮文案 'Edit'/'Delete' 在编辑/删除按钮上——注意：行内操作改为纯图标后，'Edit'/'Delete' 文案移到 `aria-label`/`title`，**测试需同步改为 `getByLabelText`/`getByTitle` 或保留一个可见文案锚点**——实现时二选一并更新测试，保持断言强度

**新增用例（至少）**：
1. 统计头计算：2 条待办（1 完成）+ 3 笔记 → 显示 `1 待办 / 1 已完成 / 3 随手记`，progressbar `aria-valuenow=50`
2. 筛选切换：点"未完成"→ 已完成项不渲染；点"已完成"→ 反之；计数徽标正确
3. 筛选空态：全部完成时点"未完成"→ 出现 noActive 文案
4. 日期分组：两条笔记（今天 + 昨天时间戳）→ 渲染 Today/Yesterday 两个分组头
5. 加载骨架：loading 期间渲染 `.todo-skeleton`

---

## 7. 交接目标与验收标准

**实现目标**：本仓库前端工程流（React 19 + Vite + TypeScript + 自定义 CSS 令牌体系——**非 Tailwind**，技能表中的 `react-vite-tailwind-engineer` 在此对应为本项目前端实现代理）。建议继续走 superpowers 流水线（TDD + 双审查），分支 `feat/todo-ui-redesign`（从 main 切出，待 PR #9 合并后）。

**改动文件预估**：`TodoPage.tsx`（重构组件树）、`TodoPage.test.tsx`（适配+新增）、`App.css` Todo 区块（重写）、两个 locale JSON。**不动**后端、api/todo.ts、Header/App 导航。

### 验收标准

- [ ] 统计头数字与进度条与列表数据实时一致（含写操作后）
- [ ] 三档筛选切换即时、无请求，筛选空态文案正确
- [ ] 随手记按 今天/昨天/日期 分组，组内顺序新在上
- [ ] 行内操作按钮默认隐藏，悬停/键盘聚焦可见且可操作（`:focus-within` 生效）
- [ ] 三主题（dark/light/warm）下无硬编码色、对比度正常
- [ ] `prefers-reduced-motion` 下所有动画禁用
- [ ] ≤1023px 单栏堆叠、统计条换行正常
- [ ] 现有测试适配后全绿 + 新增用例通过；`npm run test/lint/build` 全绿
- [ ] 完成后按记忆规则同步更新 README（如界面描述有变化）
