"""文本分块策略：将长文档拆分为适合检索的片段。

规划中的策略
-------------
- FixedSizeChunker：按固定字符/词元数切分，支持重叠
- RecursiveChunker：递归按分隔符切分（段落 → 句子 → 子句）
- SemanticChunker：利用 embedding 相似度在语义边界处切分
"""

import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from thumbelina.rag.common.models import Chunk, Document
from thumbelina.rag.ingestion.loader import TextLoader


class Chunker(ABC):
    """分块器"""

    @abstractmethod
    def chunk(self, document: Document) -> list[Chunk]:
        """分块"""


def _page_metadata(document: Document, start: int, end: int) -> dict[str, int]:
    """根据 chunk 在正文中的偏移区间反查覆盖的页码范围。

    分页信息以 chunk 元数据形式记录（page_start/page_end），
    而非插入正文，避免页码标记割裂跨页语义、污染向量。
    无分页信息的文档（如纯文本）返回空 dict。
    """
    page_range = document.page_range_for(start, end)
    if page_range is None:
        return {}
    return {"page_start": page_range[0], "page_end": page_range[1]}


class FixedSizeChunker(Chunker):
    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        super().__init__()
        self.chunk_size = chunk_size
        self.overlap = overlap

        if self.overlap >= chunk_size:
            raise ValueError(
                f"Fixed size chunker overlap:{overlap} is bigger than chunk_size:{chunk_size}"
            )

    def chunk(self, document: Document) -> list[Chunk]:
        text = document.content
        chunks: list[Chunk] = []

        start: int = 0
        index: int = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            slice = text[start:end]
            chunk = Chunk(
                id=uuid.uuid4().hex,
                document_id=document.id,
                content=slice,
                metadata=json.dumps(
                    {
                        "source_uri": document.source_uri,
                        "document_type": document.document_type.value,
                        "name": document.name,
                        "start": start,
                        "end": end,
                        "length": len(slice),
                        "chunk_index": index,
                        **_page_metadata(document, start, end),
                    }
                ),
                knowledge_base_id=document.knowledge_base_id,
            )
            index += 1
            start = start + self.chunk_size - self.overlap
            chunks.append(chunk)
        return chunks


