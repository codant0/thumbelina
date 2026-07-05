# Web 设置中文化方案设计文档

## 1. 需求概述

根据 TODO 第一条：**"WEB设置中支持将语言修改为中文"**，目标是在现有英文界面的基础上，提供一个语言切换入口，让用户在英文和中文之间选择，实现全界面文本的切换。

当前现状：
- 前端使用 React 19 + TypeScript 6 + Vite 8，**无任何 i18n 库**
- 所有 UI 文本（Header 导航、设置面板、渠道页、插件页、聊天窗口、侧边栏、任务管理器、Dream 页面、Memory 页面）均为硬编码英文字符串
- 已有主题切换功能（`ThemeToggle`）使用 `localStorage` 持久化偏好，可作为语言切换的参考模式
- 项目无路由库，采用简单的 `activePage` 状态切换页面

## 2. 技术选型

### 推荐方案：自定义 `useTranslation` Hook + JSON 字典文件

**不采用 react-i18next / lingui 等第三方库的理由：**

| 对比项 | react-i18next | 自定义 Hook |
|--------|--------------|-------------|
| 包体积 | ~30KB gzipped（i18next + react-i18next） | ~2KB |
| 初始化复杂度 | Provider 包裹、i18n 实例初始化、语言检测插件 | 一个 Context + 一个 Hook |
| TypeScript 类型安全 | 需要额外 `.d.ts` 扩展 | 天然类型安全（可生成 key 类型） |
| 学习成本 | 需理解 i18next 的命名空间、插值、复数规则 | 零学习成本 |
| 适用规模 | 10+ 语言、复杂 ICU 消息格式 | 2~5 语言、简单文本替换 |

Thumbelina 是一个个人助手项目，仅需中英双语支持，自定义方案更为轻量、可控、可维护。

### 方案概要

```
┌─────────────────────────────────────────────┐
│  LocaleProvider (Context)                    │
│  ├─ locale: string ('en' | 'zh-CN')         │
│  ├─ setLocale: (locale) => void             │
│  └─ t: (key) => string                     │
├─────────────────────────────────────────────┤
│  字典文件 (JSON)                             │
│  ├─ frontend/src/i18n/locales/en.json       │
│  └─ frontend/src/i18n/locales/zh-CN.json    │
├─────────────────────────────────────────────┤
│  持久化: localStorage ('thumbelina-locale') │
│  默认值: 'en'（向后兼容）                    │
└─────────────────────────────────────────────┘
```

## 3. 字典文件组织方式

```
frontend/src/i18n/
├── index.ts                 # 导出所有公共 API
├── LocaleContext.tsx         # Context + Provider 组件
├── useLocale.ts             # useLocale / useTranslation hooks
├── types.ts                 # 字典 key 类型定义
├── locales/
│   ├── en.json              # 英文字典（完整覆盖）
│   └── zh-CN.json           # 中文字典（完整覆盖）
```

### 字典 key 命名规范

采用**扁平 + 分组**命名，以点号分隔：

```typescript
// types.ts - 自动推导自 en.json
type LocaleKey = 
  // Header 导航
  | 'nav.chat' | 'nav.tasks' | 'nav.memory' | 'nav.dream' 
  | 'nav.settings' | 'nav.plugins' | 'nav.channels'
  // 设置面板
  | 'settings.title' | 'settings.llmConfig' | 'settings.switchModel'
  // 通用
  | 'common.loading' | 'common.save' | 'common.cancel'
  | 'common.connected' | 'common.disconnected'
  // ... 逐组件展开
```

### 字典文件示例

