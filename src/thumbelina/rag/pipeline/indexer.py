"""文档索引流水线。

协调完整的文档处理流程：

    1. 加载原始文档（loader）
    2. 切分为片段（chunker）
    3. 为每个片段生成向量（embedding model）
    4. 将向量 + 元数据写入向量库（vector store）

各组件通过依赖注入传入，运行时可随时替换，无需修改 Indexer 本身。

典型用法::

    indexer = Indexer(loader, chunker, embedder, vector_store)
    stats = indexer.index("path/to/document.pdf")

输出示例::

    IndexStats(
        document_count=1,
        chunk_count=24,
        indexed_count=24,
        skipped_count=0,
    )

热替换示例::

    indexer.loader = PDFLoader()
    indexer.chunker = SemanticChunker()
    stats_v2 = indexer.index("path/to/another.pdf")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from thumbelina.rag.embedding.base import EmbeddingModel, VectorStore
from thumbelina.rag.ingestion.chunker import Chunker
from thumbelina.rag.ingestion.loader import Loader
from thumbelina.rag.knowledge_base.models import Chunk, Document

logger = logging.getLogger(__name__)


@dataclass
class IndexStats:
    """索引统计信息。"""

    document_count: int = 0
    chunk_count: int = 0
    indexed_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


class Indexer:
    """文档索引流水线：加载 → 分块 → 向量化 → 存储。

    所有组件通过构造函数注入，属性公开可读写，支持运行时热替换。

    Parameters
    ----------
    loader:
        文档加载器，负责从文件/URI 读取原始内容。
    chunker:
        分块器，负责将长文档切分为适合检索的片段。
    embedder:
        向量模型，负责将文本片段编码为稠密向量。
    vector_store:
        向量库，负责持久化存储向量和元数据。
    """

    def __init__(
        self,
        loader: Loader,
        chunker: Chunker,
        embedder: EmbeddingModel,
        vector_store: VectorStore,
    ) -> None:
        self.loader = loader
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store

    def index(self, path: str) -> IndexStats:
        """对单个文件执行完整的索引流程。

        Parameters
        ----------
        path:
            文件路径，具体支持的格式取决于当前注入的 loader。

        Returns
        -------
        IndexStats
            本次索引的统计信息。
        """
        stats = IndexStats()

        # 1. 加载
        documents = self._load(path, stats)
        if not documents:
            return stats

        # 2. 分块 → 3. 向量化 → 4. 写入
        for document in documents:
            chunks = self._chunk(document, stats)
            if not chunks:
                continue
            self._embed_and_store(chunks, stats)

        return stats

    def index_batch(self, paths: list[str]) -> IndexStats:
        """批量索引多个文件。

        Parameters
        ----------
        paths:
            文件路径列表。

        Returns
        -------
        IndexStats
            所有文件的累计索引统计。
        """
        total = IndexStats()
        for path in paths:
            result = self.index(path)
            total.document_count += result.document_count
            total.chunk_count += result.chunk_count
            total.indexed_count += result.indexed_count
            total.skipped_count += result.skipped_count
            total.errors.extend(result.errors)
        return total

    # ------------------------------------------------------------------
    # 内部流水线步骤
    # ------------------------------------------------------------------

    def _load(self, path: str, stats: IndexStats) -> list[Document]:
        """步骤 1：加载文档。"""
        try:
            documents = self.loader.load(path)
        except Exception as exc:
            msg = f"加载失败 [{path}]: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            return []

        if not documents:
            msg = f"未产生文档 [{path}]（文件不存在或格式不支持）"
            logger.warning(msg)
            stats.skipped_count += 1
            return []

        stats.document_count += len(documents)
        return documents

    def _chunk(self, document: Document, stats: IndexStats) -> list[Chunk]:
        """步骤 2：将文档切分为片段。"""
        try:
            chunks = self.chunker.chunk(document)
        except Exception as exc:
            msg = f"分块失败 [{document.name}]: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            return []

        if not chunks:
            logger.warning("分块为空 [%s]", document.name)
            stats.skipped_count += 1
            return []

        stats.chunk_count += len(chunks)
        return chunks

    def _embed_and_store(self, chunks: list[Chunk], stats: IndexStats) -> None:
        """步骤 3 + 4：向量化并写入向量库。"""
        texts = [c.content for c in chunks]

        try:
            embeddings = self.embedder.embed_batch(texts)
        except Exception as exc:
            msg = f"向量化失败: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        try:
            self.vector_store.add(chunks, embeddings)
        except Exception as exc:
            msg = f"写入向量库失败: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        stats.indexed_count += len(chunks)
