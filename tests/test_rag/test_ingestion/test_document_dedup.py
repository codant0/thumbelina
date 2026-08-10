"""Tests for DocumentDeduplicator."""

from __future__ import annotations

import uuid

from thumbelina.rag.common.models import Document, DocumentType
from thumbelina.rag.common.orm_models import DocumentRecord
from thumbelina.rag.ingestion.document_dedup import (
    DedupAction,
    DedupResult,
    DocumentDeduplicator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_document(
    sha256: bytes = b"\xaa" * 32,
    sim_hash_64: bytes = b"\xbb" * 8,
    name: str = "test.md",
) -> Document:
    return Document(
        id=uuid.uuid4().hex,
        name=name,
        source_uri="/tmp/test.md",
        document_type=DocumentType.MARKDOWN,
        content="hello world",
        sha256=sha256,
        sim_hash_64=sim_hash_64,
    )


def _make_doc_record(
    doc_id: str = "existing-1",
    name: str = "old.md",
    sha256: bytes = b"\xaa" * 32,
    sim_hash_64: bytes = b"\xbb" * 8,
) -> DocumentRecord:
    record = DocumentRecord(
        id=doc_id,
        knowledge_base_id="0",
        name=name,
        source_uri="/tmp/old.md",
        doc_type=".md",
        sha256=sha256,
        sim_hash_64=sim_hash_64,
    )
    return record


class FakeDocRepo:
    """Fake DocumentRepository for testing DocumentDeduplicator."""

    def __init__(
        self,
        sha256_result: DocumentRecord | None = None,
        simhash_results: list[tuple[DocumentRecord, int]] | None = None,
    ):
        self._sha256_result = sha256_result
        self._simhash_results = simhash_results or []
        self.deleted_ids: list[str] = []

    def _get_by_sha256(self, sha256: bytes) -> DocumentRecord | None:
        if self._sha256_result and self._sha256_result.sha256 == sha256:
            return self._sha256_result
        return None

    def find_by_simhash_sync(
        self,
        query_sim_hash: bytes,
        threshold: int,
        direction: str = "le",
        kb_id: str | None = None,
        limit: int = 100,
    ) -> list[tuple[DocumentRecord, int]]:
        return self._simhash_results

    def delete(self, doc_id: str) -> bool:
        self.deleted_ids.append(doc_id)
        return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDedupAction:
    def test_enum_values(self):
        assert DedupAction.PASS.value == "pass"
        assert DedupAction.EXACT_DUPLICATE.value == "exact_duplicate"
        assert DedupAction.NEAR_DUPLICATE.value == "near_duplicate"
        assert DedupAction.IDENTICAL_SIMHASH.value == "identical_simhash"


class TestDedupResult:
    def test_defaults(self):
        result = DedupResult(action=DedupAction.PASS)
        assert result.message == ""
        assert result.existing_doc_id is None
        assert result.existing_doc_name is None


class TestDocumentDeduplicator:
    """Tests for DocumentDeduplicator.check()."""

    # ---- SHA-256 精确去重 ----

    def test_pass_when_no_existing_doc(self):
        """无重复文档 → PASS。"""
        repo = FakeDocRepo(sha256_result=None)
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document()

        result = dedup.check(doc)

        assert result.action == DedupAction.PASS
        assert result.existing_doc_id is None

    def test_exact_duplicate_sha256(self):
        """SHA-256 匹配 → EXACT_DUPLICATE。"""
        existing = _make_doc_record()
        repo = FakeDocRepo(sha256_result=existing)
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\xaa" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.EXACT_DUPLICATE
        assert result.existing_doc_id == "existing-1"
        assert result.existing_doc_name == "old.md"
        assert "请勿重复上传" in result.message

    def test_skip_exact_when_sha256_empty(self):
        """sha256 为空时跳过精确去重，直接进入 SimHash 层。"""
        existing = _make_doc_record()
        repo = FakeDocRepo(
            sha256_result=existing,
            simhash_results=[(existing, 2)],
        )
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"")

        result = dedup.check(doc)

        # sha256 为空跳过第一层，SimHash 距离=2 → NEAR_DUPLICATE
        assert result.action == DedupAction.NEAR_DUPLICATE

    # ---- SimHash 模糊去重 ----

    def test_identical_simhash_distance_0(self):
        """SimHash 距离 = 0 → IDENTICAL_SIMHASH。"""
        existing = _make_doc_record(doc_id="sim-0", name="identical.md")
        repo = FakeDocRepo(simhash_results=[(existing, 0)])
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32)  # sha256 不匹配，进入第二层

        result = dedup.check(doc)

        assert result.action == DedupAction.IDENTICAL_SIMHASH
        assert result.existing_doc_id == "sim-0"
        assert result.existing_doc_name == "identical.md"
        assert "请勿重复上传" in result.message

    def test_near_duplicate_simhash_distance_2(self):
        """SimHash 距离 1~3 → NEAR_DUPLICATE。"""
        existing = _make_doc_record(doc_id="sim-near", name="similar.md")
        repo = FakeDocRepo(simhash_results=[(existing, 2)])
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.NEAR_DUPLICATE
        assert result.existing_doc_id == "sim-near"
        assert result.existing_doc_name == "similar.md"
        assert "高度近似" in result.message

    def test_near_duplicate_respects_threshold(self):
        """SimHash 距离 = threshold 仍视为近似。"""
        existing = _make_doc_record()
        repo = FakeDocRepo(simhash_results=[(existing, 3)])
        dedup = DocumentDeduplicator(doc_repo=repo, simhash_threshold=3)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.NEAR_DUPLICATE

    def test_beyond_threshold_pass(self):
        """SimHash 距离 > threshold → PASS（不会出现在结果中）。"""
        # 距离 4 > threshold 3，但 find_by_simhash_sync 已按阈值过滤
        # 如果返回空列表表示无近似文档
        repo = FakeDocRepo(simhash_results=[])
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.PASS

    def test_skip_simhash_when_empty(self):
        """sim_hash_64 为空时跳过模糊去重。"""
        repo = FakeDocRepo(simhash_results=[(_make_doc_record(), 1)])
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32, sim_hash_64=b"")

        result = dedup.check(doc)

        assert result.action == DedupAction.PASS

    # ---- 优先级：SHA-256 先于 SimHash ----

    def test_sha256_takes_priority_over_simhash(self):
        """SHA-256 匹配时不再检查 SimHash。"""
        existing = _make_doc_record()
        repo = FakeDocRepo(
            sha256_result=existing,
            simhash_results=[(_make_doc_record(doc_id="other", name="other.md"), 1)],
        )
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\xaa" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.EXACT_DUPLICATE

    # ---- 自定义阈值 ----

    def test_custom_simhash_threshold(self):
        """自定义 simhash_threshold 生效。"""
        # 距离 = 5，阈值 = 10 时应视为近似
        existing = _make_doc_record()
        repo = FakeDocRepo(simhash_results=[(existing, 5)])
        dedup = DocumentDeduplicator(doc_repo=repo, simhash_threshold=10)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.NEAR_DUPLICATE


class TestDocumentDeduplicatorIntegration:
    """与 Indexer 集成的场景测试。"""

    def test_near_duplicate_existing_doc_id_for_deletion(self):
        """NEAR_DUPLICATE 结果中包含正确的 existing_doc_id，供 Indexer 删除。"""
        existing = _make_doc_record(doc_id="to-delete", name="stale.md")
        repo = FakeDocRepo(simhash_results=[(existing, 1)])
        dedup = DocumentDeduplicator(doc_repo=repo)  # type: ignore[arg-type]
        doc = _make_document(sha256=b"\x00" * 32)

        result = dedup.check(doc)

        assert result.action == DedupAction.NEAR_DUPLICATE
        assert result.existing_doc_id == "to-delete"
