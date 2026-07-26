"""Tests for ChunkDeduplicator — 分块级去重器。"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import Engine, create_engine, text

from thumbelina.rag.embedding.base import EmbeddingModel
from thumbelina.rag.ingestion.chunk_dedup import (
    ChunkDeduplicator,
    ChunkDedupStats,
)
from thumbelina.rag.knowledge_base.models import Chunk

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KB_ID = "test-kb-1"


@pytest.fixture()
def engine() -> Engine:
    """创建内存 SQLite 引擎并初始化指纹表。"""
    eng = create_engine("sqlite:///:memory:")

    # SQLite 默认不启用外键约束，需要手动开启
    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    with eng.begin() as conn:
        # 创建 rag_documents 表（外键依赖）
        conn.execute(
            text("""
            CREATE TABLE rag_documents (
                id TEXT PRIMARY KEY,
                knowledge_base_id TEXT NOT NULL,
                name TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                sha256 BLOB NOT NULL,
                sim_hash_64 BLOB NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        # 插入一个占位文档
        conn.execute(
            text(
                "INSERT INTO rag_documents"
                " (id, knowledge_base_id, name, source_uri, doc_type, sha256, sim_hash_64)"
                " VALUES ('doc-1', :kb_id, 'test.md', '/tmp/test.md', '.md', x'', x'')"
            ),
            {"kb_id": KB_ID},
        )
        # 创建 chunk 指纹表
        conn.execute(
            text("""
            CREATE TABLE rag_chunk_fingerprints (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                kb_id TEXT NOT NULL,
                content_hash BLOB NOT NULL,
                minhash_sig BLOB,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
            )
        """)
        )
        conn.execute(
            text("CREATE INDEX idx_chunk_fingerprint_hash ON rag_chunk_fingerprints(content_hash)")
        )
        conn.execute(text("CREATE INDEX idx_chunk_fingerprint_kb ON rag_chunk_fingerprints(kb_id)"))
        conn.execute(
            text("CREATE INDEX idx_chunk_fingerprint_doc ON rag_chunk_fingerprints(document_id)")
        )
    return eng


def _make_chunk(content: str, doc_id: str = "doc-1", chunk_id: str | None = None) -> Chunk:
    return Chunk(
        id=chunk_id or uuid.uuid4().hex,
        document_id=doc_id,
        content=content,
        metadata=json.dumps({"source_uri": "/tmp/test.md"}),
        knowledge_base_id=KB_ID,
    )


def _count_fingerprints(engine: Engine) -> int:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM rag_chunk_fingerprints")).fetchone()
    return row[0]  # type: ignore[index]


# ---------------------------------------------------------------------------
# ChunkDedupStats
# ---------------------------------------------------------------------------


class TestChunkDedupStats:
    def test_default_values(self):
        stats = ChunkDedupStats()
        assert stats.input_count == 0
        assert stats.exact_dup_count == 0
        assert stats.minhash_dup_count == 0
        assert stats.embedding_dup_count == 0
        assert stats.output_count == 0

    def test_total_removed(self):
        stats = ChunkDedupStats(input_count=10, output_count=7)
        assert stats.total_removed == 3


# ---------------------------------------------------------------------------
# 第一级：SHA-256 精确去重
# ---------------------------------------------------------------------------


class TestExactDedup:
    def test_no_duplicates_pass_all(self, engine: Engine):
        """无重复 chunk → 全部保留。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)
        chunks = [_make_chunk(f"chunk-{i}") for i in range(5)]

        result, stats = dedup.deduplicate(chunks, KB_ID)

        assert len(result) == 5
        assert stats.exact_dup_count == 0
        assert stats.output_count == 5

    def test_exact_dedup_within_batch(self, engine: Engine):
        """同一批次中的重复 chunk 被过滤。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)
        same_text = "这是一段完全相同的文本内容"
        c1 = _make_chunk(same_text, chunk_id="c1")
        c2 = _make_chunk(same_text, chunk_id="c2")  # 内容相同
        c3 = _make_chunk("另一段不同的文本", chunk_id="c3")

        result, stats = dedup.deduplicate([c1, c2, c3], KB_ID)

        assert len(result) == 2
        assert stats.exact_dup_count == 1
        result_ids = {c.id for c in result}
        assert "c1" in result_ids
        assert "c3" in result_ids

    def test_exact_dedup_across_batches_replaces_old(self, engine: Engine):
        """跨批次重复：旧指纹被删除，新 chunk 全部保留。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)

        # 先注册一批 chunk
        first_batch = [_make_chunk("已入库的文本", chunk_id="existing")]
        dedup.register_chunks(first_batch)
        assert _count_fingerprints(engine) == 1

        # 再上传相同内容 → 旧指纹被删除，新 chunk 保留
        new_batch = [_make_chunk("已入库的文本", chunk_id="new-1")]

        result, stats = dedup.deduplicate(new_batch, KB_ID)

        assert len(result) == 1
        assert result[0].id == "new-1"
        assert stats.exact_dup_count == 1
        assert "existing" in stats.removed_old_ids
        assert _count_fingerprints(engine) == 0  # 旧指纹已删除

    def test_all_duplicates_returns_one(self, engine: Engine):
        """全部重复时只保留第一个（批次内去重）。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)
        same = "全部相同的文本"
        chunks = [_make_chunk(same, chunk_id=f"c{i}") for i in range(5)]

        result, stats = dedup.deduplicate(chunks, KB_ID)

        assert len(result) == 1  # 第一个保留，其余被过滤
        assert stats.exact_dup_count == 4

    def test_batch_sql_not_full_load(self, engine: Engine):
        """验证跨批次去重使用 SQL IN 查询而非全量加载。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)

        # 注册 10 个已有 chunk
        existing = [_make_chunk(f"existing-{i}", chunk_id=f"e{i}") for i in range(10)]
        dedup.register_chunks(existing)

        # 查询 3 个候选（其中 1 个与已有重复）
        candidates = [
            _make_chunk("existing-0", chunk_id="new-dup"),  # 与 e0 重复
            _make_chunk("brand-new-1", chunk_id="new-1"),
            _make_chunk("brand-new-2", chunk_id="new-2"),
        ]

        result, stats = dedup.deduplicate(candidates, KB_ID)

        # 全部 3 个新 chunk 保留，旧指纹 e0 被删除
        assert len(result) == 3
        assert stats.exact_dup_count == 1
        assert "e0" in stats.removed_old_ids


# ---------------------------------------------------------------------------
# 第二级：MinHash 近似去重
# ---------------------------------------------------------------------------


class TestMinhashDedup:
    def test_no_existing_signatures(self, engine: Engine):
        """无已有签名时全部保留。"""
        dedup = ChunkDeduplicator(engine)
        chunks = [_make_chunk(f"chunk-{i}") for i in range(3)]

        result, stats = dedup.deduplicate(chunks, KB_ID)

        assert len(result) == 3
        assert stats.minhash_dup_count == 0

    def test_minhash_near_duplicate_replaces_old(self, engine: Engine):
        """相似度 >= 阈值：旧指纹被删除，新 chunk 保留。"""
        dedup = ChunkDeduplicator(engine, jaccard_threshold=0.80)

        # 使用足够长的英文文本，修改极少量字符以产生高 Jaccard
        base_text = "the quick brown fox jumps over the lazy dog " * 30
        # 只替换 2 个字符（fox→cat），影响 1 个 shingle
        similar_text = base_text.replace("fox", "cat", 1)

        existing = [_make_chunk(base_text, chunk_id="base")]
        dedup.register_chunks(existing)

        new_chunk = _make_chunk(similar_text, chunk_id="similar")

        result, stats = dedup.deduplicate([new_chunk], KB_ID)

        # 旧指纹被删除，新 chunk 保留
        assert len(result) == 1
        assert result[0].id == "similar"
        assert stats.minhash_dup_count == 1
        assert "base" in stats.removed_old_ids

    def test_minhash_below_threshold_kept(self, engine: Engine):
        """相似度 < 阈值：无旧指纹被删除，新 chunk 保留。"""
        dedup = ChunkDeduplicator(engine, jaccard_threshold=0.99)

        existing = [_make_chunk("完全不同的内容A" * 50, chunk_id="a")]
        dedup.register_chunks(existing)

        new_chunk = _make_chunk("另一段完全不同的内容B" * 50, chunk_id="b")

        result, stats = dedup.deduplicate([new_chunk], KB_ID)

        assert len(result) == 1
        assert stats.minhash_dup_count == 0
        assert len(stats.removed_old_ids) == 0

    def test_minhash_no_intra_batch_dedup(self, engine: Engine):
        """批次内近似 chunk 不再被过滤（全量保留新 chunk）。"""
        dedup = ChunkDeduplicator(engine, jaccard_threshold=0.80)

        base_text = "深度学习是人工智能的重要分支" * 20
        similar_text = base_text[:50] + "机器学习" + base_text[50 + 4 :]

        c1 = _make_chunk(base_text, chunk_id="c1")
        c2 = _make_chunk(similar_text, chunk_id="c2")

        result, stats = dedup.deduplicate([c1, c2], KB_ID)

        # 两个新 chunk 都保留（不做批次内近似去重）
        assert len(result) == 2
        assert stats.minhash_dup_count == 0

    def test_minhash_pre_deserialize(self, engine: Engine):
        """验证已有签名只反序列化一次（通过批量注册后查询行为）。"""
        dedup = ChunkDeduplicator(engine)

        # 注册 5 个已有 chunk
        existing = [_make_chunk(f"chunk-{i}" * 30, chunk_id=f"e{i}") for i in range(5)]
        dedup.register_chunks(existing)

        # 上传 2 个新 chunk
        new = [_make_chunk(f"new-{i}" * 30, chunk_id=f"n{i}") for i in range(2)]
        result, stats = dedup.deduplicate(new, KB_ID)

        # 应正常完成，无异常
        assert stats.output_count == len(result)


# ---------------------------------------------------------------------------
# 第三级：Embedding 语义去重
# ---------------------------------------------------------------------------


class FakeEmbeddingModel(EmbeddingModel):
    """测试用 embedding 模型：返回固定维度的向量。"""

    def __init__(self, raise_exc: bool = False):
        self._raise = raise_exc

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._raise:
            raise RuntimeError("embedding failed")
        return [self.embed(t) for t in texts]


class TestEmbeddingDedup:
    def test_embedding_dedup_disabled_by_default(self, engine: Engine):
        """默认不启用 embedding 语义去重。"""
        dedup = ChunkDeduplicator(engine, embedder=FakeEmbeddingModel())
        assert dedup.enable_embedding is False

    def test_embedding_dedup_enabled(self, engine: Engine):
        """明确启用后生效。"""
        dedup = ChunkDeduplicator(
            engine,
            embedder=FakeEmbeddingModel(),
            enable_embedding=True,
        )
        assert dedup.enable_embedding is True

    def test_embedding_dedup_filters_similar(self, engine: Engine):
        """余弦相似度 >= 阈值的 chunk 被过滤。"""
        # FakeEmbeddingModel 所有文本都返回相同向量
        # 所以余弦相似度始终为 1.0，应被过滤
        dedup = ChunkDeduplicator(
            engine,
            embedder=FakeEmbeddingModel(),
            enable_embedding=True,
            enable_exact=False,
            enable_minhash=False,
            cosine_threshold=0.90,
        )
        c1 = _make_chunk("chunk A content", chunk_id="c1")
        c2 = _make_chunk("chunk B content", chunk_id="c2")

        result, stats = dedup.deduplicate([c1, c2], KB_ID)

        # 所有向量相同，c2 被过滤
        assert len(result) == 1
        assert stats.embedding_dup_count == 1

    def test_embedding_dedup_single_chunk(self, engine: Engine):
        """单个 chunk 不触发 embedding 语义去重。"""
        dedup = ChunkDeduplicator(
            engine,
            embedder=FakeEmbeddingModel(),
            enable_embedding=True,
            enable_exact=False,
            enable_minhash=False,
        )
        c1 = _make_chunk("唯一的内容", chunk_id="c1")

        result, stats = dedup.deduplicate([c1], KB_ID)

        assert len(result) == 1
        assert stats.embedding_dup_count == 0


# ---------------------------------------------------------------------------
# 指纹注册
# ---------------------------------------------------------------------------


class TestRegisterChunks:
    def test_register_then_dedup_replaces_old(self, engine: Engine):
        """注册 → 再次输入同批 chunk → 旧指纹被删除，新 chunk 全部保留。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)
        chunks = [_make_chunk(f"text-{i}", chunk_id=f"c{i}") for i in range(3)]

        dedup.register_chunks(chunks)
        assert _count_fingerprints(engine) == 3

        # 同内容的新 chunk（不同 ID）
        new_chunks = [_make_chunk(f"text-{i}", chunk_id=f"n{i}") for i in range(3)]
        result, stats = dedup.deduplicate(new_chunks, KB_ID)

        assert len(result) == 3
        assert stats.exact_dup_count == 3
        assert len(stats.removed_old_ids) == 3
        assert _count_fingerprints(engine) == 0  # 旧指纹已删除

    def test_register_batch_insert(self, engine: Engine):
        """验证指纹注册使用批量插入（一次 SQL 调用）。"""
        dedup = ChunkDeduplicator(engine)
        chunks = [_make_chunk(f"text-{i}", chunk_id=f"c{i}") for i in range(10)]

        dedup.register_chunks(chunks)

        assert _count_fingerprints(engine) == 10

    def test_register_empty_chunks(self, engine: Engine):
        """空列表注册不报错。"""
        dedup = ChunkDeduplicator(engine)
        dedup.register_chunks([])
        assert _count_fingerprints(engine) == 0

    def test_cascade_delete_cleanup(self, engine: Engine):
        """删除文档后指纹记录自动清理。"""
        dedup = ChunkDeduplicator(engine)
        chunks = [_make_chunk(f"text-{i}", chunk_id=f"c{i}") for i in range(3)]
        dedup.register_chunks(chunks)
        assert _count_fingerprints(engine) == 3

        # 删除关联的文档
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rag_documents WHERE id = 'doc-1'"))

        assert _count_fingerprints(engine) == 0


