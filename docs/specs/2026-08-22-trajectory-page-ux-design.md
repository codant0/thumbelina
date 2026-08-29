# 轨迹页信息展示优化 — UX 设计交付

- 日期：2026-08-22
- 技能：frontend-design-ui-ux（设计规格，不含实现）
- 目标代码：`frontend/src/components/Trajectory/TrajectoryPage.tsx`（现有实现）+ 新组件

## 1. 用户与上下文

**用户**：需要审计/回溯历史对话的 Thumbelina WEB 用户（运维排查、效果复盘、机制验证）。单用户本地应用，桌面浏览器为主，可能手机浏览器查看。

**产品目标**：让用户在“轨迹”页快速定位某轮次的关键信息，长内容不被截断焦虑、短内容不被弹窗打断；大量轮次时浏览体验顺滑。

**现状问题**（用户反馈 + 代码审查）：
- 长助手回复/工具结果在卡片内全量渲染，页面被撑得很长（TrajectoryPage.tsx:148/156 `event-content` 无限长）。
- 技术事件展开后 `<pre>` 内 JSON 一次性全显（:183），长 JSON 可读性差。
- 所有信息（含文本消息）无法单独“查看详情”，只能整行展开/收起。
- 轮次多时依赖底部“加载更多”按钮（:113-123），无滚动自动加载；页面级滚动导致选择器/标题滚出视野。
- 已知 deferred minor：`load()` 无请求序号守卫，快速切会话时晚响应可覆盖视图（:27-51）——本次一并纳入。

**已确认设计目标**：
1. 长文本首尾折叠（头尾各保留约 200 字，中间折叠，点击进弹窗看全文）。
2. 所有信息支持点击弹窗查看详细内容（含原始 JSON）。
3. 轨迹多时列表容器内滚动，滚动到底自动加载下一页（保留“加载更多”按钮作无障碍兜底）。

## 2. 流程与状态

### 流程：浏览与审计单轮次详情

**User Story**：作为管理员/使用者，我想在轨迹页滚动浏览各轮次、点开某条消息或工具调用看完整内容，以便审计该会话发生过什么。

**Trigger**：顶部导航“轨迹”或聊天页“查看轨迹”按钮进入；选择会话后浏览。

**主流程**：
```
[进入页面 → 默认空态]
    │ 选择会话
    ▼
[列表容器内滚动（倒序轮次卡片）]
    │ 滚到底 / 点“加载更多”
    ▼
[自动加载下一页（追加渲染）]
    │ 点击任意信息行 / 轮次头
    ▼
[详情弹窗 → 查看全文 / JSON → 关闭（Esc/遮罩/按钮）]
```

**状态模型**（现有状态 + 新增）：

| 状态 | 现有实现 | 本次调整 |
|---|---|---|
| 未选择会话 | `trajectory-empty`（“请选择要查看的会话”） | 不变 |
| 会话被删除(404) | `notFound` → 空态文案“会话不存在” | 不变 |
| 首载/换会话加载 | 无 loading 提示（deferred minor） | 列表顶部显示轻量“加载中…”占位（骨架/文案） |
| 加载失败 | `trajectory-error` + 重试 | 不变 |
| 部分数据（可继续加载） | 底部“加载更多”按钮 | 按钮保留 + 进入视口自动触发（无限滚动互补） |
| 全部加载完 | 按钮隐藏 | 按钮隐藏，底部显示“已加载全部 N 轮”灰字（可选） |
| 弹窗打开 | 无 | 列表禁止背景滚动（body overflow lock），关闭后恢复 |
| 慢响应竞态 | 无守卫（deferred minor） | `load()` 增加 request-seq：仅最新请求可写状态 |

**分支点**：
- 切换会话 → 重置 `page=1`、清空 `expanded`、关闭弹窗、清空列表容器滚动位置（scrollTop=0）。
- 加载中再次触发加载 → 忽略（`loading` + seq 守卫双保险）。
- 弹窗打开时点击另一行 → 直接切换弹窗内容（不要求先关闭）。

**错误/边界**：
- payload 缺失字段（如无 `content`）→ 弹窗按字段存在性渲染，缺失字段显示 `—`。
- payload 非对象（`raw` 降级）→ 弹窗仅显示 JSON/pre 文本。
- 极长文本（>100K 字符）→ 弹窗正文限高滚动；卡片预览仅头尾 200 字。
- 空事件轮次 → 轮次卡片仍显示头部 + “无事件”灰字。

## 3. 组件规格

### Component: TrajectoryDetailModal

#### Purpose
展示单条轨迹信息的完整详情（全文或原始 JSON），从任意信息行/轮次头进入。

#### Props

