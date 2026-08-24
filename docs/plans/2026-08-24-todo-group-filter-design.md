# 待办分组过滤卡片设计交接

- **日期**：2026-08-24
- **状态**：已确认（用户决策）
- **相关代码**：`frontend/src/components/Todo/TodoPage.tsx`、`frontend/src/App.css`、`frontend/src/i18n/locales/{zh-CN,en}.json`
- **基于**：待办/随手记已支持 Markdown 一级标题分组（`TodoItem.group` / `TodoNote.group` 字段）

## 1. 用户与上下文总结

**目标用户**：使用待办页记录 TODO 与随手记的用户，习惯用 Markdown `# 标题` 手工分类（工作/学习/生活…）。

**产品目标**：让用户能快速聚焦某一分组，而不是长期面对全部分组的混合列表。

**已确认决策**：
1. 分组过滤卡片应用到 **待办清单与随手记两个面板**（交互一致）
2. 分组卡片形态：**卡片式带计数**（图标 + 组名 + 数量徽标）
3. 分组列表**只显示有内容的分组**：从条目数据派生（`group` 字段），空组不出现；「未分组」单独一张卡片；**无需改后端**
4. 默认选中「全部」→ 保持现有的按分组分块展示（组头 + 条目）

**约束**：不修改后端解析/API；复用现有 `groupByHeading`、`TodoFilter`、BEM 类名与设计令牌。

## 2. 流程与状态

### 主流程
```
打开待办页（两个面板）
   │
   ▼
分组卡片栏渲染：全部(默认选中) | 未分组 | 工作 | 学习 …
   │
   ├─ 保持默认「全部」──▶ 列表按分组分块展示（组头 + 条目）
   │
   └─ 点击某分组卡片 ──▶ 视图聚焦：
        · 标题组：只显示该组条目（组内随手记仍按天分组）
        · 未分组：只显示 group 为空的条目
        · 全部：恢复分块视图
   │
   └─ 与现有「全部/未完成/已完成」状态过滤叠加（AND）
```

### 状态
| 状态 | 表现 | 说明 |
|------|------|------|
| Loading | 骨架屏（现状不变） | 分组卡片不渲染 |
| 空数据 | 现有空态（暂未待办/暂无随手记） | 卡片栏隐藏 |
| 全部选中（默认） | 分块视图 + 各组组头 | 现行为 |
| 选中标题组 | 单组视图，无外层组头（组内随手记保留天组头） | 避免重复标题 |
| 分组 × 状态过滤后为空 | 显示现有空态文案（如「全部完成！」） | 卡片仍显示该组 |
| 点击状态过滤标签 | 卡片栏不变，内容联动 | 两个过滤 AND |

### 边角情况
| 场景 | 处理 |
|------|------|
| 只有未分组条目 | 卡片栏仅「全部」+「未分组」两张 |
| 只有一个分组（无未分组） | 卡片栏「全部」+ 该组 |
| 分组名很长 | 卡片内省略（`text-overflow: ellipsis`），`title` 全名 |
| 点击「全部」后 | 恢复分块视图，滚动位置留在顶部 |
| 分组计数为 0（如已完成过滤后） | 卡片仍显示，计数随可见范围内内容更新（详见派生规则） |

## 3. 组件规范

### 3.1 组件：`TodoGroupFilter`

分组过滤卡片栏，单选。（缩进为 BEM：`.todo-group-filter`、`.todo-group-filter__card` 等）

#### 用途
在待办/随手记面板顶部展示可用分组，供用户单选取聚焦视图。

#### Props
```typescript
interface TodoGroupFilterOption {
  /** 分组键：'' 表示全部；'__ungrouped__' 表示未分组；其余为标题文本 */
  key: string
  label: string
  count: number
}

interface TodoGroupFilterProps {
  options: TodoGroupFilterOption[]
  /** 当前选中键，'' = 全部 */
  selected: string
  onSelect: (key: string) => void
  /** 面板类型，决定图标（待办=ClipboardList / 随手记=StickyNote） */
  kind: 'items' | 'notes'
  disabled?: boolean
}
```

