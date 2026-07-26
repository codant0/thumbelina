# 分块级去重设计方案

**日期**: 2026-07-26
**状态**: 待审批
**关联**: `src/thumbelina/rag/RAG.md` 第 126-132 行

## 1. 背景与问题

### 1.1 现状

当前 RAG 模块已实现**文档级去重**（两级漏斗）：

| 层级 | 方法 | 位置 | 效果 |
|------|------|------|------|
| 精确去重 | SHA-256 | `DocumentDeduplicator._check_sha256()` | 完全相同的文件直接跳过 |
| 模糊去重 | SimHash + 汉明距离 | `DocumentDeduplicator._check_simhash()` | 距离 ≤ 3 的相似文档覆盖旧文档 |

但**分块级去重缺失**。当发生以下场景时，向量库中会出现重复 chunk：

1. **跨文档重复**：不同文档（名称不同、SHA256/SimHash 不同）包含相同段落或章节
2. **同文档变体上传**：文档经过微小修改后重新上传（SimHash 距离 > 3 被视为不同文档），其中未改动的大量段落产生重复 chunk
3. **模板文档**：多份 SOP/报告基于同一模板，共享大量固定文本

### 1.2 影响

- **检索质量下降**：top-k 结果中多个 chunk 内容几乎一致，挤占了本可返回其他相关内容的名额
- **LLM 上下文浪费**：有限的 context budget（当前 3000 tokens）被重复信息消耗
- **存储膨胀**：相同的 embedding 向量被重复存储

## 2. 设计目标

| 目标 | 描述 |
|------|------|
| 去重粒度 | chunk 级别（512 字符左右的文本片段） |
| 去重范围 | 同一知识库内跨文档 |
| 准确度 | Jaccard ≥ 0.85 判定为近似重复 |
| 性能影响 | 不显著增加索引延迟（SHA256/MinHash 级别为微秒/毫秒级） |
| 兼容性 | 不改变现有文档级去重逻辑和检索逻辑 |
| 可配置 | 各级阈值和开关可调 |

## 3. 策略总览

沿用 RAG.md 已规划的三级漏斗策略，在分块之后、embedding 之前执行：

```
Load → 文档级 Dedup → Chunk → 【分块级 Dedup】→ Embed → Store → 注册指纹
                                      │
                         ┌──────────────┼──────────────┐
                         ▼              ▼              ▼
                   [1] SHA-256    [2] MinHash    [3] Embedding
                   精确去重       近似去重        语义去重
                  (微秒级)       (毫秒级)        (秒级, 可选)
```

## 4. 详细设计

### 4.1 数据模型：chunk 指纹表

在 SQLite 中新增 `rag_chunk_fingerprints` 表，存储 chunk 的哈希/签名，用于快速查重。

