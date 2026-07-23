# KnowledgeBasePage UI 优化设计规格

## 1. 用户与场景摘要

| 维度 | 描述 |
|------|------|
| **目标用户** | Thumbelina 个人用户，管理 RAG 知识库以增强对话质量 |
| **核心目标** | 高效创建/管理知识库、上传文档、验证检索效果 |
| **设备环境** | 桌面优先（1024px+），需兼容平板（768px+）和移动端（< 768px） |
| **使用频率** | 中低频设置页面，通常在首次配置和文档更新时访问 |
| **设计约束** | 复用现有 `index.css` / `themes.css` / `App.css` 设计令牌体系；BEM 类名；`lucide-react` 图标；三主题适配 |

---

## 2. 流程与状态模型

### 2.1 主用户旅程

```
[进入知识库页面]
    │
    ▼
┌─────────────────┐
│  查看知识库列表  │ ── 空 → 展示引导空态
└─────────────────┘
    │ 选择/新建
    ▼
┌─────────────────┐
│  知识库详情面板  │
│  ├─ 概览卡片    │
│  ├─ 文档管理    │
│  └─ 检索测试    │
└─────────────────┘
```

### 2.2 状态矩阵

| 区域 | 空态 | 加载中 | 有数据 | 操作中 | 错误 |
|------|------|--------|--------|--------|------|
| **页面整体** | 引导占位 + CTA | 全屏 spinner | 双栏布局 | — | 顶部 toast |
| **KB 列表** | 引导文案 + 创建按钮 | 骨架条 ×3 | 列表项 | 新建表单展开 | 错误提示 |
| **KB 详情** | 选中引导占位 | spinner | 概览+文档+检索 | 上传进度条 | 文档加载失败 |
| **文档列表** | 空态插图 | spinner | 文档表格 | 上传中禁用按钮 | 上传失败 toast |
| **检索测试** | 输入框默认态 | 按钮 loading | 结果卡片列表 | — | 无结果文案 |

### 2.3 边界场景

| 场景 | 处理方式 |
|------|----------|
| 大量知识库（>20个） | 列表区域 `overflow-y: auto`，当前已支持 |
| 长文件名 | 截断 + tooltip（`title` 属性） |
| 文档上传失败（部分文件） | 逐文件上传，失败时 toast 提示，已成功的继续 |
| 并发操作（编辑+上传） | 编辑表单展开时禁用上传按钮 |
| 删除确认被中断 | 点击其他 KB 项自动取消删除确认态 |
| 移动端双栏布局 | < 768px 时堆叠为单栏，KB 列表变为可折叠抽屉 |

---

## 3. 组件规格

### 3.1 KbOverviewCard（知识库概览卡片）🆕

**目的：** 在右侧详情面板顶部展示选中知识库的核心元信息，建立视觉锚点。

```typescript
interface KbOverviewCardProps {
  kb: KnowledgeBase;         // 选中的知识库
  documentCount: number;     // 文档总数
  totalChunks: number;       // 总分块数（需后端新增字段，或前端累计）
  createdAt: string;         // 创建时间
  onEdit: () => void;        // 编辑回调
  onDelete: () => void;      // 删除回调（触发确认）
}
```

**布局：**

```
┌─────────────────────────────────────────────────────┐
│ 📚 知识库名称                       [编辑] [删除]  │
│ 这是一段描述文字，简要说明知识库的用途和内容范围...  │
│                                                      │
│ ┌──────┐  ┌──────┐  ┌──────┐                        │
│ │  12  │  │  58  │  │ 3天前│                        │
│ │ 文档 │  │ 分块 │  │ 创建 │                        │
│ └──────┘  └──────┘  └──────┘                        │
└─────────────────────────────────────────────────────┘
```

**设计要点：**
- 顶部大标题（`--fs-lg`, `--fw-semi`, `--text-heading`）+ 右侧操作按钮组
- 描述文字（`--fs-sm`, `--text-secondary`），最多 2 行截断
- 三个统计胶囊并排：文档数、分块数、创建时间
- 统计胶囊：`background: var(--bg-hover)`, `border-radius: var(--radius)`, `padding: var(--sp-2) var(--sp-3)`
- 数值用 `--fs-lg` + `--fw-bold` + `--accent`，标签用 `--fs-xs` + `--text-secondary`

**删除确认：** 按钮区域内联确认（复用现有 trash → check+X 模式），不使用弹窗。

