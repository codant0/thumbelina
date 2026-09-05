"""多模态图像内容块构建工具(设计文档 §3.3 / Task B5)。

聊天路径不经过 ``llm/base._to_langchain_messages``:``agent/nodes.py`` 的
``call_model`` 直调 LangChain 模型,图像块随 graph state 透传。本模块把
附件引用(id 列表)解析为 LangChain 标准 v1 图像内容块::

    {"type": "image", "base64": "<raw base64>", "mime_type": "image/png"}

**禁止嵌套 ``source`` 结构**(如 ``{type: "image", source: {...}}``)——
langchain-ollama 的 ``is_data_content_block`` 只认扁平的 ``base64`` /
``url`` 键,嵌套会直接抛 ValueError。provider 层(``llm/*.py``)零改动,
统一标准块由已装 LangChain 各 provider 内部转换;不做模型白名单——
provider 报错走现有 WS ``error`` 帧由前端展示。
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from thumbelina.repository.manager import RepositoryManager

logger = logging.getLogger(__name__)


async def build_image_blocks(
    repository_manager: RepositoryManager | None,
    attachment_refs: list[dict[str, object]] | None,
    root: Path | None,
) -> list[dict[str, object]]:
    """把附件引用解析为 LangChain 标准 v1 图像内容块。

    fail-soft:无 repo / 无 root / 记录缺失 / 元数据缺失 / 文件读取
    异常 → 跳过该张并 ``logger.warning``,绝不抛出。单文件 ≤10MB 由
    上传端保证,这里不重复限制。

    Parameters
    ----------
    repository_manager:
        仓储管理器;``None`` 时无法解析记录,全部跳过。
    attachment_refs:
        附件引用列表(``[{id, alt?}]``,来自 WS 上行);每项必须是含
        非空字符串 ``id`` 键的 dict,否则跳过该张。重复 ``id`` 以首次
        出现为准(其余跳过),避免同一张图重复进入模型。
    root:
        附件根目录(``agent.attachments_root``);``None`` 时全部跳过。

    Returns
    -------
    list[dict[str, object]]
        图像内容块列表(可空),供 ``HumanMessage(content=...)`` 组装。
    """
    if not attachment_refs:
        return []

    # 去重:同一 id 多次引用只保留首次出现,避免同一张图重复发给模型。
    ids: list[str] = []
    seen_ids: set[str] = set()
    for ref in attachment_refs:
        attachment_id = ref.get("id") if isinstance(ref, dict) else None
        if isinstance(attachment_id, str) and attachment_id:
            if attachment_id in seen_ids:
                logger.info("Duplicate attachment id %s; keeping first occurrence", attachment_id)
                continue
            seen_ids.add(attachment_id)
            ids.append(attachment_id)
        else:
            logger.warning("Skipping malformed attachment ref: %r", ref)
    if not ids:
        return []

    if repository_manager is None:
        logger.warning("No repository manager; skipping %d image attachment(s)", len(ids))
        return []
    if root is None:
        logger.warning("No attachments root; skipping %d image attachment(s)", len(ids))
        return []

    # 一次批量取记录;缺失的 id 不出现在结果里(RepositoryManager 契约)。
    try:
        records = await repository_manager.get_attachments(ids)
    except Exception:
        logger.warning(
            "Failed to load %d attachment record(s); skipping all", len(ids), exc_info=True
        )
        return []

    resolved_root = root.resolve()
    blocks: list[dict[str, object]] = []
    for attachment_id in ids:
        record = records.get(attachment_id)
        if record is None:
            logger.warning("Attachment %s not found; skipping", attachment_id)
            continue
        mime = record.get("mime")
        relative_path = record.get("relative_path")
        if not isinstance(mime, str) or not mime:
            logger.warning("Attachment %s has no mime; skipping", attachment_id)
            continue
        if not isinstance(relative_path, str) or not relative_path:
            logger.warning("Attachment %s has no relative_path; skipping", attachment_id)
            continue
        try:
            # 路径穿越防护:与上传路由同规则,逃逸附件根目录视为坏记录。
            full = (root / relative_path).resolve()
            if not full.is_relative_to(resolved_root):
                raise ValueError("path escapes attachments root")
            data = full.read_bytes()
        except Exception:
            logger.warning(
                "Failed to read attachment %s (%s); skipping",
                attachment_id,
                relative_path,
                exc_info=True,
            )
            continue
        blocks.append(
            {
                "type": "image",
                "base64": base64.b64encode(data).decode("ascii"),
                "mime_type": mime,
            }
        )
    return blocks