```json
// en.json
{
  "nav": {
    "chat": "Chat",
    "tasks": "Tasks",
    "memory": "Memory",
    "dream": "Dream",
    "settings": "Settings",
    "plugins": "Plugins",
    "channels": "Channels"
  },
  "settings": {
    "title": "Settings",
    "llmConfig": "LLM Configuration",
    "provider": "LLM Provider",
    "model": "Model",
    "baseUrl": "Base URL",
    "apiKey": "API Key",
    "rateLimit": "Enable Rate Limiting",
    "switchModel": "Switch Model",
    "switching": "Switching...",
    "userProfile": "User Profile",
    "dataManagement": "Data Management",
    "exportAll": "Export All Data",
    "deleteAll": "Delete All Data",
    "language": "Language"
  },
  "common": {
    "loading": "Loading...",
    "save": "Save",
    "saving": "Saving...",
    "cancel": "Cancel",
    "connected": "Connected",
    "disconnected": "Disconnected",
    "generating": "Generating...",
    "edit": "Edit",
    "retry": "Retry",
    "done": "Done"
  },
  "channels": {
    "title": "Channels",
    "qqBot": "QQ Bot",
    "wechat": "WeChat",
    "enabled": "enabled",
    "disabled": "disabled",
    "enable": "Enable",
    "enableWechat": "Enable WeChat Channel",
    "enableQQ": "Enable QQ Bot",
    "scanQR": "Scan QR Code to Login",
    "manualConfig": "Manual Config",
    "reconnect": "Scan QR Code to Reconnect"
  },
  "chat": {
    "startPrompt": "Start a conversation",
    "startHint": "Type a message below to begin",
    "noConversations": "No conversations yet.",
    "sendHint": "Send a message to start.",
    "streamLabel": "Stream"
  },
  "taskManager": {
    "title": "Task Manager",
    "subagents": "Subagents",
    "scheduledTasks": "Scheduled Tasks",
    "noSubagents": "No active subagents",
    "noTasks": "No scheduled tasks",
    "cancel": "Cancel"
  },
  "memory": {
    "title": "Memory",
    "searchConversations": "Search Conversations",
    "searchPlaceholder": "Search messages...",
    "search": "Search",
    "searching": "Searching...",
    "noResults": "No results found",
    "skills": "Skills",
    "loadSkills": "Load Skills",
    "skillCompositions": "Skill Compositions",
    "noSkills": "No skills found",
    "noCompositions": "No compositions found"
  },
  "dream": {
    "title": "Dream",
    "loading": "Loading...",
    "refresh": "Refresh",
    "skills": "Skills",
    "categories": "Categories",
    "activeDays": "Active Days",
    "timeline": "Timeline",
    "topSkills": "Top Skills by Maturity",
    "categoryTitle": "Categories",
    "skillCloud": "Skill Cloud",
    "noSkills": "No skills recorded yet. Skills will appear here as the agent learns."
  },
  "plugins": {
    "title": "Plugins",
    "loaded": "Loaded Plugins",
    "noPlugins": "No plugins loaded. Configure plugin_dirs in thumbelina.yaml to load plugins.",
    "showReport": "Show Sandbox Report",
    "hideReport": "Hide Sandbox Report",
    "sandboxReport": "Sandbox Validation Report",
    "valid": "valid",
    "invalid": "invalid",
    "violations": "violations"
  },
  "language": {
    "en": "English",
    "zhCN": "中文"
  }
}
```

## 4. UI/UX 设计

### 语言切换入口（两处）

**首选入口：设置面板（Settings）**

在 Settings 页面的 "Data Management" 卡片上方或 "LLM Configuration" 卡片下方，新增一个 "Language" 设置卡片或行内选择器：

```
┌─────────────────────────────────┐
│  Settings                       │
│                                 │
│  ┌─ LLM Configuration ─────────┐│
│  │  LLM Provider: [OpenAI ▼]   ││
│  │  ...                         ││
│  └──────────────────────────────┘│
│                                 │
│  ┌─ Language ──────────────────┐│
│  │  Interface Language: [中文▼]││
│  └──────────────────────────────┘│
│                                 │
│  ┌─ User Profile ──────────────┐│
│  └──────────────────────────────┘│
│  ┌─ Data Management ───────────┐│
│  └──────────────────────────────┘│
└─────────────────────────────────┘
```

**辅助入口：Header 导航栏（可选）**

在 Header 右侧 ThemeToggle 旁边，增加一个语言切换下拉按钮（与主题切换类似），方便快速切换：

```
┌─ Header ───────────────────────────────────────┐
│  ● Thumbelina   Chat Tasks ...   [🌐] [🌙]    │
└────────────────────────────────────────────────┘
```

