# 记忆页分组浏览 + 分层全文搜索 设计交接

- **日期**：2026-08-26
- **状态**：已确认（用户决策）
- **相关代码**：`frontend/src/components/Memory/MemoryViewer.tsx`、`frontend/src/App.css`、`frontend/src/i18n/locales/{zh-CN,en}.json`、`src/thumbelina/memory/{search,service,models}.py`、`src/thumbelina/api/routes/memory.py`
- **基于**：Markdown 分层记忆子系统（L0 索引 / L1 概览 / L2 全文，见 `docs/plans/2026-08-16-markdown-memory-design.md`）、待办分组过滤卡片模式（`docs/plans/2026-08-24-todo-group-filter-design.md`）

## 1. 用户与上下文总结

**目标用户**：通过 WEB 前端查看与检索个人记忆的普通用户。

**现状问题**：顶部"记忆"页的搜索框实际请求 `/api/v1/conversations/search`（历史对话消息），与"轨迹"页重复；记忆本体（`MEMORY/<category>/<slug>.md`）只可浏览技能/组合，无法浏览与检索。

**产品目标**：
1. 记忆页搜索改为检索**记忆本体**（L0 标题/摘要 + L1 概览 + L2 正文）
2. 记忆以分类分组展示，支持分组过滤聚焦（复用待办页交互）
3. 在不引入向量库/预建索引的前提下获得可行的全文查询策略（分层 n-gram 分块取极值）

**已确认决策**：
1. 搜索走后端 `/api/v1/memory/search`（升级为分层全文检索）
2. 分组维度 = 记忆分类白名单 `user/project/decision/topic`（对应 用户/项目/决策/主题），卡片带计数，默认选中"全部"按组分块展示
3. 分组卡片只显示有内容的分类；空分类不出现；「全部」计数 = 可见条数
4. 搜索命中结果同样按组分块，与分组过滤 AND 叠加
5. 点击条目展开查看 概览 + 全文（`depth=full`），内联展开而非弹窗
6. 保留技能/组合卡片区（独立功能，仅随视觉升级）
7. 后端保持确定性检索：字符 2-gram 覆盖率 + 精确 token 重叠 + 分块 max-pooling，不引入 embedding/FTS

**约束**：复用现有 CSS 变量与 BEM 类名风格；不改动抽取器/注入路径（`search_entries` L0 口径保留）。

## 2. 流程与状态

### 主流程

```
打开记忆页
   │
   ▼
拉取 /entries + /status ── 加载失败 → 错误态(重试)
   │                       模块禁用 → 禁用提示
   ▼
无记忆 → 空态(引导)
   │
   ▼
浏览模式(默认)：分组卡片栏 全部|用户|项目|决策|主题
   │  分组卡片+计数，默认"全部"→ 按组分块展示
   │  点击具体分组 → 只显示该组
   ▼
输入关键词回车/点搜索 → 搜索模式
   │  调 /api/v1/memory/search?q=…
   │  结果同样按组分块 + 分组卡片过滤 AND 叠加
   │  命中项显示 snippet 高亮 + 命中层级 badge
   ▼
点击条目 → 拉取 depth=full → 内联展开 概览+全文
   │  Esc / 再次点击 → 收起
   ▼
清空关键词 → 回到浏览模式
```

### 状态

| 状态 | 表现 |
|------|------|
| Loading | 骨架屏（搜索区域 + 列表占位），`aria-busy` |
| 模块禁用 | 提示卡片 `memory.disabled`，隐藏搜索与列表 |
| 数据错误 | 错误条 + 重试按钮，不隐藏页面 |
| 空数据（浏览） | 空态：图标 + "暂无记忆" |
| 搜索无结果 | 空态：图标 + "未找到相关记忆" |
| 搜索中 | 按钮 loading 图标 + spinner，输入框保持可用 |
| 搜索后清空 | 一键清空按钮 `×`，恢复浏览模式 |

### 边角情况

| 场景 | 处理 |
|------|------|
| 只有 1 个分类有内容 | 卡片栏「全部」+ 该分类 2 张 |
| 全部分类为空 | 卡片栏隐藏，显示空态 |
| 分类计数在搜索后变化 | 计数基于当前可见（过滤后）列表派生 |
| 条目无摘要/无更新时间 | 对应位置回退占位（–） |
| 命中片段很长 | 截断 200 字符 + 省略号，`title` 属性放全文 |
| 高亮词含正则特殊字符 | 前端对 query 转义后高亮（`escapeRegExp`） |
| 全文很大 | 后端 `read_full` 截断上限已存在，前端按 `max-height` 滚动 |