```typescript
interface TrajectoryDetailModalProps {
  /** 当前展示目标；null 表示关闭 */
  target: TrajectoryDetail | null;
  onClose: () => void;
}

interface TrajectoryDetail {
  kind: 'event' | 'turn-meta';
  /** kind='event'：事件来源轮次 + 事件 */
  turnId?: string;
  event?:
    | { seq: number; event_type: 'user' | 'assistant'; payload: Record<string, unknown>; created_at: string }
    | { seq: number; event_type: 'context' | 'tool_call' | 'tool_result'; payload: Record<string, unknown>; created_at: string };
  /** kind='turn-meta'：轮次头信息 */
  turnMeta?: { turn_id: string; started_at: string; eventCount: number };
}
```

#### 变体（按 event_type）
- `user` / `assistant`：标题=角色徽标+时间；正文=全文（`pre-wrap`，限高滚动）。
- `context`：标题=上下文；正文=items 列表（kind → content），展开“原始 JSON”。
- `tool_call`：标题=工具调用: {tool}；字段区 tool/call_id/args（args 为 JSON 块），展开“原始 JSON”。
- `tool_result`：标题=工具结果；错误时（is_error）标题含❌/红色边框；content 全文；展开“原始 JSON”。
- `turn-meta`：标题=轮次信息 #N；字段 turn_id/started_at/事件数；仅元数据，不展开到各事件。

#### States

| State | Visual | Behavior |
|---|---|---|
| Closed | 不渲染（或 unmount） | `target=null` |
| Open | 遮罩 + 居中卡片（宽 min(720px, 92vw)） | focus 移入卡片，aria-modal |
| Loading（无需） | — | 数据已在内存，无异步 |
| Error（无需） | — | 数据已在内存，无异步 |

#### Accessibility
- Role: `dialog`；`aria-modal="true"`；`aria-labelledby` = 标题文本 id。
- Focus：打开时 focus 关闭按钮；Tab/Shift+Tab 在卡片内循环（focus trap）；Esc 关闭；关闭后焦点返回触发元素。
- `aria-label`：关闭按钮 = i18n `trajectory.closeDetail`。
- 正文滚动区 `tabIndex=0` 以便键盘滚动。

#### Keyboard
| Key | Action |
|---|---|
| Tab | 卡片内循环 |
| Escape | 关闭 |
| Enter/Space | 触发行打开弹窗（行本身是 button） |

#### Responsive
| Breakpoint | Behavior |
|---|---|
| <640px | 弹窗近全屏（`width 100vw; height 100dvh; border-radius 0`）；列表容器限高降低 |
| ≥640px | 居中卡片，max-height 80vh 内部滚动 |

#### Edge Cases
| Scenario | Handling |
|---|---|
| 长文本 | 正文限高（`max-height: 60vh; overflow: auto`），不截断 |
| raw 降级 | 仅 JSON pre |
| 连续快开关弹窗 | 由 React 状态驱动，无队列问题 |
| body 滚动锁 | 打开时 `document.body.style.overflow = 'hidden'`，关闭还原 |

#### Dependencies
- 无新库（自写；如仓库已有 dialog 惯例则复用）。
- i18n keys 新增（zh/en 同步）：`trajectory.closeDetail`、`trajectory.originalJson`、`trajectory.viewDetails`、`trajectory.eventCount`、`trajectory.noEvents`、`trajectory.loadedAll`、`trajectory.collapsedChars`、`trajectory.loadingInitial`。

#### Implementation Notes
- 文件：`frontend/src/components/Trajectory/TrajectoryDetailModal.tsx`。
- 复用 `event-badge`/`event-error` 现有样式；新增 `.modal-*` 一组。
- 无动画或仅 150ms fade（保持一致）。

---

### Component: TrajectoryEventRow（信息行 · 可点击）

#### Purpose
卡片内单条轨迹信息的可点击行：短内容直接展示；长内容首尾折叠；点击打开弹窗。

#### Props

```typescript
interface TrajectoryEventRowProps {
  turnId: string;
  event: TrajectoryEvent;
  /** 打开详情弹窗 */
  onOpenDetail: (target: TrajectoryDetail) => void;
}
```

#### 行为规则
- 渲染为 `<button type="button" class="turn-event event-row">`（整行可点；可访问）。
- `user/assistant`：徽标 + 文本预览（≤600 字符全显；>600 字符首 200 + “…共 N 字…” + 尾 200，加 `viewDetails` 提示）。
- `context/tool_call/tool_result`：展开/收起交互**移除**（原 `event-toggle`），改为整行点击进弹窗；行内预览 = 1 行摘要（如 `上下文 · items×3`、`工具调用: search`、`工具结果: 前 120 字`）。
- 错误结果：行边框/徽标红色（沿用 `event-error`）。
- Hover：背景加深 + 右侧出现“查看详情”图标/文字提示；Focus ring 可见。

