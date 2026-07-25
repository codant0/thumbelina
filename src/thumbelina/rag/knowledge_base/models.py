"""知识库数据模型。

------------
- KnowledgeBase：知识库（名称、描述、配置）
- Document：源文档（来源 URI、文档类型、所属知识库）
- Chunk：文档片段（文本内容、向量 ID、元数据、所属文档）
"""

from enum import Enum

from pydantic import BaseModel


class KnowledgeBase(BaseModel):
    """知识库分组。"""

    id: str = "0"
    name: str = "通用知识库"
    description: str = "通用知识库，默认使用该知识库"


class DocumentType(Enum):
    """文档文件类型，即后缀"""

    TXT = ".txt"
    MARKDOWN = ".md"
    PDF = ".pdf"
    HTM = ".htm"
    HTML = ".html"

    @classmethod
    def from_value(cls, value: str) -> "DocumentType":
        """转枚举"""
        try:
            return cls(value.lower())
        except ValueError as e:
            raise ValueError(f"invalid value: {value}") from e


class Document(BaseModel):
    """文档，对应硬盘中的物理文件"""

    id: str
    name: str
    source_uri: str
    document_type: DocumentType
    content: str
    sha256: str
    sim_hash_64: str
    knowledge_base_id: str = "0"


class Chunk(BaseModel):
    """切片"""

    id: str
    document_id: str
    content: str
    # TODO 暂时直接使用json类型的metadata，待后续结构稳定后再明确
    metadata: str
    knowledge_base_id: str