```sql
CREATE TABLE rag_chunk_fingerprints (
    id            TEXT PRIMARY KEY,           -- chunk UUID（与 ChromaDB 中的 chunk id 一致）
    document_id   TEXT NOT NULL,              -- 所属文档 ID
    kb_id         TEXT NOT NULL,              -- 所属知识库 ID
    content_hash  BLOB NOT NULL,              -- chunk 内容的 SHA-256 (32 bytes)
    minhash_sig   BLOB,                       -- MinHash 签名 (128 × uint32 = 512 bytes)
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_chunk_fingerprint_hash ON rag_chunk_fingerprints(content_hash);
CREATE INDEX idx_chunk_fingerprint_kb   ON rag_chunk_fingerprints(kb_id);
CREATE INDEX idx_chunk_fingerprint_doc  ON rag_chunk_fingerprints(document_id);
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT (UUID) | 与 ChromaDB 中存储的 chunk id 一一对应 |
| `document_id` | TEXT | 关联到 `rag_documents.id`，删除文档时级联清理 |
| `kb_id` | TEXT | 冗余字段，便于按知识库批量查询指纹（避免 JOIN） |
| `content_hash` | BLOB (32 bytes) | `hashlib.sha256(content.encode()).digest()` |
| `minhash_sig` | BLOB (512 bytes) | `datasketch.MinHash.serialize()`，128 个排列 × 4 bytes/uint32 |

**设计决策：为什么用独立 SQL 表，而非在 ChromaDB 中存储？**

| 考量 | SQL 指纹表 | ChromaDB 元数据 |
|------|-----------|-----------------|
| SHA256 精确查找 | B-tree 索引，O(log n) | 需全扫描 metadata filter |
| MinHash Jaccard 查询 | SQL 取回签名后本地计算 | ChromaDB 不支持 Jaccard 距离 |
| 存储开销 | 仅存指纹（~544 bytes/chunk） | ChromaDB 已存 embedding（~2.4KB/chunk） |
| 跨数据源一致性 | 与文档表在同一数据库 | 独立数据库，无外键约束 |

### 4.2 核心类：`ChunkDeduplicator`

**文件**：`src/thumbelina/rag/ingestion/chunk_dedup.py`

```python
"""
分块级去重器

三级漏斗策略：SHA-256 精确去重 → MinHash 近似去重 → Embedding 语义去重
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from datasketch import MinHash
from sqlalchemy import Engine, text

from thumbelina.rag.embedding.base import EmbeddingModel
from thumbelina.rag.knowledge_base.models import Chunk

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_JACCARD_THRESHOLD = 0.85   # MinHash 近似去重阈值
DEFAULT_COSINE_THRESHOLD = 0.95    # Embedding 语义去重阈值
DEFAULT_NUM_PERM = 128             # MinHash 排列数
DEFAULT_SHINGLE_SIZE = 3           # 字符 n-gram 大小


@dataclass
class ChunkDedupStats:
    """分块去重统计"""
    input_count: int = 0            # 输入 chunk 数
    exact_dup_count: int = 0        # SHA-256 精确重复数
    minhash_dup_count: int = 0      # MinHash 近似重复数
    embedding_dup_count: int = 0    # Embedding 语义重复数
    output_count: int = 0           # 去重后输出 chunk 数

    @property
    def total_removed(self) -> int:
        return self.input_count - self.output_count


class ChunkDeduplicator:
    """分块级去重器。

    在 chunk 生成之后、embedding 计算之前执行，
    过滤已存在于向量库中的重复或近似 chunk。

    Parameters
    ----------
    engine : Engine
        SQLAlchemy 引擎（与主数据库共享）
    embedder : EmbeddingModel | None
        仅第三级语义去重需要。未提供则跳过第三级
    jaccard_threshold : float
        MinHash Jaccard 相似度阈值（0.0~1.0），默认 0.85
    cosine_threshold : float
        Embedding 余弦相似度阈值（0.0~1.0），默认 0.95
    num_perm : int
        MinHash 排列数，越大越准确但签名越大，默认 128
    shingle_size : int
        字符 n-gram 大小，默认 3
    enable_exact : bool
        是否启用第一级精确去重，默认 True
    enable_minhash : bool
        是否启用第二级 MinHash 去重，默认 True
    enable_embedding : bool
        是否启用第三级 Embedding 语义去重，默认 False（需提供 embedder）
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
```

#### 4.2.1 第一级：SHA-256 精确去重

> **性能修正**：初版设计将知识库内所有 chunk 的 `content_hash` 全量加载到 Python 内存，再用 `set.in` 判断。这完全浪费了 B-tree 索引的优势，且随知识库增长内存线性膨胀。修正为：只对本次候选的哈希做批量 SQL `IN (...)` 查询，让数据库利用索引完成判断。

```python
    def _compute_content_hash(self, content: str) -> bytes:
        """计算 chunk 内容的 SHA-256 哈希值"""
        return hashlib.sha256(content.encode("utf-8")).digest()

    def _query_hashes_exist(self, kb_id: str, hashes: list[bytes]) -> set[bytes]:
        """批量查询指定哈希在指纹表中是否已存在。

        不全量加载，而是利用 B-tree 索引精确查找本次候选哈希。
        SQLite 对 IN (...) 列表有上限（~999 参数），需分批查询。
        """
        found: set[bytes] = set()
        batch_size = 500
        with self.engine.connect() as conn:
            for i in range(0, len(hashes), batch_size):
                batch = hashes[i : i + batch_size]
                placeholders = ", ".join(f":h{j}" for j in range(len(batch)))
                params: dict = {"kb_id": kb_id}
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

    def _exact_dedup(
        self, chunks: list[Chunk], stats: ChunkDedupStats
    ) -> list[Chunk]:
        """第一级：SHA-256 精确去重。

        分两步处理：
        1. 批次内去重（纯内存，同一批上传文件中的重复 chunk）
        2. 跨批次去重（SQL 查询本次候选哈希是否已存在于指纹表）
        """
        # --- 批次内去重：计算哈希并去重 ---
        seen: set[bytes] = set()
        unique_chunks: list[Chunk] = []
        for chunk in chunks:
            h = self._compute_content_hash(chunk.content)
            chunk._content_hash = h  # 暂存，供后续注册使用
            if h in seen:
                stats.exact_dup_count += 1
                logger.debug("批次内精确去重: chunk %s", chunk.id[:8])
                continue
            seen.add(h)
            unique_chunks.append(chunk)

        if not unique_chunks:
            return []

        # --- 跨批次去重：只查本次候选哈希是否已存在 ---
        kb_id = unique_chunks[0].knowledge_base_id
        candidate_hashes = [c._content_hash for c in unique_chunks]
        existing = self._query_hashes_exist(kb_id, candidate_hashes)

        result: list[Chunk] = []
        for chunk in unique_chunks:
            if chunk._content_hash in existing:
                stats.exact_dup_count += 1
                logger.debug("跨批次精确去重: chunk %s", chunk.id[:8])
                continue
            result.append(chunk)

        return result
