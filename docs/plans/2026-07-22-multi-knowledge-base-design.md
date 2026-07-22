# 多知识库管理 — 设计文档

**日期**: 2026-07-22
**状态**: 已批准

## 背景

当前 RAG 模块仅支持 id=0 的"通用知识库"。`KnowledgeBaseRepository`（`rag/knowledge_base/repository.py`）只是一个空壳文档字符串。需要补齐知识库管理能力，支持多个知识库的创建、查询、删除，以及文档元数据的 CRUD。

## 设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 数据持久化 | 混合方案：SQLAlchemy ORM 存元数据 + ChromaDB 存向量 | 复用现有基础设施，元数据关系查询用 SQL 更自然 |
| RAG 模块独立性 | RAG 自建 ORM Base + 引擎，不依赖 memory 模块 | 解耦两个模块，便于独立演进 |
| 数据库文件 | 共享同一个 SQLite 文件（thumbelina.db） | 简化部署，减少文件数量 |
| ChromaDB 隔离 | 每个知识库一个 Collection | 天然隔离，删除知识库时直接 drop collection |
| 默认知识库 | 系统启动时自动创建 id="0"，不可删除 | 保证向后兼容，现有代码无需修改 |

## 新增文件结构

```
src/thumbelina/rag/knowledge_base/
├── models.py          # 修改：Pydantic 模型 id 类型修正
├── orm_models.py      # 新增：SQLAlchemy ORM（独立 Base）
├── db.py              # 新增：引擎/会话/初始化
└── repository.py      # 重写：完整 Repository 实现

src/thumbelina/rag/embedding/
└── store_manager.py   # 新增：ChromaStoreManager

tests/test_rag/
├── test_orm_models.py          # 新增
├── test_repository.py          # 新增
└── test_embedding/
    └── test_store_manager.py   # 新增
```

## 模型设计

### SQLAlchemy ORM（`orm_models.py`）

**KnowledgeBaseRecord**:
| 字段 | 类型 | 约束 |
|------|------|------|
| id | String(36) | PK |
| name | String(200) | NOT NULL |
| description | Text | nullable |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate=now() |

**DocumentRecord**:
| 字段 | 类型 | 约束 |
|------|------|------|
| id | String(36) | PK |
| knowledge_base_id | String(36) | FK → knowledge_bases.id, NOT NULL |
| name | String(500) | NOT NULL |
| source_uri | String(1000) | NOT NULL |
| doc_type | String(20) | NOT NULL |
| chunk_count | Integer | default=0 |
| created_at | DateTime | server_default=now() |

### Pydantic 模型修改（`models.py`）

- `KnowledgeBase.id`: `str = 0` → `str = "0"`（修复类型不一致）
- 注释更新：移除"当前只支持id 0"

## Repository 层

### KnowledgeBaseRepository

- 构造接收 `db_url: str`，内部创建引擎和表
- 方法均为同步实现 + `asyncio.to_thread` 包装的异步接口
- `delete("0")` 抛出 `ValueError`

### DocumentRepository

- 同一引擎/会话工厂
- `list_by_kb(kb_id)` 按知识库列出文档
- `delete_by_kb(kb_id)` 级联删除某知识库下所有文档记录

## ChromaStoreManager

- 构造接收 `chromadb.Client` 实例
- `get_or_create_store(kb_id) -> ChromaVectorStore`：collection 名 `rag_kb_{kb_id}`
- `delete_store(kb_id)`：删除对应 collection
- `list_stores() -> list[str]`：列出所有 rag_kb_ 前缀的 collection

## 默认知识库保护

1. `init_rag_db()` 在 `create_all()` 后检查 id="0" 是否存在
2. 不存在则自动插入默认记录
3. `KnowledgeBaseRepository.delete("0")` 抛 `ValueError("通用知识库不可删除")`