## 3. 组件规格

### 3.1 MemorySearchBar

- **用途**：输入关键词搜索记忆全文（L0/L1/L2）
- **行为**：Enter / 按钮触发；`disabled` 无关键词或请求中；`×` 清空回浏览
- **可访问性**：input 绑定 `aria-label="搜索记忆"`；请求中 `aria-busy`
- **关键选择**：不复用对话搜索，目标 `/api/v1/memory/search`，`top_k=50`

### 3.2 MemoryGroupFilter（复用 todo-group-filter 视觉契约，类名 `memory-group-filter`）

- **props**：`options: {key,label,count,icon}[]`、`selected: string`、`onSelect`
- **语义**：`''` 全部；`user|project|decision|topic` 具体分类；分类顺序固定白名单顺序
- **交互**：`aria-pressed`；选中态 `--accent-secondary` 高亮（与待办一致）；单行横向滚动
- **计数徽标**：圆形，选中时反色

### 3.3 MemoryEntryCard

- **用途**：浏览/搜索共用的记忆条目卡片
- **props**：`entry`（含 category/title/summary/updated/source/score?/matched?/snippet?）、`expanded`、`query?`、`onToggle`
- **内容（浏览）**：分类 badge（带分类色）、标题、摘要（2 行截断）、更新时间 + 来源 meta
- **内容（搜索命中）**：分类 badge + 命中层级 badge（标题/摘要/概览/正文）、标题、摘要、**snippet**（`<mark>` 高亮命中词，转义后高亮）、更新时间
- **展开**：`aria-expanded`；展开区渲染 概览 + 全文（MarkdownContent），顶部"返回顶部收起"
- **键盘**：卡片为 `<button>` 或可聚焦元素，Enter/Space 切换展开；Esc 收起

### 3.4 页面骨架

```
page-container
├─ page-title 记忆
├─ MemorySearchBar（card）
├─ MemoryGroupFilter（有内容时）
├─ 分组列表 / 搜索结果（card，分块：组头 + 卡片列表）
├─ card: 系统技能（保留）
└─ card: 技能组合（保留）
```

数据流：`entries` 全量（浏览）→ `visible` 按 `activeCategory` 过滤；`query` 非空时切换为 `results` 数据源 → 同样按 `activeCategory` 过滤。两个模式共用 GroupFilter 与 EntryCard，仅"命中片段/层级 badge"为搜索模式附加。

## 4. 设计令牌与样式规则

全部复用现有 CSS 变量体系（`frontend/src/index.css` + `styles/themes.css`），不新建色板。新增 `memory-*` BEM 类，与 `.todo-group-filter` 等共享规则用逗号合并选择器。

| 语义 | Token |
|------|-------|
| 分类 badge 用户 | `--accent` 背景 `--accent-muted` |
| 分类 badge 项目 | `--accent-secondary` 背景 `--accent-secondary-muted` |
| 分类 badge 决策 | `--success` 背景 `--success-muted` |
| 分类 badge 主题 | `--warning` 背景 `--warning-muted` |
| 命中层级 badge | `--bg-hover` 底 + `--text-secondary`（中性） |
| snippet 高亮 `<mark>` | `background: var(--accent-secondary-muted)` + `color: var(--accent-secondary)`，`border-radius: 2px` |
| 组头 | `.todo-group__header` 同款：分隔线 + `--fs-xs --fw-semi --text-secondary` |
| 空态/骨架/错误 | 复用 `.todo-empty-state` / `.todo-skeleton` 视觉语言（新增 `memory-` 副本或合并选择器） |

**动效**：卡片展开 180ms `--ease-out`；进入动画复用 `todo-item-in` 命名体感（轻量 fade/translate）。

**暗色/亮色**：全部走变量，自动适配。

**响应式**：单列；分组卡片栏横向滚动（`scrollbar-width: none`）；展开全文 `max-height: 60vh; overflow:auto`。

## 5. 后端检索规格（查询策略）

### 5.1 字段与权重

| 层级 | 字段 | 权重 | 说明 |
|------|------|------|------|
| L0 | `title` | 1.0 | 标题命中最相关 |
| L0 | `summary` | 0.9 | 索引一句话摘要 |
| L1 | `overview` | 0.8 | 概览 2–5 行 |
| L2 | `full_text` | 0.6 | 完整正文（最长，降权防长文本膨胀） |

### 5.2 打分（确定性，无外部依赖）