```

**精确去重的数据流**：

```
chunks: [A, B, C, D, E]
            │
    ┌───────┴─────────────────────────────────────────┐
    │  1. 批次内去重：计算 hash，seen={hash_1, hash_2} │
    │     hash(A) = hash_1 → 保留                     │
    │     hash(B) = hash_2 → 保留                     │
    │     hash(C) = hash_1 → 跳过（批次内重复）         │
    │     hash(D) = hash_3 → 保留                     │
    │     hash(E) = hash_2 → 跳过（批次内重复）         │
    │     unique = [A, B, D]                          │
    ├──────────────────────────────────────────────────┤
    │  2. 跨批次去重：SQL IN 查询 [hash_1,hash_2,hash_3]│
    │     已存在: {hash_1, hash_3}                     │
    │     hash(A) = hash_1 → 跳过（跨批次重复）         │
    │     hash(B) = hash_2 → 保留                     │
    │     hash(D) = hash_3 → 跳过（跨批次重复）         │
    └───────┬─────────────────────────────────────────┘
            ▼
    candidates: [B]
```

#### 4.2.2 第二级：MinHash 近似去重

> **性能修正**：初版设计有两个性能问题：
> 1. **重复反序列化**：每个候选 chunk 比较时，所有已有签名都被 `MinHash.deserialize()` 重新解析。以 100 候选 × 10,000 已有 = 1,000,000 次 deserialize。修正为：从数据库取出后**一次性预反序列化**为 `MinHash` 对象列表，后续复用。
> 2. **批次内近似去重缺失**：初版只与已有签名比较，批次内两个近似 chunk 会同时保留。修正为：本批次新保留的 chunk 也加入比较列表。

```python
    def _compute_minhash_obj(self, text_content: str) -> MinHash:
        """计算文本的 MinHash 对象。

        使用字符 n-gram（shingle）而非分词器，保证中英文兼容。
        返回 MinHash 对象而非 bytes，避免不必要的 serialize/deserialize。
        """
        m = MinHash(num_perm=self.num_perm)
        content_bytes = text_content.encode("utf-8")
        for i in range(len(content_bytes) - self.shingle_size + 1):
            m.update(content_bytes[i : i + self.shingle_size])
        return m

    def _minhash_dedup(
        self, candidates: list[Chunk], stats: ChunkDedupStats
    ) -> list[Chunk]:
        """第二级：MinHash 近似去重。

        1. 从指纹表取出已有签名，一次性反序列化为 MinHash 对象列表
        2. 对每个候选计算 MinHash，与已有列表比较 Jaccard
        3. 新保留的 chunk 也加入比较列表（批次内近似去重）

        时间复杂度：O(m × n)，其中 m=候选数, n=已有签名数。
        对于 n > 10,000 的知识库，应考虑引入 LSH 索引（见第 8 节）。
        """
        kb_id = candidates[0].knowledge_base_id

        # 一次性从数据库取出并反序列化，避免重复 deserialize
        existing_mh: list[MinHash] = []
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT minhash_sig FROM rag_chunk_fingerprints "
                    "WHERE kb_id = :kb_id AND minhash_sig IS NOT NULL"
                ),
                {"kb_id": kb_id},
            ).fetchall()
            for row in rows:
                existing_mh.append(
                    MinHash.deserialize(row[0], num_perm=self.num_perm)
                )

        logger.debug("MinHash 去重: 已有签名 %d 条", len(existing_mh))

        result: list[Chunk] = []
        for chunk in candidates:
            mh = self._compute_minhash_obj(chunk.content)
            chunk._minhash_sig = mh.serialize()  # 暂存，供后续注册使用

            is_dup = False
            for existing in existing_mh:
                if mh.jaccard(existing) >= self.jaccard_threshold:
                    is_dup = True
                    stats.minhash_dup_count += 1
                    logger.debug(
                        "MinHash 去重: chunk %s Jaccard=%.3f",
                        chunk.id[:8], mh.jaccard(existing),
                    )
                    break

            if not is_dup:
                result.append(chunk)
                existing_mh.append(mh)  # 加入比较列表，实现批次内近似去重

        return result
