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

    坐标系约定（由加载器建立，消费方不得破坏）：

    - ``content = "\\n".join(各页文本)``，每页文本已经 strip 首尾空白，
      相邻两页之间**有且仅有**一个连接用 ``"\\n"``；
    - 连接 ``"\\n"`` 恰好落在相邻两个 span 的间隙中（即 ``content[前span.end]``），
      **不属于任何一页**；跨页 chunk 覆盖到它时页码反查结果仍正确；
    - span 按页码升序存放、区间互不重叠，页内自带的换行只是普通内容字符；
    - 无可提取文本的空白页被跳过：**页码可能不连续**（如 [1, 3]），
      物理总页数以 ``DocumentLayout.page_count`` 为准。

    正确用法（还原某页文本的唯一合法方式——按偏移切片）::

        page_text = document.content[span.start : span.end]

    误用警示：

    - **禁止**用 ``content.split("\\n")`` 或查找 ``"\\n"`` 来划分页面——
      页内换行与页间连接符无法区分，页边界只存在于本类记录的偏移中；
    - **禁止**假设 ``content[span.end]`` 是下一页文本的开头——
      它是连接 ``"\\n"``（下一页文本从 ``span.end + 1`` 开始），且可能不存在下一页；
    - **禁止**把页码冗余复制进其他结构（如 BlockSpan）——任何区间
      （chunk/表格等）的页码都应经 ``DocumentLayout.page_range_for`` 由偏移反查。
    """

    page: int  # 页码，从 1 开始；空白页被跳过，可能不连续
    start: int  # 在 content 中的起始偏移（含）
    end: int  # 在 content 中的结束偏移（不含）；与下一 span 的间隙为页间连接 "\n"


class BlockSpan(BaseModel):
    """结构化块（表格等）在 Document.content 中的偏移区间。

    供分块器做原子性保护：块内内容不在中间切断。
    不冗余存储页码——块的页码可由 [start, end) 偏移对 page_spans 反查得到，
    坚持"content 偏移为唯一坐标系"，避免坐标复制导致的不一致。
    """

    block_type: str  # 块类型，当前仅 "table"
    start: int  # 在 content 中的起始偏移（含）
    end: int  # 在 content 中的结束偏移（不含）
    heading_path: list[str] = []  # 块上方的标题路径，如 ["产品规格", "价格表"]
    header_row: list[str] = []  # 表头单元格，供长表按行组拆分时复用


class DocumentLayout(BaseModel):
    """加载阶段产出的布局结构信息。

    摄入流水线（loader → chunker）的瞬态数据，不随 DocumentRecord 持久化：
    chunk 生成后，页码等信息已落入 chunk metadata，本结构即可丢弃。
    无布局信息的文档类型（TXT/HTML 等）对应 Document.layout = None。
    """

    page_count: int = 0  # 物理总页数（含被跳过的空页，不可由 page_spans 推出）
    page_spans: list[PageSpan] = []  # 坐标系：偏移区间 → 页码
    block_spans: list[BlockSpan] = []  # 结构块：表格等，供切块原子性保护

    def page_range_for(self, start: int, end: int) -> tuple[int, int] | None:
        """根据 content 中的偏移区间返回覆盖的 (起始页, 结束页)。

        无分页信息或未命中任何页时返回 None。
        """
        if not self.page_spans:
            return None
        pages = [span.page for span in self.page_spans if span.start < end and span.end > start]
        if not pages:
            return None
        return pages[0], pages[-1]


class Document(BaseModel):
    """文档，对应硬盘中的物理文件"""

    id: str
    name: str
    source_uri: str
    document_type: DocumentType
    content: str
    # 加载阶段产出的布局结构信息（PDF/Markdown 等填充）；无布局信息时为 None
    layout: DocumentLayout | None = None

    sha256: bytes
    sim_hash_64: bytes
    knowledge_base_id: str = "0"


class Chunk(BaseModel):
    """切片"""

    id: str
    document_id: str
    content: str
    # 暂时直接使用json类型的metadata，待后续结构稳定后再明确
    metadata: str
    knowledge_base_id: str


@unique
class PdfPageType(Enum):
    """PDF页类型"""

    TEXT = auto()
    SCANNED = auto()
    MIXED = auto()
