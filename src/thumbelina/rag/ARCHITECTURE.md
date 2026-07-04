# Thumbelina RAG 模块架构文档

## 概述

RAG（Retrieval-Augmented Generation）模块为 Thumbelina 项目提供**外部知识检索**能力。
与现有的 `memory/` 模块（专注于**对话历史**的记忆与搜索）不同，`rag/` 模块专注于**非对话来源**的文档知识管理——让 Agent 能够读取 PDF、网页、代码库等外部文档，并在对话中引用这些知识来回答问题。

### 设计原则

| 原则 | 说明 |
|------|------|
| **独立性** | RAG 模块内部各子组件松耦合，不依赖主项目的 Agent 循环，可独立学习和测试 |
| **渐进式** | 从最简的「加载→分块→检索→注入」链路起步，逐步叠加高级策略 |
| **可替换性** | 每个接口层（加载器、分块器、向量化模型、检索策略）均设计为可插拔 |

---

## 整体架构

```
┌─────────────────────────────────────────────────────┐
│                     RAG 模块                          │
│                                                      │
│  ┌──────────┐   ┌───────────┐   ┌───────────────┐   │
│  │ 知识库管理 │   │  索引流水线 │   │   检索层       │   │
│  │ knowledge │──▶│  pipeline │──▶│  retrieval    │   │
│  │ _base/    │   │           │   │               │   │
│  └──────────┘   └───────────┘   └───────┬───────┘   │
│       │              │                  │           │
│       ▼              ▼                  ▼           │
│  ┌─────────────────────────────────────────────┐    │
│  │              摄取层 (ingestion)               │    │
│  │   ┌──────────┐          ┌──────────┐        │    │
│  │   │ loader   │─── text ─▶│ chunker  │        │    │
│  │   └──────────┘          └────┬─────┘        │    │
│  └──────────────────────────────┼──────────────┘    │
│                                 │                    │
│                                 ▼                    │
│  ┌─────────────────────────────────────────────┐    │
│  │           向量化层 (embedding)                │    │
│  │   ┌──────────┐     ┌──────────────┐         │    │
│  │   │  registry │────▶│ EmbeddingModel│         │    │
│  │   └──────────┘     └──────┬───────┘         │    │
│  └───────────────────────────┼─────────────────┘    │
│                              │                       │
│                              ▼                       │
│  ┌─────────────────────────────────────────────┐    │
│  │          向量存储 (复用 memory/vector/)        │    │
│  │   ChromaDB / 其他 VectorStore 实现            │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
         │
         ▼  （后续接入 Agent）
┌────────────────────┐
│  Thumbelina Agent   │
│  ┌──────────────┐   │
│  │ _get_rag_    │   │
│  │ context()    │   │
│  └──────┬───────┘   │
│         ▼           │
│  SystemMessage 注入  │
└────────────────────┘
```

### 数据流

```
用户提问
    │
    ▼
[1] 检索阶段（Retrieve）
    ├── 对用户问题进行向量化
    ├── 在向量库中检索相似片段
    └── 可选：重排序 / MMR 多样化
    │
    ▼
[2] 增强阶段（Augment）
    ├── 将检索结果格式化为上下文
    ├── 附带来源元数据（文档名、页码等）
    └── 按 token 上限截断
    │
    ▼
[3] 生成阶段（Generate）
    └── Agent 将上下文作为 SystemMessage 注入
         LLM 据此回答问题
```

---

## 子模块详细说明

### 1. `ingestion/` — 摄取层

**作用**：从各种外部来源读取原始文档，并将其切分为适合向量检索的片段。

**包含组件**：

| 文件 | 职责 | 规划状态 |
|------|------|----------|
| `loader.py` | 文档加载器，支持多种格式（文本、PDF、HTML、代码） | 待实现 |
| `chunker.py` | 文本分块策略，控制块大小、重叠、边界 | 待实现 |

**规划路线**：

1. 先实现 `TextLoader` 和 `FixedSizeChunker`，构建最简链路
2. 加入 `RecursiveChunker`，提升语义完整性
3. 按需加入 `PDFLoader`、`HTMLLoader`
4. 高阶：`SemanticChunker`，在语义边界处切分

---

### 2. `embedding/` — 向量化层

**作用**：将文本转换为向量表示，这是语义检索的基础。

**包含组件**：

| 文件 | 职责 | 规划状态 |
|------|------|----------|
| `base.py` | `EmbeddingModel` 抽象接口，定义 `embed()` 和 `embed_batch()` | 骨架完成 |
| `registry.py` | 模型注册中心，支持按名称获取模型实例 | 待实现 |

**规划路线**：

1. 先对接 `OllamaEmbedding`（与项目已有的 Ollama 提供者一致）
2. 接入 `OpenAIEmbedding`（text-embedding-3-small 起步）
3. 可选：`HuggingFaceEmbedding` 本地模型

**与项目现有模块的关系**：

```
rag/embedding/  ← 独立的 embedding 抽象层
    ↓ 复用
llm/  ← 主项目的 LLM 提供者层（不同职责，但可共享模型资源）
```

---

### 3. `retrieval/` — 检索层

**作用**：给定用户问题，从向量库中召回最相关的文档片段，并格式化为 LLM 可用的上下文。

**包含组件**：

| 文件 | 职责 | 规划状态 |
|------|------|----------|
| `strategies.py` | 多种检索算法（简单 top-k、MMR、混合搜索、重排序） | 待实现 |
| `context_formatter.py` | 将检索到的片段拼接为 LLM 上下文，附带来源标记 | 待实现 |