考虑到项目当前 UI 偏简洁，**实现第一阶段仅在 Settings 面板提供切换入口**，Header 的快捷按钮可作为后续优化。

### 切换行为

1. 用户在 Settings 中选择目标语言
2. 立即写入 localStorage（`thumbelina-locale`）
3. 触发 `LocaleProvider` 中的状态变更
4. 全局 React 树重新渲染（所有 `useTranslation()` 消费最新字典）
5. **无需页面刷新**

### 默认值

- 首次访问时检测浏览器语言（`navigator.language`），若以 `zh` 开头则默认中文，否则英文
- 同时提供切换选项，切换后以 localStorage 为准

## 5. 与现有设置持久化的集成

语言偏好是纯前端 UI 偏好，采用与主题一致的 `localStorage` 持久化方案：

| 持久化方式 | 适用数据 | 理由 |
|-----------|---------|------|
| localStorage | 语言偏好、主题偏好 | 纯 UI 状态，不涉及后端逻辑 |
| API `/api/v1/config` | LLM provider、渠道配置、速率限制 | 影响后端行为，需持久化到 YAML/DB |
| API `/api/v1/config/llm` | 模型切换 | 影响 LLM 调用 |

### 为什么不将语言偏好存到后端？

- 语言是纯前端展示层选项，后端无需感知
- 避免为这个状态增加 API 端点
- 与 ThemeToggle 一致（主题也是 localStorage）
- 切换即时生效，无需后端请求

### 持久化读取顺序

```
1. localStorage.getItem('thumbelina-locale')  // 用户显式选择
2. navigator.language.startsWith('zh') ? 'zh-CN' : 'en'  // 浏览器语言检测
3. 'en'  // 最终兜底
```

## 6. 需要修改的文件清单

### 新增文件

| 文件路径 | 说明 |
|---------|------|
| `frontend/src/i18n/LocaleContext.tsx` | Context 定义 + Provider 组件 |
| `frontend/src/i18n/useLocale.ts` | `useLocale()` 和 `useTranslation()` hooks |
| `frontend/src/i18n/types.ts` | 字典 key 类型定义 |
| `frontend/src/i18n/locales/en.json` | 英文字典 |
| `frontend/src/i18n/locales/zh-CN.json` | 中文字典 |
| `frontend/src/i18n/index.ts` | 统一导出 |

### 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `frontend/src/main.tsx` | 包裹 `<LocaleProvider>` |
| `frontend/src/App.tsx` | Header 中导航 label 用 `t()` 替换，Brand 名称留英文"Thumbelina" |
| `frontend/src/components/Layout/Header.tsx` | `links` 的 `label` 改为调用 `t('nav.xxx')` |
| `frontend/src/components/Layout/ThemeToggle.tsx` | label 文本改用 `t()`（可选，图标为主） |
| `frontend/src/components/Settings/SettingsPanel.tsx` | 1. 所有 UI 文本替换为 `t()` 2. 新增 Language 选择器卡片 |
| `frontend/src/components/Channels/ChannelsPage.tsx` | 所有 UI 文本替换为 `t()` |
| `frontend/src/components/Plugins/PluginsPage.tsx` | 所有 UI 文本替换为 `t()` |
| `frontend/src/components/Tasks/TaskManager.tsx` | 所有 UI 文本替换为 `t()` |
| `frontend/src/components/Dream/DreamViewer.tsx` | 所有 UI 文本替换为 `t()` |
| `frontend/src/components/Memory/MemoryViewer.tsx` | 所有 UI 文本替换为 `t()` |
| `frontend/src/components/Chat/ChatWindow.tsx` | 状态文本、空状态提示替换为 `t()` |
| `frontend/src/components/Chat/MessageList.tsx` | 文本替换 |
| `frontend/src/components/Chat/InputBox.tsx` | placeholder 替换（如有） |
| `frontend/src/components/Layout/Sidebar.tsx` | 空状态文本替换为 `t()` |
| `frontend/src/App.test.tsx` | 更新断言文本，或切换为 `data-testid` 断言 |
| 各组件 `.test.tsx` 文件 | 按需更新测试断言 |

