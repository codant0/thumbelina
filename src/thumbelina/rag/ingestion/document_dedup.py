"""文档级去重器。

两级漏斗策略：

    1. SHA-256 精确去重（微秒级）—— 完全相同的文件直接跳过
    2. SimHash 汉明距离模糊去重（毫秒级）—— 高度近似的文件覆盖旧文档

典型用法::

    dedup = DocumentDeduplicator(doc_repo)
    result = dedup.check(document)
    if result.action == DedupAction.EXACT_DUPLICATE:
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from thumbelina.rag.knowledge_base.models import Document
from thumbelina.rag.knowledge_base.repository import DocumentRepository

logger = logging.getLogger(__name__)


class DedupAction(Enum):
    """去重判定结果枚举。"""

    PASS = "pass"
    """无重复，可继续处理。"""

    EXACT_DUPLICATE = "exact_duplicate"
    """SHA-256 完全相同，应跳过。"""

    NEAR_DUPLICATE = "near_duplicate"
    """SimHash 高度近似，应删除旧文档后覆盖。"""

    IDENTICAL_SIMHASH = "identical_simhash"
    """SimHash 汉明距离 = 0，应跳过。"""


@dataclass
class DedupResult:
    """去重检查结果。"""

    action: DedupAction
    message: str = ""
    existing_doc_id: str | None = None
    """需要处理的旧文档 ID（EXACT_DUPLICATE / IDENTICAL_SIMHASH / NEAR_DUPLICATE 时有值）。"""
    existing_doc_name: str | None = None


class DocumentDeduplicator:
    """文档级去重器。

    对上传文档执行两级漏斗去重：

    - **第一层**：SHA-256 精确匹配，完全相同的文件直接跳过。
    - **第二层**：SimHash 汉明距离粗筛，距离 = 0 视为相同，距离 1 ~ threshold 视为近似。

    Parameters
    ----------
    doc_repo:
        文档元数据仓库，提供 SHA-256 和 SimHash 查询能力。
    simhash_threshold:
        SimHash 汉明距离阈值，距离 ≤ 该值视为近似重复，默认 3。
    """

    def __init__(
        self,
        doc_repo: DocumentRepository,
        simhash_threshold: int = 3,
    ) -> None:
        self.doc_repo = doc_repo
        self.simhash_threshold = simhash_threshold

    def check(self, document: Document) -> DedupResult:
        """对单个文档执行去重检查。

        按 SHA-256 → SimHash 的顺序进行两级判定，命中即返回。

        Parameters
        ----------
        document:
            待检查的文档对象，需包含 ``sha256`` 和 ``sim_hash_64`` 字段。

        Returns
        -------
        DedupResult
            去重判定结果，包含动作类型和可选的旧文档信息。
        """
        # 第一层：SHA-256 精确去重
        result = self._check_sha256(document)
        if result.action != DedupAction.PASS:
            return result

        # 第二层：SimHash 模糊去重
        return self._check_simhash(document)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _check_sha256(self, document: Document) -> DedupResult:
        """第一层：SHA-256 精确去重。"""
        if not document.sha256:
            return DedupResult(action=DedupAction.PASS)

        existing = self.doc_repo._get_by_sha256(document.sha256)
        if existing:
            msg = f"存在相同文件 [{existing.name}], 请勿重复上传"
            logger.info(msg)
            return DedupResult(
                action=DedupAction.EXACT_DUPLICATE,
                message=msg,
                existing_doc_id=existing.id,
                existing_doc_name=existing.name,
            )
        return DedupResult(action=DedupAction.PASS)

    def _check_simhash(self, document: Document) -> DedupResult:
        """第二层：SimHash 汉明距离模糊去重。"""
        if not document.sim_hash_64:
            return DedupResult(action=DedupAction.PASS)

        similar_docs = self.doc_repo.find_by_simhash_sync(
            query_sim_hash=document.sim_hash_64,
            threshold=self.simhash_threshold,
        )

        if not similar_docs:
            return DedupResult(action=DedupAction.PASS)

        # find_by_simhash 按汉明距离升序返回，遍历按距离分类处理
        for doc_record, distance in similar_docs:
            if distance == 0:
                msg = f"存在相同文件 [{doc_record.name}], 请勿重复上传"
                logger.info(msg)
                return DedupResult(
                    action=DedupAction.IDENTICAL_SIMHASH,
                    message=msg,
                    existing_doc_id=doc_record.id,
                    existing_doc_name=doc_record.name,
                )
            else:
                # 高度近似（1 ~ simhash_threshold），标记需覆盖
                msg = f"存在与文件 {doc_record.name} 高度近似的文档，删除原始文档重新上传"
                logger.info(msg)
                return DedupResult(
                    action=DedupAction.NEAR_DUPLICATE,
                    message=msg,
                    existing_doc_id=doc_record.id,
                    existing_doc_name=doc_record.name,
                )

        return DedupResult(action=DedupAction.PASS)