**规划路线**：

1. `SimpleRetriever`：基于余弦相似度的 top-k 检索，最简方案
2. `HybridRetriever`：关键词 BM25 + 向量检索融合
3. `ReRankRetriever`：用交叉编码器对 top-k 精排
4. `MMRRetriever`：在相关性和多样性之间取平衡

**与现有 `memory/search.py` 的关系**：

```
memory/search.py      — 搜索对话历史（keyword / semantic / hybrid）
rag/retrieval/        — 搜索外部知识（独立的数据源和流程）

两者可共享 VectorStore 接口，但使用不同的 collection 和数据。
```

---

### 4. `pipeline/` — 索引流水线

**作用**：编排完整的文档索引流程——加载→分块→向量化→存储。

**包含组件**：

| 文件 | 职责 | 规划状态 |
|------|------|----------|
| `indexer.py` | 将单个文档从头到尾处理并写入向量库 | 待实现 |

**规划路线**：

1. `Indexer` 基础实现：接收 loader / chunker / embedder / vector_store，串行处理单篇文档
2. 批量索引：支持目录扫描 + 增量更新
3. 可选的异步并行加速

---

### 5. `knowledge_base/` — 知识库管理

**作用**：对已索引的文档进行元数据管理，将文档组织为命名的「知识库」集合。

**包含组件**：

| 文件 | 职责 | 规划状态 |
|------|------|----------|
| `models.py` | KnowledgeBase / Document / Chunk 数据模型 | 待实现 |
| `repository.py` | 元数据 CRUD 持久化层（SQLite） | 待实现 |

**规划路线**：

1. `KnowledgeBase` + `Document` 的基础模型和 CRUD
2. 元数据过滤（检索时按知识库范围限定）
3. 文档版本管理

---

## 与现有 `memory/` 模块的分工

| 维度 | `memory/`（对话记忆） | `rag/`（知识检索） |
|------|----------------------|-------------------|
| **数据来源** | 用户与 Agent 的聊天记录 | 外部文档（PDF、网页、代码等） |
| **数据结构** | Conversation → Message | KnowledgeBase → Document → Chunk |
| **写入时机** | 每次对话自动写入 | 用户主动上传 / 触发索引 |
| **检索目的** | 回忆历史对话上下文 | 查找外部知识回答用户问题 |
| **向量 Collection** | thumbelina（默认） | knowledge（独立 collection） |
| **当前状态** | 已有完整实现 | 新建，待实现 |

**共享部分**：两者共用 `memory/vector/base.py` 的 `VectorStore` 抽象接口，但使用不同的 ChromaDB collection 实例，数据完全隔离。

---

## 后续接入主项目的规划

### 阶段一：独立构建与验证（当前）

- 实现各子模块的核心功能
- 编写单元测试，确保每个组件独立可测
- 不依赖主项目的 Agent 和 API，可独立运行 `pytest`

### 阶段二：Agent 集成

```
修改文件：src/thumbelina/agent/graph.py（ThumbelinaAgent）

新增 _get_rag_context(query: str) → str 方法：
  1. 调用 rag/retrieval 检索相关文档
  2. 将结果格式化为文本
  3. 返回内容供注入为 SystemMessage

在 _build_messages() 中调用 _get_rag_context()：
  if self.rag_enabled and has_query:
      rag_context = await self._get_rag_context(query)
      messages.insert(0, SystemMessage(content=rag_context))
```

### 阶段三：API 与前端集成

**后端 API**（新增 `src/thumbelina/api/routes/rag.py`）：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/v1/rag/knowledge-bases` | GET/POST | 列出/创建知识库 |
| `/api/v1/rag/knowledge-bases/{id}` | DELETE | 删除知识库 |
| `/api/v1/rag/knowledge-bases/{id}/documents` | POST | 上传文档并触发索引 |
| `/api/v1/rag/query` | POST | 检索测试（给定问题，返回 top-k 片段） |

**前端**：
- 新增 `KnowledgeBasePage`，与现有 `MemoryViewer` 同级
- 知识库列表 → 文档上传 → 索引状态 → 检索测试界面

### 阶段四：配置与可开关

```yaml
# thumbelina.yaml
rag:
  enabled: false                  # 默认关闭，用户按需开启
  default_knowledge_base: "main"
  retriever:
    strategy: "hybrid"            # simple / mmr / hybrid / rerank
    top_k: 5
    min_score: 0.5
  embedding:
    provider: "ollama"            # openai / ollama / huggingface
    model: "nomic-embed-text"
```

---

## 实现优先级总结

| 优先级 | 子模块 | 里程碑 |
|--------|--------|--------|
| P0 | `ingestion/loader.py` | 能加载文本文件 |
| P0 | `ingestion/chunker.py` | 能按固定大小分块 |
| P0 | `embedding/` + 检索 | 能向量化并召回相关片段 |
| P0 | `retrieval/context_formatter.py` | 检索结果能喂给 LLM |
| P1 | `pipeline/indexer.py` | 全自动索引单篇文档 |
| P1 | `knowledge_base/` | 知识库元数据管理 |
| P1 | `retrieval/strategies.py` — MMR/Hybrid | 检索质量提升 |
| P2 | Loader 扩展（PDF、HTML） | 支持更多文档类型 |
| P2 | Agent 集成 | 在对话中自动使用 RAG |
| P3 | API + 前端 | 可视化知识库管理 |
| P3 | 配置化、可开关 | 生产就绪 |