class RecursiveChunker(Chunker):
    """递归按分隔符切分：段落 → 行 → 句 → 子句 → 词 → 字符。

    设计要点：
    - 分隔符按语义边界从粗到细排列，优先在高层级边界切分；
    - 分隔符保留在前一段末尾，不丢失标点/换行；
    - 字符级 ``""`` 兜底保证任何文本都能切开，不再截断丢内容；
    - 碎片合并为接近 ``max_size`` 的块，相邻块间保留 ``overlap`` 衔接上下文；
    - metadata 记录 start/end/chunk_index，偏移连续可反查页码。
    """

    default_separators: list[str] = [
        "\n\n",  # 段落
        "\n",  # 换行
        "。",
        "！",
        "？",
        "；",  # 中文句末/分句
        ". ",
        "! ",
        "? ",
        "; ",  # 英文句末（带空格，避免误切 3.14 / e.g.）
        "，",
        ", ",
        " ",  # 子句 / 词边界
        "",  # 字符级兜底
    ]
    default_max_size: int = 512

    def __init__(
        self,
        separators: list[str] | None = None,
        max_size: int = default_max_size,
        overlap: int | None = None,
        length_function: Callable[[str], int] = len,
    ):
        super().__init__()
        if max_size <= 0:
            raise ValueError(f"RecursiveChunker max_size must be positive: {max_size}")
        self.max_size = max_size
        self.overlap = max_size // 8 if overlap is None else overlap
        if not 0 <= self.overlap < max_size:
            raise ValueError(
                f"RecursiveChunker overlap:{self.overlap} must satisfy 0 <= overlap < "
                f"max_size:{max_size}"
            )
        self.length_function = length_function
        # 拷贝一份，避免别名到类属性/调用方列表被意外修改
        seps = list(separators) if separators is not None else list(self.default_separators)
        if not seps or seps[-1] != "":
            seps.append("")  # 保证字符级兜底存在，否则超长无分隔符文本会被截断丢失
        self.separators = seps

    def chunk(self, document: Document) -> list[Chunk]:
        pieces = self._split(document.content, self.separators)
        merged = self._merge(pieces)
        return [
            self._build_chunk(document, text, start, end, index)
            for index, (text, start, end) in enumerate(merged)
        ]

    # ------------------------------------------------------------------
    # 递归切分
    # ------------------------------------------------------------------

    def _split(self, text: str, separators: list[str]) -> list[tuple[str, int]]:
        """递归切分，返回 (片段, 片段相对 text 的起始偏移)，逐层累加可还原绝对偏移。"""
        if not text:
            return []
        if self.length_function(text) <= self.max_size:
            return [(text, 0)]
        if not separators:
            # 防御性兜底：正常不可达（"" 兜底保证递归时分隔符列表非空）
            return [(text[i : i + self.max_size], i) for i in range(0, len(text), self.max_size)]

        # 选当前层级第一个真正出现的分隔符；"" 必然命中
        sep_index = next(
            (i for i, s in enumerate(separators) if s == "" or s in text),
            len(separators) - 1,
        )
        separator = separators[sep_index]
        remaining = separators[sep_index + 1 :]

        pieces: list[tuple[str, int]] = []
        for part, offset in self._split_by(text, separator):
            if not part.strip():
                continue  # 过滤连续分隔符产生的纯空白碎片
            if self.length_function(part) <= self.max_size:
                pieces.append((part, offset))
                continue
            # 超长片段用更细分隔符继续切，并把子偏移换算回本层坐标系
            for sub, sub_offset in self._split(part, remaining):
                pieces.append((sub, offset + sub_offset))
        return pieces

    @staticmethod
    def _split_by(text: str, separator: str) -> list[tuple[str, int]]:
        """按分隔符切分，分隔符保留在前一段末尾，返回 (片段, 偏移)。"""
        if separator == "":
            return [(ch, i) for i, ch in enumerate(text)]
        parts: list[tuple[str, int]] = []
        start = 0
        while True:
            idx = text.find(separator, start)
            if idx == -1:
                if start < len(text):
                    parts.append((text[start:], start))
                return parts
            end = idx + len(separator)
            parts.append((text[start:end], start))
            start = end

    # ------------------------------------------------------------------
    # 合并与 overlap
    # ------------------------------------------------------------------

    def _merge(self, pieces: list[tuple[str, int]]) -> list[tuple[str, int, int]]:
        """把碎片合并为接近 max_size 的块，块间保留 overlap。

        overlap 按片段粒度回溯（不断在句子中间），返回 (块文本, 起始偏移, 结束偏移)。
        被过滤的空白碎片会在片段间留下空隙：块不能跨越空隙合并，
        否则块内容不再等于原文切片，偏移/页码反查都会失真。
        注意：合并按"片段长度之和"估算，若 length_function 非纯加性
        （如带特殊符的 tokenizer），结果可能有少量偏差。
        """
        chunks: list[tuple[str, int, int]] = []
        current: list[tuple[str, int]] = []
        current_len = 0
        current_end = 0

        for part, offset in pieces:
            part_len = self.length_function(part)
            contiguous = not current or offset == current_end
            if current and (current_len + part_len > self.max_size or not contiguous):
                chunks.append(self._finish(current))
                overlap_pieces: list[tuple[str, int]] = []
                overlap_len = 0
                # 仅片段连续时继承上一块尾部作为 overlap，跨空隙继承会令块内容≠原文切片
                if contiguous:
                    for prev in reversed(current):
                        prev_len = self.length_function(prev[0])
                        if (
                            overlap_len + prev_len > self.overlap
                            or overlap_len + prev_len + part_len > self.max_size
                        ):
                            break
                        overlap_pieces.insert(0, prev)
                        overlap_len += prev_len
                current, current_len = overlap_pieces, overlap_len
            current.append((part, offset))
            current_len += part_len
            current_end = offset + len(part)

        # 末尾的小碎片块不做并入（并入会与 overlap 内容重复），保留即可
        if current:
            chunks.append(self._finish(current))
        return chunks

    @staticmethod
    def _finish(current: list[tuple[str, int]]) -> tuple[str, int, int]:
        text = "".join(part for part, _ in current)
        start = current[0][1]
        end = current[-1][1] + len(current[-1][0])
        return text, start, end

    # ------------------------------------------------------------------
    # 构块
    # ------------------------------------------------------------------

    @staticmethod
    def _build_chunk(
        document: Document, text: str, start: int, end: int, chunk_index: int
    ) -> Chunk:
        return Chunk(
            id=uuid.uuid4().hex,
            document_id=document.id,
            content=text,
            metadata=json.dumps(
                {
                    "source_uri": document.source_uri,
                    "document_type": document.document_type.value,
                    "name": document.name,
                    "start": start,
                    "end": end,
                    "length": len(text),
                    "chunk_index": chunk_index,
                    **_page_metadata(document, start, end),
                },
                ensure_ascii=False,
            ),
            knowledge_base_id=document.knowledge_base_id,
        )


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent
    TEST_FILE = str(BASE_DIR / ".." / "demo" / "data" / "doc.md")
    loader = TextLoader()
    documents = loader.load(TEST_FILE)
    for i, document in enumerate(documents):
        # 递归按分隔符切块
        recursive_chunker = RecursiveChunker()
        for i, c in enumerate(recursive_chunker.chunk(document)):
            print(f"chunk index: {i}, content: {c}")

        # 固定长度切块
        # fix_size_chunker = FixedSizeChunker()
        # for i, c in enumerate(fix_size_chunker.chunk(document)):
        #     print(f"chunk index: {i}, content: {c}")