1. query 提取字符 2-gram 集 `q_gram`
2. 长字段分块：`overview`/`full_text` 按空行拆段落，段落 >160 字符再按 `。！？!?；;` 拆句；每块独立打分
3. 块分 = `0.7 * (覆盖率+Dice)/2 + 0.3 * token重叠率`，其中 覆盖率 = `|q_gram ∩ c_gram| / |q_gram|`（解决长文本稀释）
4. 字段分 = 全块最高分（max-pooling）；条目标 = `max(字段分 × 权重)`
5. 记录 `matched_field`（argmax）与最佳块文本 → 生成 snippet（截断 200 字符）

### 5.3 API 契约

`GET /api/v1/memory/search?q=&top_k=` 返回：

```json
[{
  "title": "用户:编程偏好", "category": "user", "slug": "programming-preference",
  "summary": "…", "score": 0.61,
  "matched_field": "full_text", "snippet": "…命中片段…",
  "updated": "2026-08-26", "source": "对话 2026-08-10"
}]
```

- 服务端 `search_content`：锁内扫描全部条目 → 全量读文件（不截断）→ 分层打分
- 保留 `search_entries`（L0）供抽取器/注入使用，不改动
- 规模护栏：`max_entries=200`、`max_total_bytes=5MB`，全量扫描毫秒级，`to_thread` 防阻塞

## 6. 交接与验收

- **实现目标**：`react-vite-engineer`（本项目 Vite + React + 原生 CSS 变量，非 Tailwind）
- **验收标准**：
  - [ ] 记忆页搜索返回记忆命中（L1/L2 可命中），不再请求 conversations
  - [ ] 浏览模式按分类分块展示 + 分组卡片过滤生效
  - [ ] 搜索模式结果按组分块，分组过滤叠加生效，snippet 高亮正确
  - [ ] 点击条目内联展开概览+全文，Esc 收起
  - [ ] 空/禁用/错误/loading 状态齐全
  - [ ] 后端新增检索测试通过；前端 vitest 通过
  - [ ] 明暗主题、窄屏滚动无溢出
## 7. 变更纪要（第二轮：美化 + 移除技能/组合）

### 7.1 变更目标

- **移除**：记忆页中的「系统技能」与「技能组合」两个卡片区（含对应 API 调用、状态、i18n 键与测试）。这些属于 Agent 技能管理，与记忆浏览/检索无关，保留会稀释记忆页语义。
- **美化**：在保持现有设计系统（CSS 变量 + BEM）前提下提升页面层次与质感。

### 7.2 变更明细

| 项 | 行为 |
|----|------|
| 技能/组合卡片 | 整块删除；`skills/compositions` 状态、`handleLoadSkills/handleLoadCompositions`、`Skill/Composition` 接口、`Sparkles/Layers` 图标、i18n `skills/loadSkills/skillCompositions/noSkills/noCompositions/loaded` 键全部移除 |
| 记忆统计条（新增） | 搜索卡片上方新增 `memory-stats`（card）：`记忆总数`（Brain 图标）、`分类数`（FolderKanban）、`最近更新`（Clock，取浏览数据最大 updated）。仅浏览数据源；搜索/过滤不改变统计条，保持页面身份稳定 |
| 搜索框 | 输入框内嵌 Search 图标（`.memory-search-box`），聚焦时 accent 边框 + focus-ring；保留清空 `×` 与搜索按钮 |
| 空态/无结果 | 纯文本改为图标 + 文案空态（复用 todo-empty-state 视觉语言，新增 `.memory-empty-state`）：无记忆用 Brain，无结果用 SearchX，禁用用 Lock |
| 卡片动效 | `.memory-entry` 增加轻量进入动画（fade + translateY 4px，180ms ease-out），与 todo-item-in 同体感 |
| 组头 | 保留分隔线 + 计数徽标，字号不变；结构不动 |

### 7.3 设计令牌

全部沿用现有变量：统计条数字 `--fs-2xl --fw-bold --text-heading`（对齐 `.stat-value`）、标签 `--fs-xs --text-secondary`；空态图标 `opacity .6`；搜索框聚焦 `var(--focus-ring)`。明暗主题自动适配。

### 7.4 验收标准

- [ ] 页面不再出现技能/组合区块，`.skill-grid`/Sparkles/Layers 无残留引用
- [ ] 统计条显示 记忆数/分类数/最近更新，且随记忆变化刷新
- [ ] 空态（无记忆/无结果/禁用）均为图标 + 文案，非纯文本
- [ ] 搜索输入聚焦样式、卡片进入动画生效
- [ ] 原技能相关测试用例删除后 vitest 全绿；tsc/lint/build 通过