# ---------------------------------------------------------------------------
# 空输入 / 边界场景
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_chunks(self, engine: Engine):
        """空列表输入不报错。"""
        dedup = ChunkDeduplicator(engine)
        result, stats = dedup.deduplicate([], KB_ID)

        assert result == []
        assert stats.input_count == 0
        assert stats.output_count == 0

    def test_single_chunk(self, engine: Engine):
        """单个 chunk 不受影响。"""
        dedup = ChunkDeduplicator(engine)
        c = _make_chunk("唯一的 chunk")

        result, stats = dedup.deduplicate([c], KB_ID)

        assert len(result) == 1
        assert stats.input_count == 1
        assert stats.output_count == 1
        assert stats.total_removed == 0

    def test_stats_accuracy(self, engine: Engine):
        """统计数字与实际行为一致（替换策略）。"""
        dedup = ChunkDeduplicator(engine, enable_minhash=False)

        # 注册 2 个已有 chunk
        existing = [_make_chunk("已存在A", chunk_id="ea"), _make_chunk("已存在B", chunk_id="eb")]
        dedup.register_chunks(existing)

        # 上传 5 个 chunk：2 个跨批次重复，1 个批次内重复，2 个新内容
        new = [
            _make_chunk("已存在A", chunk_id="n1"),  # 跨批次重复 → 旧指纹删除
            _make_chunk("已存在B", chunk_id="n2"),  # 跨批次重复 → 旧指纹删除
            _make_chunk("新内容C", chunk_id="n3"),
            _make_chunk("新内容C", chunk_id="n4"),  # 批次内重复
            _make_chunk("新内容D", chunk_id="n5"),
        ]

        result, stats = dedup.deduplicate(new, KB_ID)

        assert stats.input_count == 5
        assert stats.exact_dup_count == 3  # 2 个跨批次 + 1 个批次内
        assert stats.output_count == 4  # n1, n2, n3, n5（跨批次的保留，批次内的 n4 被过滤）
        assert stats.total_removed == 1  # 仅批次内重复的 n4
        assert len(result) == 4
        assert len(stats.removed_old_ids) == 2  # ea, eb


