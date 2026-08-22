# 状态栏栏目视觉区分 — 设计交付

- 日期：2026-08-22
- 技能：frontend-design-ui-ux（设计规格，不含实现）
- 状态：已评审并实施（2026-08-22，feat/trajectory-page PR #15）
- 影响面：`frontend/src/components/StatusBar/*`（StatusBarItem 协议 / ContextUsageItem / CacheHitRateItem / StatusBar）、`frontend/src/components/Chat/ChatWindow.tsx`、`frontend/src/App.css`（statusbar 段）

## 1. 用户与上下文

**用户**：Thumbelina WEB 使用者，在聊天页顶部状态栏同时关注「上下文占用」与「缓存命中率」两个指标。当前两个胶囊**外观完全一致**（同底色、同圆角、仅数值不同），只能靠悬浮提示分辨；且两者之间空隙过大，视觉上割裂。

**产品约束**：
- 复用 `StatusBarItem` 协议与现有 `StatusBarItemView`（已支持 `icon` prop），不改数据源与开关逻辑。
- 图标与设置页「状态栏」卡片保持一致：**上下文占用 = Gauge，缓存命中率 = Zap**（设置页已用）。
- 状态点语义（ok/warning/error/idle）、「—」占位、悬浮明细、localStorage 开关全部不变。
- 零硬编码色值，仅消费主题令牌。

**设计方向**：用既有图标语言区分两个栏目；把双容器各自 `margin-left: auto` 造成的巨大空隙收敛为统一分组间距。

**Design Read**：紧凑工具胶囊组。图标即角色标识（对照设置卡片），组内间距退化为常规 `--sp-1`。
**Dial**：`VARIANCE 2`（不动造型语言）· `MOTION 0`（无新增动效）· `DENSITY 4`（维持胶囊密度）。

## 2. 流程与状态

交互与数据流完全不变；仅视觉呈现层变化。

| 状态 | 现状 | 目标 |
|---|---|---|
| 正常 | 两个无图标同款胶囊，难区分 | 上下文占=Gauge、缓存命中率=Zap，图标即区分 |
| 间距 | 两个 `.statusbar` 各自 `margin-left:auto`，剩余空间被均分 → 中间空隙过大 | 外层 `.statusbar-group` 统一对齐，组内 `gap: var(--sp-1)` 紧邻 |
| 无数据/取数失败 | 「—」 | 图标保留，「—」不变 |
| 栏目关闭 | 对应组件不渲染、不取数 | 不变 |

## 3. 组件规格

### 3.1 StatusBarItem 协议扩展

```typescript
export interface StatusBarItem {
  key: string
  getData: () => Promise<StatusData> | StatusData
  render: (data: StatusData) => ReactNode
  status?: (data: StatusData) => StatusBarState
  title?: (data: StatusData) => string
  /** 栏目图标(与设置页卡片一致) */
  icon?: ReactNode
}
```

`StatusBar` 容器把 `item.icon` 传给 `StatusBarItemView`（其已支持 `icon` 渲染），无需改 ItemView。

### 3.2 各栏目注入图标

- `ContextUsageItem` 返回的 item：`icon: <Gauge size={13} aria-hidden="true" />`
- `CacheHitRateItem` 返回的 item：`icon: <Zap size={13} aria-hidden="true" />`
- 图标尺寸沿用 `--icon-sm`（14px 口 13px 视觉匹配胶囊高度，二者其一即可，保持一致即可）；颜色继承胶囊 `--text-secondary`（`.statusbar__icon` 现为 inline-flex、无显式色，随 item 文字色）。

### 3.3 间距收敛（根因修复）

聊天页两个栏目组件当前各自渲染一个 `.statusbar`（都带 `margin-left:auto`），Flex 会把空余空间**同时**分配给两个 auto 外边距，造成中间大空隙。

- `ChatWindow` 在两者外加一层分组容器：

```tsx
<div className="statusbar-group">
  <ContextUsageItem messages={messages} endpointId={...} />
  <CacheHitRateItem />
</div>
```

- CSS 调整：
  - 新增 `.statusbar-group { display: inline-flex; align-items: center; gap: var(--sp-1); margin-left: auto; flex-shrink: 0; }`（对齐职责从 `.statusbar` 上移）
  - `.statusbar { margin-left: 0; }`（移除原 `auto`；`.statusbar` 里仍保留自身的 item 间距 `gap: var(--sp-1)`，组内实际视觉间距≈一处 `--sp-1`，不再翻倍）

### 3.4 无障碍与响应式

- 图标 `aria-hidden="true"`；语义由数值文本 + `title`（悬浮/读屏标题）承载，不变。
- 窄屏：组容器与现状一致随顶部行换行，不额外处理。

## 4. 设计令牌

零新增令牌：

| 角色 | 令牌/现有样式 |
|---|---|
| 图标色 | 继承 `.statusbar__item` 的 `--text-secondary` |
| 组间距 | `gap: var(--sp-1)` |
| 图标尺寸 | `--icon-sm`（14px）或 13px，全组统一 |
| 对齐 | 组容器 `margin-left: auto`（原 `.statusbar` 移除） |

## 5. 交接目标与验收标准

**实现目标**：纯 SPA React + 项目原生 CSS，仅 StatusBar 协议、两个栏目、ChatWindow 挂载点、statusbar CSS 四处小改；无后端与数据源改动。在 `feat/trajectory-page`（PR #15）继续 follow-up。

**工程验收（可测）**：
- [ ] 两个胶囊分别渲染 Gauge / Zap 图标，与设置页两张卡片图标一致
- [ ] 两栏目间距由「双 auto 边距撑大」收敛为 `--sp-1`（`.statusbar` 不再带 `margin-left:auto`，改为 `.statusbar-group` 承载）
- [ ] 状态点、占位、悬浮明细、栏目开关行为不回归
- [ ] StatusBar 容器将 `item.icon` 传入 ItemView（组件测试覆盖：两 item 各自带图标渲染出来）
- [ ] `npm run lint`、`npm run build`、全量 `npm test` 通过