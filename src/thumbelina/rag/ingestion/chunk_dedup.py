"""分块级去重器。

三级漏斗策略（替换模式）：

    1. SHA-256 精确去重（微秒级）—— 文本完全一致的旧 chunk 指纹被删除，新 chunk 保留
    2. MinHash 近似去重（毫秒级）—— Jaccard ≥ 阈值的旧 chunk 指纹被删除，新 chunk 保留
    3. Embedding 语义去重（秒级，可选）—— 余弦相似度 ≥ 阈值的批次内重复 chunk 被过滤

核心语义：检测到与已有数据重复时，删除旧 chunk，全量写入新 chunk（替换策略）。
批次内仅执行精确去重（完全相同的内容只保留一个），不做近似去重。

典型用法::

    dedup = ChunkDeduplicator(engine)
    all_chunks, stats = dedup.deduplicate(chunks, kb_id="0")
    # stats.removed_old_ids 记录了需要从向量库删除的旧 chunk ID
    vector_store.delete(list(stats.removed_old_ids))
    vector_store.add(all_chunks, embeddings)
    dedup.register_chunks(all_chunks)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

import numpy as np
from datasketch import MinHash
from sqlalchemy import Engine, text

from thumbelina.rag.embedding.base import EmbeddingModel
from thumbelina.rag.knowledge_base.models import Chunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------
DEFAULT_JACCARD_THRESHOLD = 0.85
DEFAULT_COSINE_THRESHOLD = 0.95
DEFAULT_NUM_PERM = 128
DEFAULT_SHINGLE_SIZE = 3


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
@dataclass
class ChunkDedupStats:
    """分块去重统计。"""

    input_count: int = 0
    exact_dup_count: int = 0
    minhash_dup_count: int = 0
    embedding_dup_count: int = 0
    output_count: int = 0
    removed_old_ids: set[str] = field(default_factory=set)

    @property
    def total_removed(self) -> int:
        return self.input_count - self.output_count


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------
class ChunkDeduplicator:
    """分块级去重器（替换模式）。

    在 chunk 生成之后、embedding 计算之前执行，
    检测已存在于向量库中的重复或近似 chunk，删除旧记录，保留全部新 chunk。

    Parameters
    ----------
    engine:
        SQLAlchemy 引擎（与主数据库共享）。
    embedder:
        仅第三级语义去重需要。未提供则跳过第三级。
    jaccard_threshold:
        MinHash Jaccard 相似度阈值（0.0~1.0），默认 0.85。
    cosine_threshold:
        Embedding 余弦相似度阈值（0.0~1.0），默认 0.95。
    num_perm:
        MinHash 排列数，越大越准确但签名越大，默认 128。
    shingle_size:
        字符 n-gram 大小，默认 3。
    enable_exact:
        是否启用第一级精确去重，默认 True。
    enable_minhash:
        是否启用第二级 MinHash 去重，默认 True。
    enable_embedding:
        是否启用第三级 Embedding 语义去重，默认 False。
    """

    def __init__(
        self,
        engine: Engine,
        embedder: EmbeddingModel | None = None,
        jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
        cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
        num_perm: int = DEFAULT_NUM_PERM,
        shingle_size: int = DEFAULT_SHINGLE_SIZE,
        enable_exact: bool = True,
        enable_minhash: bool = True,
        enable_embedding: bool = False,
    ) -> None:
        self.engine = engine
        self.embedder = embedder
        self.jaccard_threshold = jaccard_threshold
        self.cosine_threshold = cosine_threshold
        self.num_perm = num_perm
        self.shingle_size = shingle_size
        self.enable_exact = enable_exact
        self.enable_minhash = enable_minhash
        self.enable_embedding = enable_embedding and embedder is not None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def deduplicate(self, chunks: list[Chunk], kb_id: str) -> tuple[list[Chunk], ChunkDedupStats]:
        """对一批 chunk 执行分块级去重。

        Parameters
        ----------
        chunks:
            待去重的 chunk 列表。
        kb_id:
            知识库 ID。

        Returns
        -------
        tuple[list[Chunk], ChunkDedupStats]
            去重后的 chunk 列表和统计信息。
        """
        stats = ChunkDedupStats(input_count=len(chunks))

        if not chunks:
            return chunks, stats

        result = list(chunks)

        # 第一级：SHA-256 精确去重
        if self.enable_exact:
            result = self._exact_dedup(result, stats)

        # 第二级：MinHash 近似去重
        if self.enable_minhash and result:
            result = self._minhash_dedup(result, stats)

        # 第三级：Embedding 语义去重（可选）
        if self.enable_embedding and result:
            result = self._embedding_dedup(result, stats)

        stats.output_count = len(result)
        logger.info(
            "分块去重完成: 输入 %d, 精确去重 %d, MinHash去重 %d, Embedding去重 %d, 输出 %d",
            stats.input_count,
            stats.exact_dup_count,
            stats.minhash_dup_count,
            stats.embedding_dup_count,
            stats.output_count,
        )
        return result, stats

    def register_chunks(self, chunks: list[Chunk]) -> None:
        """将已成功入库的 chunk 指纹写入指纹表。

        使用 executemany 批量插入。在 chunks 成功写入 ChromaDB 后调用。
        """
        if not chunks:
            return

        rows: list[dict[str, object]] = []
        for chunk in chunks:
            content_hash: bytes = getattr(chunk, "_content_hash", None)  # type: ignore[assignment]
            if content_hash is None:
                content_hash = self._compute_content_hash(chunk.content)

            minhash_sig: bytes | None = getattr(chunk, "_minhash_sig", None)  # type: ignore[assignment]
            if minhash_sig is None and self.enable_minhash:
                mh = self._compute_minhash_obj(chunk.content)
                minhash_sig = self._serialize_minhash(mh)

            rows.append(
                {
                    "id": chunk.id,
                    "doc_id": chunk.document_id,
                    "kb_id": chunk.knowledge_base_id,
                    "hash": content_hash,
                    "sig": minhash_sig,
                }
            )

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO rag_chunk_fingerprints "
                    "(id, document_id, kb_id, content_hash, minhash_sig) "
                    "VALUES (:id, :doc_id, :kb_id, :hash, :sig)"
                ),
                rows,
            )

    # ------------------------------------------------------------------
    # 第一级：SHA-256 精确去重
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_content_hash(content: str) -> bytes:
        """计算 chunk 内容的 SHA-256 哈希值。"""
        return hashlib.sha256(content.encode("utf-8")).digest()

    def _query_hashes_exist(self, kb_id: str, hashes: list[bytes]) -> set[bytes]:
        """批量查询指定哈希在指纹表中是否已存在。

        利用 B-tree 索引精确查找，不全量加载。
        SQLite 对 IN (...) 参数有上限，需分批查询。
        """
        found: set[bytes] = set()
        batch_size = 500
        with self.engine.connect() as conn:
            for i in range(0, len(hashes), batch_size):
                batch = hashes[i : i + batch_size]
                placeholders = ", ".join(f":h{j}" for j in range(len(batch)))
                params: dict[str, object] = {"kb_id": kb_id}
                params.update({f"h{j}": h for j, h in enumerate(batch)})
                rows = conn.execute(
                    text(
                        f"SELECT content_hash FROM rag_chunk_fingerprints "
                        f"WHERE kb_id = :kb_id AND content_hash IN ({placeholders})"
                    ),
                    params,
                ).fetchall()
                found.update(row[0] for row in rows)
        return found

    def _query_hash_and_ids(
        self, kb_id: str, hashes: list[bytes]
    ) -> list[tuple[str, bytes]]:
        """批量查询匹配哈希的旧 chunk ID 和 content_hash。

        Returns
        -------
        list[tuple[str, bytes]]
            (chunk_id, content_hash) 列表。
        """
        results: list[tuple[str, bytes]] = []
        batch_size = 500
        with self.engine.connect() as conn:
            for i in range(0, len(hashes), batch_size):
                batch = hashes[i : i + batch_size]
                placeholders = ", ".join(f":h{j}" for j in range(len(batch)))
                params: dict[str, object] = {"kb_id": kb_id}
                params.update({f"h{j}": h for j, h in enumerate(batch)})
                rows = conn.execute(
                    text(
                        f"SELECT id, content_hash FROM rag_chunk_fingerprints "
                        f"WHERE kb_id = :kb_id AND content_hash IN ({placeholders})"
                    ),
                    params,
                ).fetchall()
                results.extend((row[0], row[1]) for row in rows)
        return results

    def _remove_fingerprints(self, chunk_ids: list[str]) -> None:
        """从 rag_chunk_fingerprints 表中按 chunk ID 批量删除记录。"""
        if not chunk_ids:
            return
        batch_size = 500
        with self.engine.begin() as conn:
            for i in range(0, len(chunk_ids), batch_size):
                batch = chunk_ids[i : i + batch_size]
                placeholders = ", ".join(f":id{j}" for j in range(len(batch)))
                params: dict[str, object] = {f"id{j}": cid for j, cid in enumerate(batch)}
                conn.execute(
                    text(
                        f"DELETE FROM rag_chunk_fingerprints "
                        f"WHERE id IN ({placeholders})"
                    ),
                    params,
                )

    def remove_fingerprints_by_doc(self, doc_id: str) -> None:
        """删除指定文档关联的所有 chunk 指纹记录。

        供 Indexer 在文档级近似重复删除时调用，
        确保旧文档的指纹不会残留（不依赖 FK CASCADE）。
        """
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM rag_chunk_fingerprints WHERE document_id = :doc_id"),
                {"doc_id": doc_id},
            )

    def _exact_dedup(self, chunks: list[Chunk], stats: ChunkDedupStats) -> list[Chunk]:
        """第一级：SHA-256 精确去重。

        1. 批次内去重（纯内存，同一上传文件中的重复 chunk 只保留第一个）
        2. 跨批次去重：删除已有指纹，保留全部新 chunk（替换策略）
        """
        # --- 批次内去重 ---
        seen: set[bytes] = set()
        unique_chunks: list[Chunk] = []
        for chunk in chunks:
            h = self._compute_content_hash(chunk.content)
            chunk._content_hash = h  # type: ignore[attr-defined]
            if h in seen:
                stats.exact_dup_count += 1
                logger.debug("批次内精确去重: chunk %s", chunk.id[:8])
                continue
            seen.add(h)
            unique_chunks.append(chunk)

        if not unique_chunks:
            return []

        # --- 跨批次去重：删除旧指纹，保留全部新 chunk ---
        kb_id = unique_chunks[0].knowledge_base_id
        candidate_hashes = [c._content_hash for c in unique_chunks]  # type: ignore[attr-defined]
        existing_info = self._query_hash_and_ids(kb_id, candidate_hashes)

        if existing_info:
            old_ids = [row[0] for row in existing_info]
            self._remove_fingerprints(old_ids)
            stats.removed_old_ids.update(old_ids)
            stats.exact_dup_count += len(old_ids)
            logger.debug("跨批次精确去重: 删除 %d 个旧指纹", len(old_ids))

        return unique_chunks

    # ------------------------------------------------------------------
    # 第二级：MinHash 近似去重
    # ------------------------------------------------------------------

    def _compute_minhash_obj(self, text_content: str) -> MinHash:
        """计算文本的 MinHash 对象。

        使用字符 n-gram（shingle），不依赖分词器，对中英文兼容。
        使用 legacy scheme 保证序列化/反序列化一致性。
        """
        m = MinHash(num_perm=self.num_perm, scheme="legacy")
        content_bytes = text_content.encode("utf-8")
        for i in range(len(content_bytes) - self.shingle_size + 1):
            m.update(content_bytes[i : i + self.shingle_size])
        return m

    def _serialize_minhash(self, mh: MinHash) -> bytes:
        """将 MinHash 对象序列化为 bytes。

        datasketch 2.0 移除了 serialize/deserialize，改用 digest() + hashvalues。
        legacy scheme: num_perm × uint64（128 × 8 = 1024 bytes）。
        """
        return mh.digest().tobytes()

    def _deserialize_minhash(self, sig_bytes: bytes) -> MinHash:
        """从 bytes 反序列化为 MinHash 对象。"""
        hashvalues = np.frombuffer(sig_bytes, dtype=np.uint64)
        return MinHash(num_perm=self.num_perm, hashvalues=hashvalues, scheme="legacy")

    def _minhash_dedup(self, candidates: list[Chunk], stats: ChunkDedupStats) -> list[Chunk]:
        """第二级：MinHash 近似去重。

        1. 从指纹表取出已有签名，一次性反序列化为 (chunk_id, MinHash) 对
        2. 对每个候选计算 MinHash，与已有列表比较 Jaccard
        3. 匹配的旧指纹被删除，全部新 chunk 保留（替换策略）
        """
        kb_id = candidates[0].knowledge_base_id

        # 一次性取出并反序列化
        existing_mh: list[tuple[str, MinHash]] = []
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, minhash_sig FROM rag_chunk_fingerprints "
                    "WHERE kb_id = :kb_id AND minhash_sig IS NOT NULL"
                ),
                {"kb_id": kb_id},
            ).fetchall()
            for row in rows:
                existing_mh.append((row[0], self._deserialize_minhash(row[1])))

        logger.debug("MinHash 去重: 已有签名 %d 条", len(existing_mh))

        matched_old_ids: list[str] = []
        for chunk in candidates:
            mh = self._compute_minhash_obj(chunk.content)
            chunk._minhash_sig = self._serialize_minhash(mh)  # type: ignore[attr-defined]

            for old_id, existing in existing_mh:
                if mh.jaccard(existing) >= self.jaccard_threshold:
                    matched_old_ids.append(old_id)
                    stats.minhash_dup_count += 1
                    logger.debug(
                        "MinHash 去重: 删除旧 chunk %s Jaccard=%.3f",
                        old_id[:8],
                        mh.jaccard(existing),
                    )
                    break

        if matched_old_ids:
            self._remove_fingerprints(matched_old_ids)
            stats.removed_old_ids.update(matched_old_ids)

        return candidates

    # ------------------------------------------------------------------
    # 第三级（可选）：Embedding 语义去重
    # ------------------------------------------------------------------

    def _embedding_dedup(self, candidates: list[Chunk], stats: ChunkDedupStats) -> list[Chunk]:
        """第三级：Embedding 语义去重（可选）。

        对候选 chunk 计算 embedding，通过余弦相似度过滤语义重复。
        使用贪心策略：按顺序遍历，与已保留的 chunk 比较，若相似则跳过。
        """
        if not self.embedder or len(candidates) <= 1:
            return candidates

        texts = [c.content for c in candidates]
        embeddings = self.embedder.embed_batch(texts)

        keep_indices: list[int] = []
        for i, emb_i in enumerate(embeddings):
            is_dup = False
            for j in keep_indices:
                sim = self._cosine_similarity(emb_i, embeddings[j])
                if sim >= self.cosine_threshold:
                    is_dup = True
                    stats.embedding_dup_count += 1
                    logger.debug(
                        "语义去重: chunk %s 与 chunk %s 余弦相似度 %.3f",
                        candidates[i].id[:8],
                        candidates[j].id[:8],
                        sim,
                    )
                    break
            if not is_dup:
                keep_indices.append(i)

        return [candidates[i] for i in keep_indices]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