**响应式：**
- < 768px：统计胶囊纵向堆叠

---

### 3.2 KbSidebarItem（知识库列表项）— 改进

**目的：** 左侧列表中每个知识库的卡片式条目。

**现有问题：**
- 操作按钮仅 hover 可见，触屏不友好
- 文档数 badge 位置不醒目

**改进方向：**

| 属性 | 当前 | 改进后 |
|------|------|--------|
| 操作按钮 | `opacity: 0` → `opacity: 1` on hover | 移动端始终可见；桌面端 hover 显示但加 `focus-within` 可见 |
| 选中态 | `accent-border` + 渐变背景 | 左侧 3px `accent` 边框（`border-left: 3px solid var(--accent)`），背景 `accent-muted` |
| 描述截断 | 单行 ellipsis | 保持单行，增加 `title` 属性 tooltip |
| 文档数 | `badge badge-neutral` | 保持，增加 `FileText` 小图标前缀 |

**响应式：**
- < 768px：固定宽度 280px → 改为可折叠侧栏（drawer），点击汉堡图标展开

---

### 3.3 KbDocumentTable（文档表格）— 改进

**目的：** 展示知识库中的文档列表及其元信息。

**现有问题：**
- 固定 grid 列宽在窄屏下溢出
- 缺少文件类型图标区分
- 无拖拽上传视觉区域

**改进：**

| 属性 | 当前 | 改进后 |
|------|------|--------|
| 列布局 | 固定 `1fr 60px 60px 140px 32px` | `minmax(120px, 1fr) auto auto auto auto`，窄屏隐藏 chunk 和 time 列 |
| 文件图标 | 无 | 根据 `file_type` 显示 `FileText`（.txt）或 `BookOpen`（.md） |
| 上传区域 | 隐藏 input + 按钮 | 增加内联拖拽提示区域（`kb-doc-table__dropzone`），文件拖入时高亮 |
| 空态 | 纯文字 | 居中插图 + 拖拽提示文案 |

**拖拽上传区域规格：**

```
.kb-doc-table__dropzone:
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
  transition: border-color var(--dur-base) var(--ease-out),
              background var(--dur-base) var(--ease-out);

  hover/drag-over:
    border-color: var(--accent);
    background: var(--accent-muted);
```

**响应式（< 768px）：**
- 表格改为卡片列表：每张卡片显示文件名 + 类型 badge + chunk 数，时间戳和删除按钮在底部

---

### 3.4 KbQueryTest（检索测试）— 改进

**目的：** 让用户验证知识库的检索效果。

**现有问题：**
- 结果展示平铺无层次
- 无结果数量和检索耗时信息
- score 展示不够直观

**改进布局：**

```
┌─────────────────────────────────────────────┐
│ 🔍 检索测试                                  │
│ ┌───────────────────────────────┐ ┌────────┐│
│ │ 输入测试问题...               │ │  检索  ││
│ └───────────────────────────────┘ └────────┘│
│                                              │
│ 找到 3 条结果 · 耗时 0.23s                   │
│                                              │
│ ┌─────────────────────────────────────────┐  │
│ │ ████████████████░░░░ 0.872  相似度      │  │
│ │                                          │  │
│ │ 匹配的文本内容片段，使用等宽字体显示... │  │
│ │                                          │  │
│ └─────────────────────────────────────────┘  │
│ ┌─────────────────────────────────────────┐  │
│ │ ██████████████░░░░░░ 0.741  相似度      │  │
│ │ ...                                      │  │
│ └─────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**ResultCard 改进：**
- Score 用进度条可视化：`<div class="kb-query-result__score-bar">` 宽度 = `score * 100%`，颜色分级：
  - ≥ 0.8: `var(--success)` 绿色
  - 0.5–0.8: `var(--accent)` 主色
  - < 0.5: `var(--text-secondary)` 灰色
- Score 数值紧跟进度条右侧（`--fw-med`）
- 内容区保持 `pre-wrap` + `font-mono`，但改为 `background: var(--bg-surface)` + `border-radius: var(--radius-sm)`
- 结果卡片间间距 `var(--sp-3)`（当前 `var(--sp-2)`，太紧）

---

### 3.5 EmptyState（空态组件）— 统一

**目的：** 统一各区域的空态展示风格。

```typescript
interface EmptyStateProps {
  icon: LucideIcon;          // 图标组件
  title: string;             // 主文案
  description?: string;      // 辅助文案
  action?: {                 // 可选 CTA 按钮
    label: string;
    onClick: () => void;
  };
}
```

**样式：**
```
display: flex;
flex-direction: column;
align-items: center;
justify-content: center;
gap: var(--sp-3);
padding: var(--sp-10) var(--sp-4);
color: var(--text-secondary);
text-align: center;