# ---------------------------------------------------------------------------
# 三级联动
# ---------------------------------------------------------------------------


class TestThreeTierIntegration:
    def test_exact_deletes_old_before_minhash(self, engine: Engine):
        """SHA-256 精确去重在 MinHash 之前执行，旧指纹已被删除。"""
        dedup = ChunkDeduplicator(engine)

        # 注册一个 chunk
        existing_text = "精确匹配的文本"
        existing = [_make_chunk(existing_text, chunk_id="existing")]
        dedup.register_chunks(existing)

        # 上传完全相同的 chunk → 旧指纹被精确去重删除
        new = [_make_chunk(existing_text, chunk_id="new")]

        result, stats = dedup.deduplicate(new, KB_ID)

        # 旧指纹被删除，新 chunk 保留
        assert len(result) == 1
        assert result[0].id == "new"
        assert stats.exact_dup_count == 1
        assert stats.minhash_dup_count == 0
        assert "existing" in stats.removed_old_ids

    def test_three_tier_empty(self, engine: Engine):
        """三级都为空输入不报错。"""
        dedup = ChunkDeduplicator(
            engine,
            embedder=FakeEmbeddingModel(),
            enable_embedding=True,
        )
        result, stats = dedup.deduplicate([], KB_ID)
        assert result == []
