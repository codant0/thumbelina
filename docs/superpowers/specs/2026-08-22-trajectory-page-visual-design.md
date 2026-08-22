# 轨迹页全量视觉重构 — 设计交付

- 日期：2026-08-22
- 技能：frontend-design-ui-ux（设计规格，不含实现）
- 状态：已评审并实施（2026-08-22，feat/trajectory-page PR #15）
- 目标：`frontend/src/components/Trajectory/*`（TrajectoryPage / TrajectoryDetailModal / trajectoryDisplay）+ `frontend/src/App.css`

## 1. 用户与上下文

**用户**：Thumbelina WEB 的运维/审计者，在深色为主的聊天工具中回溯某会话的完整轨迹（用户消息、助手回复、工具调用、上下文、时间）。

**产品约束**：
- 项目主题可切换（`<html data-theme="dark|light|warm">`，见 ThemeToggle），语义令牌全部定义在 `frontend/src/styles/themes.css`；重构必须**只消费现有令牌**，不引入硬编码色值，主题切换自动生效。
- 现有可复用令牌（已确认存在）：`--accent/--accent-muted/--accent-hover/--accent-border`、`--user-bubble/--user-bubble-text`、`--assistant-bubble/--assistant-bubble-text`、`--error/--error-muted`、`--success/--success-muted`、`--warning/--warning-muted`、`--code-bg/--code-text`、`--bg/--bg-surface/--bg-elevated/--bg-hover/--bg-active`、`--text/--text-primary/--text-secondary/--text-heading`、`--border/--border-subtle`、`--focus-ring`、`--shadow-sm/md/lg`、`--radius/--radius-sm/--radius-lg/--radius-full`、`--sp-*`、`--fs-*`、`--fw-*`、`--dur-*`、`--ease-*`、`--z-dropdown/--z-sticky/--z-toast/--z-modal`。
- 现有交互契约**必须保留**（用户仅要求视觉重构）：整行可点开详情弹窗、长文本首尾折叠、列表容器滚动 + 无限加载 + “加载更多”兜底、request-seq 竞态守卫、空态/404/错误/加载中状态、i18n zh/en。
- lucide-react 为项目既有图标库（沿用）。

**设计方向**（用户确认）：时间线布局；不沿用现有卡片视觉；跟随主题色。

**Design Read**：审计时间线工作台。暗色技术工具语言，时序阅读效率优先。色彩只来自现有语义令牌；强调色（--accent）用于时间轴与关键节点；角色色沿用聊天页泡泡色系（--user-bubble / --assistant-bubble），保证跨页面一致。
**Dial**：`VARIANCE 4`（时间线本身有节奏，区块以垂直导轨对齐）· `MOTION 3`（仅 hover/focus/弹窗淡入，尊重 reduced-motion）· `DENSITY 5`（审计密度，但每段事件有呼吸）。

## 2. 流程与状态

主流程不变（选择会话 → 滚动加载 → 点击事件入弹窗）；本次变更集中在**视觉呈现层**与**状态视觉**。

| 状态 | 现有 | 重构后视觉 |
|---|---|---|
| 未选择会话 | 居中灰字提示 | 居中插图式空态：细线图标（Route/ListTree）+ 主提示 + 次行说明 |
| 会话 404 | 同上文案“会话不存在” | 空态图标 + “会话不存在” + 轻描边提示 |
| 首载 | 纯文字“加载中…” | 骨架轨道（左侧竖线 + 2-3 条灰色骨架事件块，无 spinner，形状接近最终布局） |
| 加载失败 | 红框 + 重试 | 内联错误块（--error 边框 + --error-muted 底），重试按钮常规尺寸 |
| 部分数据 | 底部按钮 | 底部“加载更多”按钮（--accent 幽灵按钮）或自动加载中骨架条 |
| 全部加载 | 灰字 | “已加载全部 N 轮”小字（--text-secondary） |
| 弹窗 | 现有 modal | 内容排版升级（见 §3.4） |

**分支点**：切换会话 → 时间线回到顶部、骨架态出现；加载中重复触发 → 忽略；滚到底自动加载。全部与现有逻辑一致。

## 3. 组件规格

### 3.1 TimelineViewport（轨迹列表 · 时间线容器）

- 结构：`<div class="trajectory-list">` 内渲染 `<div class="timeline">`；左侧固定轨道列（宽 72px，含竖线与节点），右侧内容列。
- 轨道绘制方式：容器内绝对定位竖线 `left: 35px; top/bottom: 0; width: 2px; background: var(--border-subtle)`；每个事件块归属的轮次起始节点在前。
- 滚动/无限加载/加载按钮/加载完成文案沿用现有实现（`trajectory-load-more`、sentinel、`trajectory-loaded-all`）。
- 移动端（<640px）：轨道列收窄（48px），事件块全宽。

### 3.2 TurnTrack（轮次轨道）

**Props**

```typescript
interface TurnTrackProps {
  turn: TrajectoryTurn;
  turnIndex: number;
  onOpenDetail: (target: TrajectoryDetail) => void;
}
```

**结构**
```
[轨道列]  ● 节点(accent 实心圆 10px, 轮次起始)
[内容列]  ├ 头部行(可点击 button): 轮次序号(--text-heading fw-semi) + started_at(--text-secondary / mono)
          ├ EventBlock × N
          └ 无事件 → “无事件记录”小字
```

