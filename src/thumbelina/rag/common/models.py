"""知识库数据模型。

------------
- KnowledgeBase：知识库（名称、描述、配置）
- Document：源文档（来源 URI、文档类型、所属知识库）
- Chunk：文档片段（文本内容、向量 ID、元数据、所属文档）
"""

from enum import Enum, auto, unique

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


class PageSpan(BaseModel):
    """某一页文本在 Document.content 中的偏移区间。

    用于分块器根据 chunk 的 [start, end) 偏移反查页码，
    使页码作为 chunk 元数据记录，而不是插入正文（避免割裂跨页语义、污染向量）。
    """

    page: int  # 页码，从 1 开始
    start: int  # 在 content 中的起始偏移（含）
    end: int  # 在 content 中的结束偏移（不含）


class Document(BaseModel):
    """文档，对应硬盘中的物理文件"""

    id: str
    name: str
    source_uri: str
    document_type: DocumentType
    content: str
    # 分页信息（仅 PDF 等分页文档填充）：
    # page_count 为物理总页数；page_text 为有内容页面的文本；
    # page_spans 记录各页文本在 content 中的偏移区间，与 page_text 一一对应
    page_text: list[str] = []
    page_count: int = 0
    page_spans: list[PageSpan] = []

    sha256: bytes
    sim_hash_64: bytes
    knowledge_base_id: str = "0"

    def page_range_for(self, start: int, end: int) -> tuple[int, int] | None:
        """根据 content 中的偏移区间返回覆盖的 (起始页, 结束页)。

        无分页信息的文档（如纯文本）或未命中任何页时返回 None。
        """
        if not self.page_spans:
            return None
        pages = [span.page for span in self.page_spans if span.start < end and span.end > start]
        if not pages:
            return None
        return pages[0], pages[-1]


class Chunk(BaseModel):
    """切片"""

    id: str
    document_id: str
    content: str
    # TODO 暂时直接使用json类型的metadata，待后续结构稳定后再明确
    metadata: str
    knowledge_base_id: str


@unique
class PdfPageType(Enum):
    """PDF页类型"""

    TEXT = auto()
    SCANNED = auto()
    MIXED = auto()
