# 轨迹工具调用组合卡片 — 设计交付

- 日期：2026-08-22
- 技能：frontend-design-ui-ux（设计规格，不含实现）
- 状态：已评审并实施（2026-08-22，feat/trajectory-page PR #15）
- 影响面：`frontend/src/components/Trajectory/TrajectoryPage.tsx`（EventBlock/ToolCallCard）、`frontend/src/components/Trajectory/trajectoryDisplay.ts`（分组纯函数）、`frontend/src/App.css`（轨迹段）、i18n zh/en、测试

## 1. 用户与上下文

**用户**：Thumbelina WEB 的运维/审计者，在轨迹页逐轮回溯工具调用链路。当前 tool_call 与 tool_result 是两条独立事件块，中间隔着时间戳与其它事件，审计时需自行"对上号"，低效且易错。

**产品约束**（沿用已有约定，全部必须保留）：
- 主题令牌驱动、零硬编码色值（同视觉重构规格）
- 所有信息块可点击打开详情弹窗；长文本首尾折叠；时间线布局不变
- 轨迹事件形状（已核实）：`tool_call.payload = { tool, args, call_id }`；`tool_result.payload = { call_id, content, is_error }`
- 配对**只在同一轮次内**进行（跨轮次不配对），不引入后端改动

**设计方向**：把同 `call_id` 的调用与结果合并为一张工具卡片，保持时间线手感；未匹配的调用/结果退回现有单事件块。

**Design Read**：审计流水卡。工具卡片是"调用+结果"的复合记录，样式沿现有芯片卡体系，通过分区与分隔线表达"请求→结果"的因果，错误结果维持红条语义。
**Dial**：`VARIANCE 3`（沿现有视觉体系，不引入新造型语言）· `MOTION 2`（仅 hover/focus）· `DENSITY 5`（审计密度不变，卡片内不增加视觉噪音）。

## 2. 流程与状态

交互主流程不变（滚动加载 → 点击事件入弹窗）；仅事件块的组织方式变化。

**配对规则（唯一分支点）**：
1. 遍历轮次内事件，取 `tool_call.call_id`（非空）为键。
2. 在**同一轮次**内收集 `tool_result`（`call_id` 相同且非空）作为该调用的结果；一个调用认领其全部匹配结果（防多结果场景）。
3. 已认领的 `tool_result` 不再单独渲染。
4. 未被认领的 `tool_call`（无匹配结果）→ 单独展示，卡片上追加"无匹配结果"小字提示。
5. 未被认领的 `tool_result`（无匹配调用，或 `call_id` 为空）→ 保持现有单事件块单独展示。
6. 组合卡片出现在原 `tool_call` 的位置，保持时间线顺序一致。

**状态矩阵**：

| 场景 | 视觉 |
|---|---|
| 调用 + 1 个结果 | 组合卡片：请求区 + 结果区（单行） |
| 调用 + 多结果 | 组合卡片：请求区 + 结果区多行 |
| 调用无结果（孤儿） | 单事件块（现 tool_call 芯片）+ 尾部"无匹配结果"小字 |
| 结果无调用（孤儿） | 单事件块（现 tool_result 芯片，形状不变） |
| call_id 为空 | 不配对，各自单独展示 |
| 结果 is_error | 结果区沿用红条语义（错误底 + 左侧 error 竖条） |

## 3. 组件规格

### 3.1 groupToolEvents（纯函数，可测）

- 位置：`trajectoryDisplay.ts`（与 `collapseMiddle` 同文件，绕开 react-refresh 规则）
- 签名：

```typescript
export interface ToolCallGroup {
  call: TrajectoryEvent
  results: TrajectoryEvent[] // 空数组 = 无匹配结果
}

export function groupToolEvents(
  events: TrajectoryEvent[],
): (TrajectoryEvent | ToolCallGroup)[]
```

- 语义：输入轮次事件数组，输出保持原顺序的块列表；匹配结果被消费进 `ToolCallGroup`，未匹配事件原样透出。不改动传入数组。

### 3.2 ToolCallCard（组合卡片）

```
┌──────────────────────────────────────────────┐
│ [Wrench] 工具调用: search        args 摘要 … 查看详情 │ ← 请求区（button，data-testid="turn-event"）
│ ───────────────────────────────────────────── │
│ [Terminal] 结果A …  查看详情                    │ ← 结果区（button，data-testid="turn-event"）
└──────────────────────────────────────────────┘
```

- 外层容器：`div.tool-call-card`（不可点），内嵌**两个独立按钮分区**（避免嵌套 button 的可访问性问题）。
- 请求区：`[Wrench] 工具调用: name`（label）+ `args JSON 摘要`（单行省略）+ `查看详情`；点击 → 打开 `tool_call` 详情弹窗（现有事件弹窗，不改）。
- 结果区（每次结果一行）：`[Terminal|CircleAlert] 内容摘要`（长文 `collapseMiddle(120,60,40)`）；`is_error` → 行内红条（`--error-muted` 底 + 左侧 inset `--error` 竖条）；点击 → 打开 `tool_result` 详情弹窗。
- 请求区与结果区之间：`1px var(--border-subtle)` 分隔线。
- 空结果：不渲染结果区；请求区尾部追加 `无匹配结果` 小字（`--text-secondary`，i18n `trajectory.noMatchingResult`）。
- hover：分区底部上浮 `--shadow-sm` + `--bg-hover`；active `scale(0.995)`；focus-visible `--focus-ring`。全部沿用现有 chip 交互。
- 移动端：卡片全宽，无额外收窄逻辑（与现 chip 一致）。

### 3.3 EventBlock 调整

- `TurnTrack` 渲染前先 `groupToolEvents(turn.events)`；`ToolCallGroup` → `ToolCallCard`，其余 → 现有 `EventBlock`。
- 孤儿 tool_call / tool_result 复用现有 chip 渲染路径，仅孤儿 tool_call 增加"无匹配结果"小字。

## 4. 设计令牌

无新增令牌，全部沿用视觉重构规格：

| 角色 | 令牌 |
|---|---|
| 卡片底/边 | `--bg-surface` / `--border-subtle` |
| 分隔线 | `--border-subtle` |
| 错误结果 | `--error-muted` 底 + inset `--error` 竖条 |
| 图标 | `--text-secondary`；错误态 `--error` |
| 次要文本/小字 | `--text-secondary` |
| hover 阴影 | `--shadow-sm` |
| 焦点环 | `--focus-ring` |
| 动效 | `--dur-fast` + `--ease-out` |

规则：形状复用 `--radius`（卡片）与 `--radius-sm`（分区 hover 背景）；**零硬编码色值**。

## 5. 交接目标与验收标准

**实现目标**：纯 SPA React + Vite + 项目原生 CSS；只动前端（`Trajectory/*` + `App.css` 轨迹段 + i18n），无后端改动。建议在 `feat/trajectory-page`（PR #15）继续 follow-up 提交。

**工程验收（可测）**：
- [ ] `groupToolEvents` 单测覆盖：正常配对、调用无结果、结果无调用、多结果、call_id 为空、输入顺序保留
- [ ] 组合卡片内请求区/结果区分区可见、点击分别打开对应详情弹窗（组件测试）
- [ ] 孤儿调用展示"无匹配结果"小字；孤儿结果保持原样
- [ ] 时间线布局、无限加载、折叠、弹窗等交互契约不回归；轨迹段样式零硬编码色值
- [ ] i18n zh/en 双语同步（新增 `trajectory.noMatchingResult`）
- [ ] `npm run lint`、`npm run build`、全量 `npm test` 通过