#### 派生函数（模块级纯函数，便于单测）
```typescript
/** 从条目/随手记派生过滤选项：全部(总数) → 未分组 → 各组（按首次出现顺序）。
 *  空组不出现；count 为当前可见列表（已过状态过滤）内该组条目数。 */
function groupFilterOptions<T extends { group?: string | null }>(
  list: T[], kind: 'items' | 'notes',
): TodoGroupFilterOption[]
```
- `全部.count = list.length`（与现有状态过滤后的可见数量一致）
- `未分组` 存在且 count>0 时出现；`list` 中无未分组条目则不出现
- 标题组按 `list` 中首次出现顺序排列
- 需要新增 i18n 键 `todo.allGroups`（中文「全部」已存在 `todo.all`，可复用；若列表中同时有状态过滤「全部」，卡片栏直接复用 dot 分隔，候选文案「全部」）；skill 交付前工程侧确认识别冲突

#### 状态
| State | Visual | Behavior |
|-------|--------|----------|
| Default | 浅色卡片：`--bg-elevated`，1px `--border-subtle`，圆角 `--radius` | 可点击 |
| Hover | 描边加深为 `--border`，微上浮 `translateY(-1px)` | 轻微反馈 |
| Focus | `--focus-ring` | Tab 可达，`aria-pressed` 同步 |
| Selected | 1.5px `--accent-secondary` 描边 + `--accent-secondary-muted` 淡底；计数徽标橙色实底白字 | 视图聚焦该组 |
| Disabled（`disabled`） | 降透明度 | 不响应点击（本次无实际禁用场景，保留 prop 以复用） |

#### 布局
- 容器：flex，`flex-wrap: nowrap`（**固定单行**），`gap: var(--sp-2)`，`overflow-x: auto` + `overscroll-behavior-x: contain` + 隐藏滚动条（`scrollbar-width: none` / `::-webkit-scrollbar { display: none }`）；上下 `padding: 2px`（防 focus 环被 overflow 裁剪）+ 负 margin 抵消
- 卡片：**固定 `height: 30px`** + `flex-shrink: 0`。理由：Chromium 在 `overflow-x: auto` 的 flex 行中，内容溢出时会错误拉伸卡片交叉轴高度（实测 44–68px，且随卡片数量变化），导致待办/随手记两面板卡片栏高度不一致；固定高度 + 单行滚动保证两面板高度恒等（34px）
- 卡片内容：`display: flex; align-items: center; gap: var(--sp-2)`；左侧图标 14px，中间组名 `--fs-sm`，右侧计数徽标（圆形 pill，`height: 20px`，最小宽 20px，`--fs-xs`）
- 「全部」卡片图标使用面板图标（ClipboardList / StickyNote）；未分组用 Inbox；标题组无图标（避免图标语义噪音）

#### 响应式
| 断点 | 行为 |
|------|------|
| 桌面/平板 | 固定单行；分组多时横向滚动（隐藏滚动条，触摸板/Shift+滚轮可滑） |
| 移动 (<640px) | 同上：单行 + 横向滚动；面板为上下堆叠时两栏各自保持 34px 高，高度仍一致 |

#### 无障碍
- 角色：按钮组，每张卡片为 `<button type="button">` + `aria-pressed={selected === key}`（与现有 `todo-filter-tabs__tab` 模式一致）
- 键盘：Tab 依次聚焦；Enter / Space 激活
- 屏幕阅读器：朗读卡片文本（图标 `aria-hidden`）+ 选中状态（`aria-pressed` 变更由浏览器自动播报安全）；计数徽标并入卡片文本，不单独立 aria
- 焦点管理：点击卡片后焦点停留在卡片本身（单选过滤不移动焦点）

#### 动画
| 触发 | 动画 | 时长 | 缓动 |
|------|------|------|------|
| 卡片状态 change | 描边/底色过渡 | 120ms | `--ease-out` |
| 列表切换分组 | 复用现有 `todo-item-in` 轻入 | 180ms | `--ease-out` |

#### 组成/插槽
- 无复合组件；`options` 由父组件派生后传入

#### 依赖
- lucide-react 图标：`ClipboardList`、`StickyNote`（页面已引入）
- 复用现有：`groupByHeading`、`TodoFilter`（状态过滤标签不变）
- 无新依赖