#### Accessibility
- 语义 button；`aria-label` 组合 `{类型}: {摘要}`。
- 键盘 Enter/Space 打开弹窗。

#### Implementation Notes
- 删除 `expanded` state 与 `ChevronDown/Up` 展开分支（变为弹窗式）；`event-toggle` 相关 i18n 可保留或弃用（弃用则同步删除 key）。
- 摘要计算：纯函数 `summarizeEvent(event) → {label, preview}`，便于单测。

---

### Component: TurnCard（轮次卡片 · 改）

#### 变更
- 头部（`turn-header`）整行可点击 → 打开 `turn-meta` 弹窗（轮次号+时间合一 button）。
- 事件区渲染改为 `TrajectoryEventRow[]`。
- 无状态变更，props 增 `onOpenDetail`。

---

### Component: TrajectoryList（滚动容器 + 无限加载）

#### 变更（在 TrajectoryPage 内实现，或抽组件）
- `.trajectory-list` 容器：`max-height: calc(100vh - 210px)`（标题+选择器占位），`min-height: 320px`，`overflow-y: auto`。
- 容器底部 sentinel `<div ref>` + `IntersectionObserver`（threshold 0.1）：进入视口且 `hasMore && !loading` → `load(page+1, append)`。
- 保留“加载更多”按钮（视觉与 sentinel 并列，作为 AT 兜底与手动触发）。
- `load()` 内增加 `requestSeqRef`：每次调用 `const seq = ++requestSeqRef.current`；仅 `seq === requestSeqRef.current` 时写 `setData/setError/setNotFound`。
- 切换会话/首载时 `listRef.current?.scrollTo({top: 0})`。

#### Edge Cases
| Scenario | Handling |
|---|---|
| 容器内容不足一屏 | sentinel 立即可见 → 自动加载直至满一屏或全部加载 |
| 连续快速触发 | seq + loading 双守卫；observer 断开/重连幂等 |
| 全部加载 | 停止 observer，显示“已加载全部 N 轮” |
| 加载失败 | error 区 + 重试（重试重置 seq） |

## 4. 设计令牌（本仓库为纯 CSS 变量，无 Tailwind）

仅定义本次需要、且与现有 App.css 惯例一致的令牌：

```css
/* 新增（App.css 追加） */
--z-modal: 1000;              /* 高于现有 header/固定层；实现时核对现存最高 z-index */
--color-overlay: rgba(0, 0, 0, 0.45);
--trajectory-list-maxh: calc(100vh - 210px);
--radius-modal: 10px;
--text-preview-head: 200;     /* JS 常量（折行预览头尾长度） */
--text-preview-limit: 600;    /* JS 常量（全显阈值） */
```

复用现有：`--border-color`、`--bg-input`、`event-badge` 背景 `#333`、错误色 `#c33`、`pre` 等宽/滚动（`.event-detail` 模式）、过渡 150ms。
语义色约束：遮罩不透明 ≥45%，卡片背景与页面背景一致（暗色系沿用现变量）。

## 5. 交接目标与验收标准

**实现目标**：纯 SPA React + Vite + 普通 CSS（仓库无 Tailwind），继续沿用 `frontend/` 现有模式（`useTranslation`、data-testid、Vitest）。建议在现有 `feat/trajectory-page` 分支/PR #15 上以 follow-up 提交实施，或按 superpowers 流程（brainstorm→plan→implement）新起一轮。

**工程验收（可测试）**：
- [ ] 长消息（>600 字符）卡片内仅显示头尾预览 + 折叠提示；≤600 字符全显。
- [ ] 所有事件行与轮次头均可点击打开 `TrajectoryDetailModal`；弹窗显示对应全文/字段/原始 JSON。
- [ ] 弹窗打开时背景滚动锁定；Esc/遮罩/关闭按钮均可关闭；焦点循环；关闭后焦点还原。
- [ ] 轨迹列表容器内滚动；滚到底自动加载下一页（observer），且“加载更多”按钮仍可手动触发。
- [ ] 快速切换会话时无旧响应覆盖（request-seq 生效）；切换后列表回到顶部。
- [ ] 全部加载完显示“已加载全部 N 轮”；首载显示加载提示。
- [ ] i18n zh/en 同步；新增 key 无遗漏。
- [ ] Vitest 覆盖：预览折叠、弹窗开关与内容、无限加载触发、seq 竞态、404 分支回归。
- [ ] `npm run lint`、`npm run build`、全量 `npm test` 通过；无回归。