- 节点：轮次起始 = `--accent` 实心圆（直径 10px，居中于竖线）；后续轮次节点的竖线自然延续。错误轮次（任一 tool_result is_error）节点切换为 `--error`。
- 头部行：整行 button（延续现有 turn-header-btn 语义），hover 背景 `--bg-hover`，focus 用 `--focus-ring`。
- 轮次序号与时间列宽对齐：`--fs-sm`/mono 时间，供快速扫描。

### 3.3 EventBlock（事件块）

| 事件 | 块样式 | 交互 |
|---|---|---|
| user | 气泡块：`--user-bubble` 底 + `--user-bubble-text` 文本，圆角 `--radius-lg`，最大宽度 78% 靠左 | 整块 button 可点开弹窗 |
| assistant | `--assistant-bubble` 底 + `--assistant-bubble-text`，圆角 `--radius-lg`，与 user 左右错开（user 左 / assistant 右，气泡式对话感） | 整块 button |
| context | 芯片卡：`--bg-surface` + `--border-subtle` 细边，mono 图标（Boxes/Braces）+ `上下文（N 项）`，摘要单行 | button |
| tool_call | 芯片卡：mono 图标（Wrench）+ `工具调用: name` + args 摘要单行 | button |
| tool_result | 芯片卡：mono 图标（Terminal/Check）；`is_error` → 左侧 `--error` 竖条 + `--error-muted` 底 | button |
| long text | 首尾折叠沿用 `collapseMiddle`；截断时块内尾部追加 `查看详情`（--accent，小字） | — |

- 角色徽标：气泡块本身已表达角色，不再叠加 badge；芯片卡顶部保留小标签（--fs-xs，--text-secondary）。
- hover：全部 button 上浮 1px 阴影（`--shadow-sm`）+ `--bg-hover`；active 微缩（scale 0.995）。
- 焦点：`--focus-ring` 2px + offset 1px（统一）。

### 3.4 TrajectoryDetailModal（弹窗内容排版）

- 容器：复用 `.modal/.modal-overlay/.modal__header/.modal__body`（现有令牌与动画不动）。
- 消息类：正文区块与气泡同色系轻染色；长文保持 pre-wrap 全显。
- 技术类：字段使用 `.trajectory-fields` 的 dl 布局；args/JSON 用 `--code-bg/--code-text` 代码块（等宽、max-height 45vh 滚动）；“原始 JSON”开关按钮为幽灵按钮（--accent 文字或边框）。
- 轮次信息：dl 布局 + 事件计数徽标（--bg-active 底 + --text-secondary）。
- 关闭/焦点/Esc/遮罩逻辑沿用。

## 4. 设计令牌（全部映射现有主题令牌）

| 角色 | 令牌 |
|---|---|
| 时间轴竖线 | `--border-subtle` |
| 轮次起始节点 | `--accent`；错误轮次 `--error` |
| 用户消息块 | `--user-bubble` / `--user-bubble-text` |
| 助手消息块 | `--assistant-bubble` / `--assistant-bubble-text` |
| 芯片卡底/边 | `--bg-surface` / `--border-subtle` |
| 错误结果 | `--error` / `--error-muted` |
| 代码块 | `--code-bg` / `--code-text` |
| 次要文本/时间 | `--text-secondary` |
| 焦点环 | `--focus-ring` |
| 阴影（hover/弹窗） | `--shadow-sm` / `--shadow-lg`（弹窗沿用） |
| 动效 | `--dur-fast`/`--dur-base` + `--ease-out` |

规则：
- **零硬编码色值**；`--bg-surface/--bg-elevated` 用于芯片卡；骨架块用 `--bg-hover` 系。
- 形状锁：消息块 `--radius-lg`，芯片卡 `--radius`，节点/按钮全圆 `--radius-full`。
- 主题切换：直接经 `[data-theme]` 的令牌切换生效，无额外代码。
- 深/浅/暖三主题下均需满足 WCAG AA（现有令牌已保证主要文字对比；实施时核对气泡文字对比）。

## 5. 交接目标与验收标准

**实现目标**：纯 SPA React + Vite + 项目原生 CSS（无 Tailwind），复用 `styles/themes.css` 令牌；实现面仅 `Trajectory*/**` + `App.css` 轨迹段 + i18n 微调。
**建议路径**：在 `feat/trajectory-page` 分支（PR #15）继续 follow-up 提交；或另行子代理回合。

**工程验收（可测）**：
- [ ] 时间线布局：竖线 + 节点 + 左右内容列在深/浅/暖三主题下渲染正确；轮次节点随主题强调色变化
- [ ] 事件块按表 3.3 分色；user/assistant 气泡左右错开；错误结果红竖条
- [ ] 全部交互契约保留：整行/整块可点开弹窗、长文本首尾折叠、“加载更多”+ 自动加载、便捷 seq 守卫、空态/404/错误/首载骨架态
- [ ] 无硬编码色值（grep 无 #hex/rgb() 于轨迹段样式；骨架/阴影/代码块全走令牌）
- [ ] 焦点环 `--focus-ring`、reduced-motion 下无多余动效；`npm run lint`、`npm run build`、全量 `npm test` 通过
- [ ] i18n zh/en 无新增遗漏（新增文案如“已加载全部”、“无事件记录”已存在，其余若加则双语同步）