#### 实现要点
- **过滤叠加**：现有 `TodoListPanel` 收到 `items=visibleItems`（状态过滤后）。分组过滤在面板内部应用：`const shown = selected === '' ? items : items.filter(i => (i.group ?? '') === (selected === '__ungrouped__' ? '' : selected))`。`groupFilterOptions` 的输入是 `items`（可见列表），因此卡片计数始终与内容一致
- **随手记面板**：分组过滤后，组内仍走 `groupNotesByDay`（保持「今天/昨天/日期」天组头）
- **选中标题组时**：不渲染外层「组头」块（`todo-group-header`），直接渲染组内条目；选中「全部」时保持现有分块渲染——实现时对现有 `groupByHeading(...).map(...)` 分支：`selected===''` 走现有分块，否则取出对应组后平铺渲染
- **空态**：`shown.length === 0` 时复用各面板现有空态逻辑（不新增文案）
- **测试**：`TodoPage.test.tsx` 新增——选项派生（全部计数、未分组置前、空组不出现）、点击卡片过滤、与状态过滤叠加、选中后组头隐藏、返回「全部」恢复分块；同时保留现有测试（`todo-group-header`、`note-group-header` testid 仅在「全部」视图出现，需同步更新断言时注意两个面板同 testid 的问题——沿用 `within(panel)` 限定）

## 4. 设计令牌与样式规则

仅新增一个组件样式块（App.css，紧邻 `.todo-filter-tabs` 附近，遵循 BEM 与现有 todo 风格）：

```css
/* 分组过滤卡片栏 */
.todo-group-filter { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-bottom: var(--sp-3); }
.todo-group-filter__card {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-3);
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}
.todo-group-filter__card:hover { border-color: var(--border); }
.todo-group-filter__card:focus-visible { box-shadow: var(--focus-ring); }
.todo-group-filter__card--selected {
  border: 1px solid var(--accent-secondary-border);
  background: var(--accent-secondary-muted);
  color: var(--accent-secondary);
  font-weight: var(--fw-med);
}
.todo-group-filter__badge {
  min-width: 20px; height: 20px; padding: 0 5px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: var(--radius-full);
  background: var(--bg);
  color: var(--text-secondary);
  font-size: var(--fs-xs);
}
.todo-group-filter__card--selected .todo-group-filter__badge {
  background: var(--accent-secondary);
  color: var(--bg-surface);
}
```

说明：
- 「全部」卡片复用 `todo.all` 文案（zh「全部」/ en「All」已存在）；「未分组」复用既有 `todo.ungrouped`（zh「未分组」/ en「Ungrouped」），无需新增 i18n
- 选中态使用橙色 `--accent-secondary` 系（todo 的「随手记」图标 StickyNote 亦用橙色，视觉同源）；teal `--accent` 保留给状态过滤标签（全部/未完成/已完成），避免两个过滤层级同色混淆
- 字体：组名 `--fs-sm`，badge `--fs-xs`

## 5. 工程交接

**Implementation Target**：`react-vite-tailwind-engineer`（本项目为 React + Vite + 原生 CSS/BEM，Tailwind 不适用，工程按现有 App.css 约定实现）

**文件清单**
- 修改 `frontend/src/components/Todo/TodoPage.tsx`：新增 `TodoGroupFilter` 组件 + `groupFilterOptions` 纯函数；`TodoListPanel` / `TodoNotesPanel` 接入分组过滤状态（各自本地 state 或提升到页面，二选一——建议面板本地 `useState` 初始 `''`，两个面板独立）
- 修改 `frontend/src/App.css`：新增上述样式块
- 修改 `frontend/src/components/Todo/TodoPage.test.tsx`：新增选项派生、过滤交互、叠加、组头隐藏、恢复「全部」用例；适配现有断言（用 `within(panel)`）
- i18n：**无需新增键**（复用 `todo.all`、`todo.ungrouped`）；若实现选择给「全部」卡片加差异文案，则补 `todo.allGroups`（zh「全部」/ en「All」），二选一

**验收标准**
- [ ] 两个面板顶部出现分组卡片：全部（默认选中）+ 未分组 + 各标题组，带数量徽标
- [ ] 分组列表从可见条目派生：空组不出现，未分组置前，计数与内容一致
- [ ] 默认「全部」时保持按分组分块展示（现有 UI 不变）
- [ ] 点击卡片：视图聚焦该组（标题组无外层组头；随手记组内按天）；再次点「全部」恢复分块
- [ ] 与「全部/未完成/已完成」状态过滤叠加正确（AND）
- [ ] 过滤后为空显示现有空态，不新增错误
- [ ] 键盘 Tab / Enter / Space 可用；`aria-pressed` 正确；图标 `aria-hidden`
- [ ] 窄屏卡片 wrap 可读，长组名省略 + `title` 提示
- [ ] 动画使用现有轻入/过渡 token
- [ ] 新增测试通过，全量 `vitest`、`tsc -b`、`eslint` 绿