```

**MinHash 去重的数据流**：

```
candidates: [B, D, E]
            │
    ┌───────┴──────────────────────────────────────────────┐
    │  从指纹表取出已有签名 → 预反序列化为 MinHash 对象列表     │
    │  existing_mh = [mh_X, mh_Y, mh_Z]                    │
    └───────┬──────────────────────────────────────────────┘
            │
    mh(B).jaccard(mh_X) = 0.92 >= 0.85 → 跳过（近似重复）
    mh(D).jaccard(mh_Y) = 0.30 < 0.85  → 保留，加入比较列表
       existing_mh = [mh_X, mh_Y, mh_Z, mh(D)]
    mh(E).jaccard(mh_Z) = 0.15 < 0.85  → 保留
    mh(E).jaccard(mh(D)) = 0.88 >= 0.85 → 跳过（批次内近似重复）
            │
            ▼
    result: [D]
```

#### 4.2.3 第三级（可选）：Embedding 语义去重

```python
    def _embedding_dedup(
        self, candidates: list[Chunk], stats: ChunkDedupStats
    ) -> list[Chunk]:
        """第三级：Embedding 语义去重（可选）。

        对候选 chunk 计算 embedding，通过余弦相似度过滤语义重复。
        使用贪心策略：按顺序遍历，与已保留的 chunk 比较，若相似则跳过。

        注意：此方法会额外调用 embedder，产生 embedding 计算成本。
        默认关闭，仅在对去重质量有极高要求时启用。
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
        """计算两个向量的余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