### 总计

- **新增 6 个文件**
- **修改约 18-20 个文件**

## 7. 核心实现细节

### LocaleContext 设计

```tsx
// LocaleContext.tsx
import { createContext, useState, useEffect, useCallback, type ReactNode } from 'react'

type Locale = 'en' | 'zh-CN'

interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string) => string
}

const STORAGE_KEY = 'thumbelina-locale'
const DEFAULT_LOCALE: Locale = 'en'

function getInitialLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'zh-CN') return stored
  } catch { /* ignore */ }
  // 浏览器语言检测
  if (typeof navigator !== 'undefined' && navigator.language.startsWith('zh')) {
    return 'zh-CN'
  }
  return DEFAULT_LOCALE
}
```

### 使用方式

```tsx
// 在任意组件中
import { useTranslation } from '../../i18n'

function MyComponent() {
  const { t } = useTranslation()
  return <h1>{t('settings.title')}</h1>
}
```

### 替换模式

对于包含动态值的字符串（如 `"Switched to ${provider}/${model}"`），保持简单字符串拼接，字典中存模板：

```json
{
  "settings": {
    "switchedTo": "Switched to {provider}/{model}"
  }
}
```

`t()` 函数支持参数插值：

```ts
t('settings.switchedTo', { provider: 'openai', model: 'gpt-4o' })
// → "Switched to openai/gpt-4o"
```

## 8. 实施步骤与优先级

### Phase 1 — 基础设施（1-2 小时）
1. 创建 `frontend/src/i18n/` 目录结构
2. 实现 `LocaleContext` + `useTranslation` Hook
3. 创建 `en.json` 和 `zh-CN.json` 字典
4. 在 `main.tsx` 包裹 Provider

### Phase 2 — 核心页面（2-3 小时）
5. 替换 SettingsPanel 文本 + 新增语言选择器
6. 替换 Header 导航文本
7. 替换 ChatWindow / Sidebar 文本

### Phase 3 — 其余页面（2-3 小时）
8. 替换 ChannelsPage 文本
9. 替换 PluginsPage 文本
10. 替换 TaskManager / DreamViewer / MemoryViewer 文本

### Phase 4 — 测试与验证（1 小时）
11. 更新受影响的 test 文件
12. 验证切换即时生效
13. 验证刷新后偏好保留

## 9. 风险与兼容性考虑

### 风险点

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| 字典遗漏 key | 页面上显示 key 名而非文本（如 `nav.chat`） | 使用 TypeScript 类型约束确保 key 完整，添加 fallback 显示为 key 名 |
| 测试断言硬编码英文文本 | 切换语言后测试失败 | 将文本断言改为 `data-testid` 断言，或仅在默认 locale 下断言文本 |
| CSS 样式适应性 | 中文文本通常比英文短（同样含义占用更少字符宽度） | 中文短文本不影响布局；如有需要可使用 `min-width` 确保按钮宽度 |
| 动态参数字符串 | 参数顺序在不同语言中可能不同 | 支持位置参数或命名参数插值 |
| 第三方组件文本 | 部分第三方组件（如 qrcode.react）不涉及文本 | 无需处理 |

### 兼容性考虑

- **渐进增强**：不引入任何外部依赖，字典加载失败时 fallback 到英文（en.json 内联在 bundle 中）
- **测试友好**：Provider 可独立测试，组件可通过 Mock Provider 测试不同语言
- **与主题系统无冲突**：locale 与 theme 是两个独立的 Context，互不干扰
- **React StrictMode 兼容**：Context 和 Hook 实现均为标准 React API
- **SSR 兼容**（如需）：检测 `typeof window === 'undefined'` 跳过 localStorage 操作，使用默认 locale

## 10. 后期可能的扩展

- **Header 快捷切换按钮**：与 ThemeToggle 并排显示语言选择下拉
- **更多语言支持**：新增 `.json` 文件即可扩展
- **RTL 布局支持**：如需支持阿拉伯语等，可扩展为 `direction: 'ltr' | 'rtl'` Context
- **字典热加载**：从服务端动态加载字典文件（当前不需要）
