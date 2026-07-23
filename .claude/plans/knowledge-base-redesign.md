# 知识库页面 UI 优化 — 实现计划

## Context

根据 `docs/design/knowledge-base-redesign-spec.md` 设计规格，对知识库页面进行 UI 优化。当前页面功能完整但视觉层次单薄：缺少概览信息、无拖拽上传、检索结果 score 不直观、无响应式适配。本计划将这些改进落地到现有 React + 纯 CSS 架构中。

## 影响文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/components/KnowledgeBase/KnowledgeBasePage.tsx` | **修改** | 主要逻辑 + JSX 重构 |
| `frontend/src/App.css` | **修改** | 新增/修改 `.kb-*` 样式（约 2200–2505 行区域） |
| `frontend/src/i18n/locales/en.json` | **修改** | 新增 i18n keys |
| `frontend/src/i18n/locales/zh-CN.json` | **修改** | 新增 i18n keys |

**复用现有组件：** `Toast`（来自 `Settings/Toast.tsx`）

## 实现步骤

### Step 1: i18n — 新增翻译 keys

在 `en.json` 和 `zh-CN.json` 的 `knowledgeBase` 节中新增：

| Key | EN | ZH-CN |
|-----|-----|-------|
| `overview` | Overview | 概览 |
| `totalChunks` | Chunks | 分块 |
| `createdAt` | Created | 创建于 |
| `dropzoneHint` | Drop files here or click to upload | 拖拽文件到此处或点击上传 |
| `dropzoneActive` | Release to upload | 释放以上传文件 |
| `queryResultCount` | Found {count} results | 找到 {count} 条结果 |
| `queryDuration` | {duration}s | 耗时 {duration}s |
| `mobileSelectKb` | Select Knowledge Base | 选择知识库 |

### Step 2: App.css — 样式新增与修改

**修改现有规则：**
- `.kb-sidebar` — `width: 280px` → `300px`，`gap: var(--sp-2)` → `var(--sp-3)`
- `.kb-item--selected` — 增加 `border-left: 3px solid var(--accent)`
- `.kb-item__actions button` — 增加 `:focus-visible` 可见态
- `.kb-layout` — `gap: var(--sp-4)` → `var(--sp-5)`
- `.kb-query-result` — `padding` 增加，`margin-bottom: var(--sp-2)` → `var(--sp-3)`
- `.kb-doc-table__header / __row` — grid 列宽改用 `minmax`

**新增规则：**
- `.kb-overview-card` — 概览卡片（accent 左边框，统计胶囊行）
- `.kb-overview-card__stats` — flex row, gap
- `.kb-overview-card__stat` — 单个统计项（数值 + 标签）
- `.kb-doc-dropzone` — 虚线边框拖拽区
- `.kb-doc-dropzone--active` — 拖拽高亮态
- `.kb-query-stats` — 结果统计行
- `.kb-score-bar` / `.kb-score-bar__fill` — score 进度条
- `.kb-empty-state` — 统一空态
- `.kb-mobile-selector` — 移动端 KB 下拉选择器
- `@media (max-width: 767px)` — 响应式断点

### Step 3: KnowledgeBasePage.tsx — 组件逻辑重构

**3a. 新增 state 和 ref：**
- `isDragOver: boolean` — 拖拽高亮
- `totalChunks: number` — 概览卡片分块总数（前端从 documents 累加）
- `queryDuration: string` — 检索耗时
- `mobileMenuOpen: boolean` — 移动端选择器展开态
- `dropzoneRef` — 拖拽区域 DOM ref

**3b. 替换消息通知：**
- 移除 `settings-message` 内联消息
- 导入 `Toast` 组件，使用 `message` + `isError` state 驱动

**3c. 新增 JSX 区域：**

**移动端 KB 选择器**（仅 `< 768px` 可见）：
- 当选中 KB 时显示 KB 名称 + ChevronDown
- 点击展开 overlay 列表
- 选择后关闭并刷新

**KB 概览卡片**（右侧顶部）：
- KB 名称（`--fs-lg, --fw-semi`）
- 描述（`--fs-sm, --text-secondary`，最多 2 行截断）
- 统计行：文档数 | 分块数 | 创建时间
- 右上角编辑/删除按钮

**文档拖拽上传区**：
- `onDragOver / onDragEnter / onDragLeave / onDrop` 处理器
- 默认态：虚线边框 + UploadCloud 图标 + "拖拽文件到此处上传"
- 拖拽高亮态：accent 边框 + accent-muted 背景
- drop 时触发已有 `handleUpload` 逻辑
- 放置在文档表格上方（或空态替代）

**Score 进度条**：
- 每个检索结果的 score 改为进度条 + 数值
- 颜色分级：≥0.8 success / ≥0.5 accent / <0.5 secondary
- 结果顶部统计行：「找到 N 条结果 · 耗时 Xs」

**3d. 响应式处理：**
- CSS 媒体查询控制 sidebar/mobile-selector 切换
- < 768px：文档表格行改为卡片布局（CSS grid 调整）

### Step 4: 验证

- `npm run build` — TypeScript 编译通过
- `npm run lint` — ESLint 无报错
- 手动检查三主题（dark/light/warm）下新增元素的令牌适配
- 检查 `< 768px` 响应式布局

## 不做的事

- 不新增子组件文件（保持现有 inline 模式，与其他页面一致）
- 不新增设计令牌（完全复用 `index.css` / `themes.css`）
- 不修改后端 API（前端累计 totalChunks，不需后端改动）
- 不修改 `KnowledgeBaseSelector`（Chat 页面的下拉选择器，保持不变）