icon: opacity: 0.25; width: 48px; height: 48px;
title: --fs-sm, --fw-med, --text-secondary;
description: --fs-xs, --text-secondary (lighter);
action button: --btn-primary--sm
```

---

## 4. 页面整体布局改进

### 4.1 顶部区域

**当前：** `page-title` + `settings-message`（位于 `.kb-layout` 外部）

**改进：**
- 移除独立的 `page-title` 和 `message` 区域
- 将页面标题集成到 `.kb-layout` 内，作为左侧 KB 列表的 header 一部分
- 状态消息改为 toast 通知（使用现有 `.toast` 组件），不在页面内占据空间

### 4.2 双栏布局

**当前结构保持**，但调整比例和间距：

| 属性 | 当前 | 改进后 |
|------|------|--------|
| 左栏宽度 | `280px` 固定 | `300px` 固定（增加 20px 给操作按钮更多空间） |
| 右栏 | `flex: 1` | 保持 |
| 间距 | `gap: var(--sp-4)` | `gap: var(--sp-5)` |
| 左栏内间距 | `gap: var(--sp-2)` | `gap: var(--sp-3)` |

### 4.3 右侧详情面板结构

```
.kb-detail
  ├── .kb-overview-card        ← 新增：概览卡片
  ├── .card (文档管理)
  │   ├── .card-title + 上传按钮
  │   ├── .kb-doc-table__dropzone  ← 新增：拖拽上传区
  │   └── .kb-doc-table (或空态)
  └── .card (检索测试)
      ├── .card-title
      ├── .kb-query (输入区)
      └── .kb-query-results (结果卡片)
