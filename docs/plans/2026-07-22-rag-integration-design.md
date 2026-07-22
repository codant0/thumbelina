# RAG 集成设计文档

**日期**: 2026-07-22
**状态**: 已批准

## 概述

将已实现的 RAG 模块与主应用连接，实现：
1. **知识库管理页面** — 导航栏新增「个人知识库」入口，支持知识库和文档的 CRUD
2. **聊天窗口知识库选择** — 按对话绑定知识库，选择后自动开启 RAG 检索增强
3. **Agent RAG 集成** — 将检索到的上下文注入 SystemMessage

## 设计决策

| 决策 | 方案 | 理由 |
|------|------|------|
| 知识库选择作用域 | 按对话绑定 | 与 ConversationModelSelector 模式一致 |
| `knowledge_base_id` 存储 | Conversation 表新增字段 | 每个对话独立绑定，无需新表 |
| Agent RAG 注入 | SystemMessage | 与 skill_context、user_context 模式一致 |
| 文档处理 | 同步索引（初版） | 简单直接，后续可改异步 |
| API 路由前缀 | `/api/v1/rag/*` | 与 ARCHITECTURE.md 规划一致 |

## 架构图

```
┌──────────────────────────────────────────────────┐
│                  前端 (React)                      │
│                                                    │
│  Header: [..., knowledge-base]                     │
│                                                    │
│  ┌──────────────────┐  ┌────────────────────────┐ │
│  │ KnowledgeBasePage│  │ ChatWindow              │ │
│  │  ├─ 知识库列表     │  │  ├─ status bar          │ │
│  │  ├─ 创建/编辑     │  │  ├─ KBSelector ← 新增   │ │
│  │  ├─ 文档上传/列表  │  │  ├─ ModelSelector       │ │
│  │  └─ 检索测试      │  │  └─ InputBox            │ │
│  └──────────────────┘  └────────────────────────┘ │
└────────────────────┬─────────────────────────────┘
                     │ HTTP / WebSocket
┌────────────────────▼─────────────────────────────┐
│                 FastAPI 后端                       │
│                                                    │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────┐│
│  │routes/rag│  │ Agent.run()  │  │ websocket   ││
│  │ CRUD     │  │ + RAG context│  │ + kb_id     ││
│  └────┬─────┘  └──────┬───────┘  └──────┬──────┘│
│       │               │                 │       │
│       ▼               ▼                 ▼       │
│  ┌──────────────────────────────────────────┐   │
│  │           rag/ 模块 (已有)                 │   │
│  │  KBRepo → Indexer → Retriever → Formatter │   │
│  └──────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

## 后端变更

### 1. Conversation 模型扩展

在 `memory/models.py` 的 `Conversation` 表中新增：

```python
knowledge_base_id: Mapped[str | None] = mapped_column(
    String(36), nullable=True, default=None
)
```

同时在 Pydantic schema 和 API 响应中暴露该字段。

### 2. RAG API 路由 (`api/routes/rag.py`)

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/v1/rag/knowledge-bases` | GET | 列出所有知识库 |
| `/api/v1/rag/knowledge-bases` | POST | 创建知识库 |
| `/api/v1/rag/knowledge-bases/{id}` | PUT | 更新知识库 |
| `/api/v1/rag/knowledge-bases/{id}` | DELETE | 删除知识库（级联删除文档和向量） |
| `/api/v1/rag/knowledge-bases/{id}/documents` | GET | 列出知识库下的文档 |
| `/api/v1/rag/knowledge-bases/{id}/documents` | POST | 上传文档 + 自动索引 |
| `/api/v1/rag/documents/{doc_id}` | DELETE | 删除单个文档 |
| `/api/v1/rag/query` | POST | 检索测试（返回 top-k 片段） |

### 3. Agent 集成 (`agent/graph.py`)

新增 `_get_rag_context(query, knowledge_base_id)` 方法：

```python
async def _get_rag_context(self, query: str, kb_id: str) -> str | None:
    # 1. 获取知识库对应的向量存储
    # 2. 用 SimpleRetriever 检索 top-k 片段
    # 3. 用 ContextFormatter 格式化为上下文
    # 4. 返回上下文字符串
```

在 `run()` 和 `stream()` 中，在 skill_context 之前注入 RAG context：

```python
rag_context = await self._get_rag_context(user_input, kb_id)
if rag_context:
    initial_messages.append(SystemMessage(content=rag_context))
```

### 4. App 初始化 (`api/app.py`)

在 lifespan 中初始化 RAG 相关组件：
- 复用主数据库引擎初始化 RAG 表 (`init_rag_db`)
- 创建 KnowledgeBaseRepository、DocumentRepository
- 创建 EmbeddingRegistry、ChromaStoreManager
- 注入到 FastAPI app.state

## 前端变更

### 1. 导航栏新增入口

`Header.tsx` 的 `Page` 类型新增 `'knowledge-base'`，图标使用 `BookOpen`。

### 2. KnowledgeBasePage 页面

结构参照现有页面模式（page-container / card / form-group）：
- 左侧面板：知识库列表（名称、描述、文档数量）
- 右侧面板：选中知识库的详情
  - 编辑表单（名称、描述）
  - 文档列表表格（文件名、类型、chunk 数、时间、操作）
  - 上传区域（支持 .txt/.md 文件）
  - 检索测试面板

### 3. KnowledgeBaseSelector 组件

位于 ChatWindow 的 status bar 中，与 ModelSelector 同级：
- 下拉选择：`不使用知识库` / 知识库列表
- 选择后通过 PATCH API 保存到 Conversation
- 切换对话时自动加载对应绑定

### 4. i18n

在 `locales/zh-CN.json` 和 `locales/en.json` 中新增 `nav.knowledgeBase`、`knowledgeBase.*` 翻译。

## 数据流

**文档上传 → 索引**:
```
POST 文件 → TextLoader.load() → Chunker.chunk()
  → EmbeddingModel.embed_batch() → VectorStore.add()
  → 保存 DocumentRecord → 返回 Document 信息
```

**聊天 → RAG 增强**:
```
用户消息 → 查找 conversation.knowledge_base_id
  → 如有: Retriever.retrieve(query) → ContextFormatter.format()
  → 注入 SystemMessage → Agent 正常处理
```
