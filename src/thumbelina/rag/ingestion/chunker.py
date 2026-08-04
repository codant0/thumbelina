"""文本分块策略：将长文档拆分为适合检索的片段。

规划中的策略
-------------
- FixedSizeChunker：按固定字符/词元数切分，支持重叠
- RecursiveChunker：递归按分隔符切分（段落 → 句子 → 子句）
- SemanticChunker：利用 embedding 相似度在语义边界处切分
"""

from abc import ABC, abstractmethod
import json
from pathlib import Path
import uuid

from thumbelina.rag.ingestion.loader import TextLoader
from thumbelina.rag.common.models import Chunk, Document


class Chunker(ABC):
    """分块器"""

    @abstractmethod
    def chunk(self, document: Document) -> list[Chunk]:
        """分块"""


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
                    }
                ),
                knowledge_base_id=document.knowledge_base_id,
            )
            index += 1
            start = start + self.chunk_size - self.overlap
            chunks.append(chunk)
        return chunks


class RecursiveChunker(Chunker):
    """递归按分隔符切分"""

    default_separators: list[str] = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";"]
    default_max_size: int = 512

    def __init__(
        self, separators: list[str] = default_separators, max_size: int = default_max_size
    ):
        super().__init__()
        self.separators = separators
        self.max_size = max_size

    def chunk(self, document: Document) -> list[Chunk]:
        return self.recursive_split(
            document, document.content, separators=self.separators, max_size=self.max_size
        )

    @classmethod
    def build_chunk(cls, document: Document, text: str) -> Chunk:
        return Chunk(
            id=uuid.uuid4().hex,
            document_id=document.id,
            content=text,
            metadata=json.dumps(
                {
                    "source_uri": document.source_uri,
                    "document_type": document.document_type.value,
                    "name": document.name,
                    "length": len(text),
                    # TODO 丢失了start、end、index信息，后续再考虑补回
                    # "start": start,
                    # "end": end,
                    # "chunk_index": index,
                }
            ),
            knowledge_base_id=document.knowledge_base_id,
        )

    @classmethod
    def recursive_split(
        cls, document: Document, text: str, separators: list[str], max_size: int
    ) -> list[Chunk]:
        chunks: list[Chunk] = []

        if not text:
            return chunks

        if len(text) <= max_size:
            chunks.append(cls.build_chunk(document, text))
            return chunks

        for separator in separators:
            texts = text.split(separator)
            if len(texts) > 1:
                for slice in texts:
                    chunks.extend(cls.recursive_split(document, slice, separators[1:], max_size))
                return chunks

        # 若无法再切割了，但依旧过长，兜底-截断
        chunks.append(cls.build_chunk(document, text[:max_size]))
        return chunks


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