```

---

## 5. 设计令牌使用

本优化不引入新的设计令牌，完全复用现有体系：

| 用途 | 使用的令牌 |
|------|-----------|
| 标题文字 | `--fs-lg` / `--fw-semi` / `--text-heading` |
| 正文 | `--fs-sm` / `--fw-med` / `--text-primary` |
| 辅助文字 | `--fs-xs` / `--fw-reg` / `--text-secondary` |
| 统计数字 | `--fs-lg` / `--fw-bold` / `--accent` |
| 卡片背景 | `--bg-surface` |
| 悬浮态 | `--bg-hover` |
| 选中背景 | `--accent-muted` |
| 选中边框 | `--accent-border` / `--accent` |
| Score 高 | `--success` |
| Score 中 | `--accent` |
| Score 低 | `--text-secondary` |
| 拖拽态边框 | `--accent` |
| 拖拽态背景 | `--accent-muted` |
| 边框 | `--border` |
| 圆角 | `--radius` / `--radius-sm` |
| 间距 | `--sp-1` ~ `--sp-12` |
| 动效 | `--dur-fast` / `--dur-base` / `--ease-out` |
| 阴影 | `--shadow-sm` / `--shadow-md` |
| 聚焦 | `--focus-ring` |
| 图标尺寸 | `--icon-sm` (14px) / `--icon-md` (16px) / `--icon-lg` (20px) |

---

## 6. 无障碍与响应式

### 6.1 无障碍

| 需求 | 实现方式 |
|------|----------|
| 拖拽上传区 | 增加 `role="region"` + `aria-label="文件上传区域"`，同时保留按钮上传作为键盘替代 |
| 列表导航 | KB 列表使用 `role="listbox"`，列表项使用 `role="option"` + `aria-selected` |
| 删除确认 | `aria-label="确认删除"` / `aria-label="取消删除"` |
| 状态变化 | 上传进度/完成使用 `aria-live="polite"` 区域播报 |
| Score 进度条 | `role="progressbar"` + `aria-valuenow` + `aria-valuemin="0"` + `aria-valuemax="1"` |
| 键盘导航 | Tab 序列：KB 列表项 → 详情面板按钮 → 检索输入框 → 检索按钮 |

### 6.2 响应式断点

| 断点 | 布局 |
|------|------|
| ≥ 1024px (desktop) | 标准双栏：左侧 300px + 右侧 flex-1 |
| 768px–1023px (tablet) | 双栏：左侧 260px + 右侧 flex-1，统计胶囊 2+1 排列 |
| < 768px (mobile) | 单栏堆叠：KB 列表变为顶部下拉选择器或抽屉；详情面板全宽；文档表格改为卡片列表 |

**移动端 KB 选择器方案：**
- 详情面板顶部新增一个 `.kb-mobile-selector`：
  - 显示当前选中 KB 名称 + 下拉箭头
  - 点击展开全屏 overlay 列表
  - 选择后关闭 overlay，详情面板刷新

---

## 7. 工程实现交接

### 实现目标

`react-vite-tailwind-engineer`（纯 SPA，无 SSR 需求）

**技术栈：** React 19 + TypeScript + Vite 8 + 纯 CSS（非 Tailwind）

### 需要修改的文件

| 文件 | 修改内容 |
|------|----------|
| `frontend/src/components/KnowledgeBase/KnowledgeBasePage.tsx` | 拆分为子组件，新增概览卡片、拖拽上传、score 进度条 |
| `frontend/src/App.css` | 新增/修改 `.kb-*` 样式规则（约 2200–2505 行区域） |
| `frontend/src/i18n/locales/en.json` | 新增 i18n keys（概览卡片、拖拽区、结果统计） |
| `frontend/src/i18n/locales/zh-CN.json` | 对应中文翻译 |

### 新增 i18n Keys

```json
{
  "knowledgeBase.overview": "概览",
  "knowledgeBase.totalChunks": "总分块",
  "knowledgeBase.createdAt": "创建于",
  "knowledgeBase.dropzoneHint": "拖拽文件到此处上传",
  "knowledgeBase.dropzoneActive": "释放以上传文件",
  "knowledgeBase.queryResultCount": "找到 {count} 条结果",
  "knowledgeBase.queryDuration": "耗时 {duration}",
  "knowledgeBase.mobileSelectKb": "选择知识库"
}
```

### 新增/修改的 CSS 类

```css
/* 新增 */
.kb-overview-card { ... }
.kb-overview-card__stats { ... }
.kb-overview-card__stat { ... }
.kb-overview-card__stat-value { ... }
.kb-overview-card__stat-label { ... }
.kb-doc-table__dropzone { ... }
.kb-doc-table__dropzone--active { ... }
.kb-query-result__score-bar { ... }
.kb-query-result__score-bar-fill { ... }
.kb-query-stats { ... }
.kb-mobile-selector { ... }
.kb-empty-state { ... }
.kb-empty-state__icon { ... }
.kb-empty-state__title { ... }
.kb-empty-state__desc { ... }

/* 修改 */
.kb-sidebar { width: 300px; gap: var(--sp-3); }
.kb-item--selected { border-left: 3px solid var(--accent); }
.kb-doc-table__header { grid-template-columns: minmax(120px, 1fr) auto auto auto auto; }
.kb-query-result { padding: var(--sp-3); margin-bottom: var(--sp-3); }
.kb-layout { gap: var(--sp-5); }

/* 新增响应式 */
@media (max-width: 767px) {
  .kb-layout { flex-direction: column; }
  .kb-sidebar { display: none; }
  .kb-mobile-selector { display: flex; }
  .kb-doc-table__header,
  .kb-doc-table__row { /* 卡片式布局 */ }
}
@media (min-width: 768px) {
  .kb-mobile-selector { display: none; }
}
```

### 实现验收标准

- [ ] 左侧 KB 列表：选中态左侧 accent 边框，操作按钮 focus-within 可见
- [ ] 右侧概览卡片：显示 KB 名称、描述、统计（文档数/分块数/创建时间）
- [ ] 文档区域：内联拖拽上传区 + 按钮上传并存，拖拽视觉反馈
- [ ] 检索测试：结果数量 + 耗时统计，score 进度条可视化
- [ ] 空态：统一 EmptyState 样式，含图标 + 文案 + 可选 CTA
- [ ] 三主题适配（dark/light/warm）：所有新增元素使用设计令牌
- [ ] 响应式：< 768px 单栏堆叠 + 移动端 KB 选择器
- [ ] 无障碍：拖拽区 role + aria-label，列表 role="listbox"，score progressbar
- [ ] 状态消息改为 toast（复用现有 `.toast` 组件）
- [ ] i18n：新增 keys 英中双语完整
- [ ] 无 TypeScript 错误、无 ESLint 警告
