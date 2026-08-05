"""知识库子模块：管理已索引文档的集合。

- models: Pydantic 数据模型（KnowledgeBase, Document, Chunk, DocumentType）
- orm_models: SQLAlchemy ORM 模型（RagBase, KnowledgeBaseRecord, DocumentRecord）
- repository: 持久化层（KnowledgeBaseRepository, DocumentRepository）
- db: 数据库初始化（init_rag_db）
"""

from thumbelina.rag.common.db import init_rag_db
from thumbelina.rag.common.models import (
    BlockSpan,
    Chunk,
    Document,
    DocumentLayout,
    DocumentType,
    KnowledgeBase,
    PageSpan,
)
from thumbelina.rag.common.orm_models import (
    DocumentRecord,
    KnowledgeBaseRecord,
    RagBase,
)
from thumbelina.rag.common.repository import (
    DocumentRepository,
    KnowledgeBaseRepository,
)

__all__ = [
    "BlockSpan",
    "Chunk",
    "Document",
    "DocumentLayout",
    "DocumentRepository",
    "DocumentRecord",
    "DocumentType",
    "KnowledgeBase",
    "KnowledgeBaseRecord",
    "KnowledgeBaseRepository",
    "PageSpan",
    "RagBase",
    "init_rag_db",
]
