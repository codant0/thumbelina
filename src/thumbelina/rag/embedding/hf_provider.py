"""hugging face 嵌入模型实现"""

import torch

import chromadb
from huggingface_hub import try_to_load_from_cache
from pathlib import Path
from sentence_transformers import SentenceTransformer
from thumbelina.rag.embedding.base import EmbeddingModel
from thumbelina.rag.ingestion.chunker import RecursiveChunker
from thumbelina.rag.ingestion.loader import TextLoader
from thumbelina.rag.knowledge_base.models import Chunk


def save_embeddings(chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    # 将索引写入向量数据库中，写入内容包含：原始文本内容、向量索引、id
    chromadb_client = chromadb.EphemeralClient()
    chromadb_collection = chromadb_client.get_or_create_collection(
        name="default")
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        chromadb_collection.add(
            documents=chunk.content,
            embeddings=[embedding],
            ids=[str(i)],
        )


class HuggingFaceEmbedding(EmbeddingModel):
    """通过sentence-transformers使用本地模型"""

    def __init__(self, model_name: str = "Qwen/Qwen3-Embedding-0.6B"):
        super().__init__()
        # 检查 HuggingFace 缓存中是否存在该模型的快照目录
        cached = try_to_load_from_cache(model_name, "config.json")
        if isinstance(cached, str) and Path(cached).exists():
            # 缓存存在，拿到快照目录（config.json 所在目录的父级）
            snapshot_dir = str(Path(cached).parent)
            print(f"使用本地缓存模型: {snapshot_dir}")
            self.model = SentenceTransformer(
                snapshot_dir, local_files_only=True)
        else:
            print(f"本地未找到缓存，从 HuggingFace Hub 下载: {model_name}")
            self.model = SentenceTransformer(model_name)

    def embed(self, chunk: Chunk) -> list[float]:
        """单文本向量化"""
        embeddings = self.model.encode(chunk.content).flatten().tolist()
        save_embeddings([chunk], [embeddings])
        return embeddings

    def embed_batch(self, chunks: list[Chunk]) -> list[list[float]]:
        """批量文本向量化"""
        embeddings = self.model.encode(
            [str(x.content) for x in chunks]).tolist()
        save_embeddings(chunks, embeddings)
        return embeddings


if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent
    TEST_FILE = str(BASE_DIR / ".." / "demo" / "data" / "doc.md")
    loader = TextLoader()
    documents = loader.load(TEST_FILE)
    for i, document in enumerate(documents):
        # 递归按分隔符切块
        recursive_chunker = RecursiveChunker()
        chunks = recursive_chunker.chunk(document)
        first_chunk = chunks[0]
        embedding_model = HuggingFaceEmbedding()
        first_embed_vlaue = embedding_model.embed(first_chunk)
        print(f"size: {len(first_embed_vlaue)}, value: {first_embed_vlaue}")

        all_embed_value = embedding_model.embed_batch(chunks)
        print(f"size: {len(all_embed_value)}")