```

#### 4.2.4 主入口方法与指纹注册

> **性能修正**：初版 `register_chunks` 对每个 chunk 执行一次独立的 `INSERT` 语句（100 chunk = 100 次 SQL round trip）。修正为使用 `executemany` 批量插入，单次 SQL 完成。

```python
    def deduplicate(
        self, chunks: list[Chunk], kb_id: str
    ) -> tuple[list[Chunk], ChunkDedupStats]:
        """对一批 chunk 执行分块级去重。

        Parameters
        ----------
        chunks : list[Chunk]
            待去重的 chunk 列表
        kb_id : str
            知识库 ID

        Returns
        -------
        tuple[list[Chunk], ChunkDedupStats]
            去重后的 chunk 列表和统计信息

        Pipeline:
            输入 → SHA-256精确去重 → MinHash近似去重 → Embedding语义去重 → 输出
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
            "分块去重完成: 输入 %d, 精确去重 %d, MinHash去重 %d, "
            "Embedding去重 %d, 输出 %d",
            stats.input_count,
            stats.exact_dup_count,
            stats.minhash_dup_count,
            stats.embedding_dup_count,
            stats.output_count,
        )
        return result, stats

    def register_chunks(self, chunks: list[Chunk]) -> None:
        """将已成功入库的 chunk 指纹写入指纹表。

        使用 executemany 批量插入，在单次 SQL 调用中完成所有写入。
        在 chunks 成功写入 ChromaDB 后调用，建立去重索引。
        """
        if not chunks:
            return

        rows: list[dict] = []
        for chunk in chunks:
            content_hash = getattr(chunk, "_content_hash", None)
            if content_hash is None:
                content_hash = self._compute_content_hash(chunk.content)

            minhash_sig = getattr(chunk, "_minhash_sig", None)
            if minhash_sig is None and self.enable_minhash:
                mh = self._compute_minhash_obj(chunk.content)
                minhash_sig = mh.serialize()

            rows.append({
                "id": chunk.id,
                "doc_id": chunk.document_id,
                "kb_id": chunk.knowledge_base_id,
                "hash": content_hash,
                "sig": minhash_sig,
            })

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO rag_chunk_fingerprints "
                    "(id, document_id, kb_id, content_hash, minhash_sig) "
                    "VALUES (:id, :doc_id, :kb_id, :hash, :sig)"
                ),
                rows,  # executemany: 单条 SQL，批量参数
            )
```

### 4.3 MinHash 参数调优指南

| 参数 | 推荐值 | 影响 |
|------|--------|------|
| `num_perm` | 128 | 签名 512 bytes。增大到 256 可提高准确度但签名翻倍 |
| `shingle_size` | 3 | 对 512 字符 chunk 约产生 510 个 shingle。增大则对短文本不敏感 |
| `jaccard_threshold` | 0.85 | RAG.md 推荐 0.8~0.9。值越高越宽松（更多 chunk 被保留） |

**阈值选择经验**：

| Jaccard 阈值 | 适用场景 | 效果 |
|-------------|----------|------|
| 0.70 | 激进去重 | 几乎相同段落也会被过滤，可能丢失有价值的变体 |
| 0.85（默认） | 平衡 | 过滤明显重复，保留有意义的不同表述 |
| 0.95 | 保守去重 | 仅过滤几乎完全相同的 chunk |

**num_perm 与准确度的关系**：

MinHash 的 Jaccard 估计方差为 `Var = (1 - J²) / num_perm`，其中 J 为真实 Jaccard。

| num_perm | 签名大小 | 估计标准差 (J=0.85) | 适用场景 |
|----------|---------|-------------------|----------|
| 64 | 256 B | ~2.5% | 快速粗筛 |
| 128（默认） | 512 B | ~1.7% | 常规使用 |
| 256 | 1 KB | ~1.2% | 高精度需求 |

### 4.4 与 Indexer 管道集成

修改 `src/thumbelina/rag/pipeline/indexer.py`：

> **事务一致性修正**：初版未考虑 `register_chunks` 失败的场景。ChromaDB 写入成功但指纹注册失败会导致去重索引不一致（chunk 存在于向量库但无法被去重检查命中）。修正为用 try/except 包裹注册步骤，记录警告日志。

```python
class Indexer:
    def __init__(
        self,
        loader: Loader,
        chunker: Chunker,
        embedder: EmbeddingModel,
        vector_store: VectorStore,
        doc_repo: DocumentRepository | None = None,
        # ===== 新增参数 =====
        engine: Engine | None = None,
        chunk_dedup_enabled: bool = True,
    ) -> None:
        self.loader = loader
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.doc_repo = doc_repo

        # 分块级去重器
        self.chunk_dedup: ChunkDeduplicator | None = None
        if engine and chunk_dedup_enabled:
            self.chunk_dedup = ChunkDeduplicator(engine, embedder=embedder)

    def _embed_and_store(self, chunks: list[Chunk], stats: IndexStats) -> None:
        """Embed and store chunks in vector store."""

        # ===== 新增：分块级去重 =====
        if self.chunk_dedup and chunks:
            chunks, dedup_stats = self.chunk_dedup.deduplicate(
                chunks, chunks[0].knowledge_base_id
            )
            if dedup_stats.total_removed > 0:
                logger.info(
                    "分块去重: 过滤 %d 个重复 chunk", dedup_stats.total_removed
                )

        if not chunks:
            return

        # 原有逻辑：计算 embedding → 写入 ChromaDB
        texts = [c.content for c in chunks]
        embeddings = self.embedder.embed_batch(texts)
        self.vector_store.add(chunks, embeddings)

        # ===== 新增：注册已入库 chunk 的指纹 =====
        # 指纹注册失败不应阻断索引流程，但需记录不一致状态
        if self.chunk_dedup:
            try:
                self.chunk_dedup.register_chunks(chunks)
            except Exception:
                logger.warning(
                    "指纹注册失败，去重索引可能不一致。"
                    "如需修复，请删除相关文档后重新上传。",
                    exc_info=True,
                )

        stats.indexed_count += len(chunks)
```

**完整的管道流程**：

```
                        ┌─── 文档级去重（已有）───┐
                        │ SHA-256 精确 → SimHash  │
                        └────────────┬────────────┘
                                     │
File → Loader.load() → Document ────┘
                                     │ (通过)
                                     ▼
                            Chunker.chunk() → list[Chunk]
                                     │
                                     ▼
                        ┌─── 分块级去重（新增）────┐
                        │ SHA-256 → MinHash →     │
                        │ Embedding (可选)         │
                        └────────────┬────────────┘
                                     │ (去重后)
                                     ▼
                            EmbeddingModel.embed_batch()
                                     │
                                     ▼
                            VectorStore.add()  ← 写入 ChromaDB
                            + register_chunks  ← 写入 SQLite 指纹表
                              (try/except)       (失败则记录警告)
```

### 4.5 指纹表初始化

修改 `src/thumbelina/rag/knowledge_base/db.py`，在 `init_rag_db()` 中添加建表逻辑：

```python
def init_rag_db(engine: Engine) -> None:
    """Initialize RAG database tables."""
    # ... 现有代码 ...

    # 分块指纹表（新增）
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_chunk_fingerprints (
                id            TEXT PRIMARY KEY,
                document_id   TEXT NOT NULL,
                kb_id         TEXT NOT NULL,
                content_hash  BLOB NOT NULL,
                minhash_sig   BLOB,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunk_fingerprint_hash "
            "ON rag_chunk_fingerprints(content_hash)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunk_fingerprint_kb "
            "ON rag_chunk_fingerprints(kb_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunk_fingerprint_doc "
            "ON rag_chunk_fingerprints(document_id)"
        ))
```

**级联删除**：`ON DELETE CASCADE` 确保删除文档时自动清理关联的指纹记录。

### 4.6 API 路由调整

在 `api/routes/rag.py` 的文档上传端点中，将 `engine` 传递给 `Indexer`：

```python
# 现有代码
kb_indexer = Indexer(
    loader=TextLoader(),
    chunker=RecursiveChunker(),
    embedder=embedding_registry.create(),
    vector_store=kb_store,
    doc_repo=doc_repo,
    # ===== 新增 =====
    engine=request.app.state.engine,
    chunk_dedup_enabled=True,
)
```

## 5. 依赖变更

```toml
# pyproject.toml
[project.optional-dependencies]
rag = [
    # ... 现有依赖 ...
    "datasketch>=1.6",       # MinHash / LSH 计算
]
```

`datasketch` 是 MinHash 的成熟纯 Python 实现，无重依赖，MIT 许可证。

## 6. 测试计划

### 6.1 单元测试

新增 `tests/test_rag/test_chunk_dedup.py`：

| 测试用例 | 描述 |
|----------|------|
| `test_exact_dedup_within_batch` | 同一批次中的重复 chunk 被过滤 |
| `test_exact_dedup_across_batches` | 与已有指纹匹配的 chunk 被过滤 |
| `test_exact_dedup_batch_sql` | 验证跨批次去重使用 SQL IN 查询而非全量加载 |
| `test_minhash_near_duplicate` | 相似度 ≥ 0.85 的 chunk 被过滤 |
| `test_minhash_below_threshold_kept` | 相似度 < 0.85 的 chunk 被保留 |
| `test_minhash_intra_batch_dedup` | 批次内两个近似 chunk 只保留第一个 |
| `test_minhash_pre_deserialize` | 验证已有签名只反序列化一次 |
| `test_empty_chunks` | 空列表输入不报错 |
| `test_single_chunk` | 单个 chunk 不受影响 |
| `test_all_duplicates` | 全部重复时返回空列表 |
| `test_register_then_dedup` | 注册 → 再次输入同批 chunk → 全被精确去重 |
| `test_register_batch_insert` | 验证指纹注册使用批量插入 |
| `test_cascade_delete_cleanup` | 删除文档后指纹记录自动清理 |
| `test_embedding_dedup` | 第三级语义去重正确过滤高相似度 chunk |
| `test_stats_accuracy` | 统计数字与实际过滤数量一致 |

### 6.2 集成测试

| 测试用例 | 描述 |
|----------|------|
| `test_upload_similar_documents` | 上传两份有大量重复段落的文档，验证去重效果 |
| `test_reupload_after_edit` | 修改文档少量内容后重新上传，验证旧 chunk 被替换 |

## 7. 性能估算与对比

以 512 字符的 chunk、新上传 100 个 chunk、知识库已有 N 个 chunk 为例：

### 7.1 单次索引性能（修正后）

| 阶段 | 耗时估算 (N=1K) | 耗时估算 (N=10K) | 说明 |
|------|----------------|-----------------|------|
| SHA-256 计算 (×100) | ~0.1 ms | ~0.1 ms | 纯 CPU |
| SQL 批量查询已有哈希 | ~0.5 ms | ~1 ms | B-tree 索引，IN 查询 100 条 |
| MinHash 计算 (×100) | ~5 ms | ~5 ms | ~500 shingle/chunk × 128 hashes |
| SQL 取出已有签名 | ~1 ms | ~5 ms | N × 512 bytes |
| 已有签名预反序列化 | ~1 ms | ~10 ms | N 次 deserialize（一次性） |
| Jaccard 比较 | ~5 ms | ~50 ms | 100 × N 次比较 |
| 批量注册指纹 | ~1 ms | ~1 ms | 1 条 executemany |
| **总计（前两级）** | **~14 ms** | **~72 ms** | |
| Embedding 计算 (×100) | ~2000 ms | ~2000 ms | 仅第三级，需 GPU |
| **总计（含第三级）** | **~2014 ms** | **~2072 ms** | |

### 7.2 修正前后对比（N=10K chunk 知识库，100 候选）

| 环节 | 初版设计 | 修正后 | 改进幅度 |
|------|---------|--------|---------|
| SHA256 查重 | 全量加载 10K 条到内存 (~320 KB) | SQL IN 查询 100 条 | 内存 -99%, 查询更快 |
| MinHash deserialize | 100 × 10K = **1,000,000 次** | 10K 次（预反序列化） | **调用次数 -99%** |
| Jaccard 比较 | 1,000,000 次（含重复 deserialize） | 1,000,000 次（复用对象） | 总耗时减少 ~80% |
| register_chunks | 100 条独立 INSERT | 1 条 executemany | SQL 调用 -99% |
| 批次内近似去重 | ❌ 不支持 | ✅ 新保留 chunk 加入比较列表 | 去重质量提升 |

### 7.3 规模瓶颈

| 知识库规模 | 前两级去重耗时 | 是否可接受 | 建议 |
|-----------|--------------|-----------|------|
| ≤ 5,000 chunks | < 30 ms | ✅ 完全没问题 | 默认配置即可 |
| 5,000 ~ 20,000 chunks | 30 ~ 200 ms | ✅ 可接受 | 注意日志监控 |
| 20,000 ~ 100,000 chunks | 200 ms ~ 2 s | ⚠️ 开始影响体验 | 引入 LSH 索引（见 8.1） |
| > 100,000 chunks | > 2 s | ❌ 不可接受 | 必须使用 LSH + 指纹预加载 |

## 8. 后续演进

### 8.1 MinHash LSH 索引 — 大规模知识库的核心优化

当知识库 chunk 数增长到万级以上时，当前 O(m × n) 的逐一比较成为瓶颈。

#### 8.1.1 问题分析

当前的 `_minhash_dedup` 方法，每个候选 chunk 都要与知识库内**所有**已有签名逐一计算 Jaccard：

```
时间复杂度: O(m × n)
  m = 候选 chunk 数（通常 10~100）
  n = 知识库已有 chunk 数（可能 10K ~ 100K）

当 n=50,000, m=100 时:
  5,000,000 次 Jaccard 比较 + 50,000 次 MinHash 反序列化
  预估耗时: 5~10 秒
```

#### 8.1.2 LSH 原理

**Locality-Sensitive Hashing (LSH)** 是一种近似最近邻搜索算法，通过将相似的项映射到同一个「桶」中，将查找复杂度从 O(n) 降至近似 O(1)。

对 MinHash 的 LSH 方案：**b 个 band × r 行**

```
MinHash 签名 (128 个哈希值)
         │
    ┌────┴────┐
    │ 拆分为 b 个 band │
    │ 每个 band 含 r 行 │
    │ (b × r = 128)   │
    └────┬────┘
         │
    band_1 = [h_0, h_1, ..., h_{r-1}]  → 哈希到桶 key_1
    band_2 = [h_r, h_{r+1}, ..., h_{2r-1}] → 哈希到桶 key_2
    ...
    band_b = [...]

如果两个 chunk 在任意一个 band 中落入同一个桶 → 候选对（可能是近似重复）
```

**阈值控制**：对于 Jaccard 相似度阈值 t，选择 b 和 r 使得：

```
t ≈ (1/b)^{1/r}

示例（t=0.85）：
  b=20, r=6  → 候选阈值 ≈ 0.84  ← 接近目标
  b=16, r=8  → 候选阈值 ≈ 0.83
  b=25, r=5  → 候选阈值 ≈ 0.86
```

#### 8.1.3 基于 datasketch.MinHashLSH 的实现方案

`datasketch` 库内置了 `MinHashLSH` 类，可直接使用：

```python
from datasketch import MinHash, MinHashLSH

class LSHChunkDeduplicator:
    """基于 LSH 索引的分块去重器（大规模知识库优化）。

    适用场景：知识库 chunk 数 > 10,000
    核心改进：将 MinHash 查找从 O(n) 降至近似 O(1)
    """

    def __init__(
        self,
        engine: Engine,
        threshold: float = 0.85,
        num_perm: int = 128,
    ) -> None:
        self.engine = engine
        self.num_perm = num_perm

        # LSH 索引：b=20, r=6 → 候选阈值 ≈ 0.84
        self.lsh = MinHashLSH(
            threshold=threshold,
            num_perm=num_perm,
        )
        self._loaded = False

    def _ensure_loaded(self, kb_id: str) -> None:
        """懒加载：首次使用时从指纹表加载所有 MinHash 到 LSH 索引。"""
        if self._loaded:
            return

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, minhash_sig FROM rag_chunk_fingerprints "
                    "WHERE kb_id = :kb_id AND minhash_sig IS NOT NULL"
                ),
                {"kb_id": kb_id},
            ).fetchall()

        for row in rows:
            mh = MinHash.deserialize(row[1], num_perm=self.num_perm)
            try:
                self.lsh.insert(row[0], mh)
            except ValueError:
                pass  # 已存在则跳过

        self._loaded = True
        logger.info("LSH 索引加载完成: %d 条签名", len(rows))

    def register(self, chunk_id: str, mh: MinHash) -> None:
        """向 LSH 索引插入新签名（O(1)）。"""
        try:
            self.lsh.insert(chunk_id, mh)
        except ValueError:
            pass

    def find_duplicates(self, mh: MinHash) -> list[str]:
        """查找候选近似重复的 chunk ID 列表（O(1) 查找）。"""
        return self.lsh.query(mh)
```

#### 8.1.4 LSH vs 线性扫描对比

| 指标 | 线性扫描（当前） | LSH 索引 |
|------|----------------|---------|
| 查找复杂度 | O(n) per candidate | O(1) per candidate |
| 构建开销 | 无 | O(n) 一次性构建 |
| 内存开销 | N × 512 bytes (签名) | N × 512 bytes + 哈希表 (~2× 签名大小) |
| 准确度 | 精确 Jaccard | 近似，有少量假阳/假阴 |
| 50K chunks 查找耗时 | ~5-10 s | ~10-50 ms |

#### 8.1.5 LSH 的局限性与应对

| 局限 | 说明 | 应对 |
|------|------|------|
| 假阳性 | 不相似的 chunk 被 LSH 判为候选 | LSH 返回的是候选对，仍需计算真实 Jaccard 二次确认 |
| 假阴性 | 少数相似 chunk 可能漏过 | 增大 `num_perm` 或调整 b/r 参数降低漏检率 |
| 内存占用 | LSH 内部维护哈希桶表 | 对于 100K chunk 约额外增加 ~50 MB，可接受 |
| 数据一致性 | 进程重启后 LSH 索引丢失 | 启动时从指纹表重新构建（首次查询时懒加载） |

#### 8.1.6 集成路径

LSH 可作为当前 `ChunkDeduplicator` 的渐进升级，无需推翻现有架构：

```
Phase 1（当前）: 线性扫描，适用于 chunk 数 < 20,000
Phase 2（后续）: 在 ChunkDeduplicator 内部根据 chunk 数自动切换策略
  - n < 10,000  → 使用线性扫描（当前实现）
  - n >= 10,000 → 自动切换到 LSH 模式
```

```python
def _minhash_dedup(self, candidates, stats):
    """根据知识库规模自动选择 MinHash 或 LSH 策略"""
    existing_count = self._count_existing_chunks(kb_id)

    if existing_count >= LSH_THRESHOLD:
        return self._minhash_dedup_lsh(candidates, stats)
    else:
        return self._minhash_dedup_linear(candidates, stats)
```

### 8.2 指纹预加载 — 减少数据库查询开销

高频知识库可在启动时将指纹表加载到内存，避免每次上传文档都查询数据库。

```python
class ChunkFingerprintCache:
    """知识库指纹内存缓存。

    在知识库首次被使用时加载，后续复用。
    文档增删时自动失效并重新加载。
    """

    def __init__(self, engine: Engine, kb_id: str) -> None:
        self.engine = engine
        self.kb_id = kb_id
        self.hashes: set[bytes] = set()
        self.minhash_objects: list[MinHash] = []
        self._loaded = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        # 一次性加载所有指纹到内存
        ...
        self._loaded = True

    def invalidate(self) -> None:
        """文档增删后调用，使缓存失效"""
        self._loaded = False
        self.hashes.clear()
        self.minhash_objects.clear()
```

### 8.3 检索级去重

即使写入时做了分块去重，检索时仍可能返回语义相近的结果（来自不同 chunk 但主题相同）。RAG.md 第 136-146 行规划了检索级去重：

- 在 `SimpleRetriever.retrieve()` 返回 top-k 后，对结果做 SimHash 或编辑距离去重
- 将 top-k 扩大为 top-2k，去重后保留 k 个，保证最终返回数量

### 8.4 增量更新

当前文档重新上传时需要删除旧文档再重建全部 chunk。未来可支持：
- 基于 chunk 指纹比对，只更新变更的 chunk
- 未变更的 chunk 复用已有 embedding，避免重复计算
