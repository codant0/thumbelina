"""Unit tests for multimodal image block building (Task B5 / B6).

Covers :func:`thumbelina.agent.multimodal.build_image_blocks` (fail-soft
contract, dedupe, path-traversal guard), the ``_build_initial_messages``
assembly in :mod:`thumbelina.agent.graph`, and the fixed 765-token image
block placeholder in :mod:`thumbelina.agent.compression.base`.
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from thumbelina.agent.compression.base import (
    IMAGE_BLOCK_TOKEN_PLACEHOLDER,
    estimate_messages_tokens,
)
from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.agent.multimodal import build_image_blocks
from thumbelina.rag.retrieval.context_formatter import estimate_tokens

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _png_bytes(width: int = 3, height: int = 2) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)


def _fake_repo(records: dict) -> MagicMock:
    """Repository manager mock returning *records* from get_attachments."""
    repo = MagicMock()
    repo.get_attachments = AsyncMock(return_value=records)
    # TrajectoryRecorder awaits this when the attribute exists; keep it awaitable.
    repo.add_trajectory_events = AsyncMock()
    return repo


def _record(attachment_id: str, mime: str = "image/png", relative_path: str | None = None) -> dict:
    if relative_path is None:
        relative_path = f"2026/01/{attachment_id}.png"
    return {
        "id": attachment_id,
        "mime": mime,
        "size": 24,
        "width": 3,
        "height": 2,
        "sha256": "abc",
        "relative_path": relative_path,
        "created_at": None,
    }


def _make_agent(repo: MagicMock, root: Path | None) -> ThumbelinaAgent:
    """Real agent with a mock provider; no tools/checkpointer/memory."""
    provider = MagicMock()
    provider.chat_model = MagicMock()
    provider.chat_model.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    provider.chat_model.bind_tools.return_value = provider.chat_model
    agent = ThumbelinaAgent(llm_provider=provider, repository_manager=repo)
    agent.attachments_root = root
    return agent


async def _write_attachment(root: Path, attachment_id: str, data: bytes) -> str:
    relative_path = f"2026/01/{attachment_id}.png"
    full = root / relative_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return relative_path


# ----------------------------------------------------------------------
# build_image_blocks
# ----------------------------------------------------------------------


async def test_build_image_blocks_returns_standard_blocks(tmp_path: Path):
    """正常块结构：{type, base64, mime_type}，base64 与落盘字节一致。"""
    data = _png_bytes()
    root = tmp_path / "attachments"
    relative_path = await _write_attachment(root, "att-a", data)
    repo = _fake_repo({"att-a": _record("att-a", relative_path=relative_path)})

    blocks = await build_image_blocks(repo, [{"id": "att-a", "alt": "x"}], root)

    assert len(blocks) == 1
    block = blocks[0]
    assert set(block) == {"type", "base64", "mime_type"}
    assert block["type"] == "image"
    assert block["mime_type"] == "image/png"
    assert block["base64"] == base64.b64encode(data).decode("ascii")


async def test_build_image_blocks_skips_missing_record(tmp_path: Path):
    """记录缺失（get_attachments 结果不含该 id）→ 跳过。"""
    root = tmp_path / "attachments"
    relative_path = await _write_attachment(root, "att-a", _png_bytes())
    repo = _fake_repo({"att-a": _record("att-a", relative_path=relative_path)})

    blocks = await build_image_blocks(repo, [{"id": "att-a"}, {"id": "att-missing"}], root)

    assert len(blocks) == 1  # 只有存在的 att-a 产出块


async def test_build_image_blocks_empty_and_none_refs(tmp_path: Path):
    """refs 为 None / 空列表 → 返回空列表。"""
    root = tmp_path / "attachments"
    repo = _fake_repo({})
    assert await build_image_blocks(repo, None, root) == []
    assert await build_image_blocks(repo, [], root) == []


async def test_build_image_blocks_none_root_skips_all(tmp_path: Path):
    """root=None（未接线附件目录）→ 全部跳过返回 []。"""
    repo = _fake_repo({"att-a": _record("att-a")})
    assert await build_image_blocks(repo, [{"id": "att-a"}], None) == []


async def test_build_image_blocks_none_repo_skips_all(tmp_path: Path):
    """repository_manager=None → 无法解析记录，全部跳过。"""
    root = tmp_path / "attachments"
    await _write_attachment(root, "att-a", _png_bytes())
    assert await build_image_blocks(None, [{"id": "att-a"}], root) == []


async def test_build_image_blocks_skips_unreadable_file(tmp_path: Path):
    """读文件异常（记录在但文件缺失）→ 跳过该张，不抛。"""
    root = tmp_path / "attachments"
    repo = _fake_repo({"att-gone": _record("att-gone")})  # 文件从未写入

    blocks = await build_image_blocks(repo, [{"id": "att-gone"}], root)

    assert blocks == []


async def test_build_image_blocks_skips_path_traversal_record(tmp_path: Path):
    """relative_path 逃逸附件根目录 → 跳过（防穿越），不读取外部文件。"""
    root = tmp_path / "attachments"
    root.mkdir()
    # 外部文件真实存在：证明跳过来自穿越防护而不是文件缺失
    (tmp_path / "outside.png").write_bytes(_png_bytes())
    repo = _fake_repo({"att-evil": _record("att-evil", relative_path="../outside.png")})

    blocks = await build_image_blocks(repo, [{"id": "att-evil"}], root)

    assert blocks == []


async def test_build_image_blocks_dedupes_duplicate_ids_first_wins(tmp_path: Path):
    """重复 id 只保留首次出现，产出单个块。"""
    data = _png_bytes()
    root = tmp_path / "attachments"
    relative_path = await _write_attachment(root, "att-a", data)
    repo = _fake_repo({"att-a": _record("att-a", relative_path=relative_path)})

    blocks = await build_image_blocks(repo, [{"id": "att-a"}, {"id": "att-a"}], root)

    assert len(blocks) == 1
    assert blocks[0]["base64"] == base64.b64encode(data).decode("ascii")


# ----------------------------------------------------------------------
# _build_initial_messages assembly
# ----------------------------------------------------------------------


async def test_build_initial_messages_text_plus_attachments(tmp_path: Path):
    """text + 附件 → list content，首块为 text，其后跟图像块。"""
    data = _png_bytes()
    root = tmp_path / "attachments"
    relative_path = await _write_attachment(root, "att-a", data)
    repo = _fake_repo({"att-a": _record("att-a", relative_path=relative_path)})
    agent = _make_agent(repo, root)

    messages = await agent._build_initial_messages(
        "看这张图", None, attachments=[{"id": "att-a"}]
    )

    human = messages[-1]
    assert isinstance(human, HumanMessage)
    assert isinstance(human.content, list)
    assert human.content[0] == {"type": "text", "text": "看这张图"}
    assert human.content[1]["type"] == "image"
    assert human.content[1]["base64"] == base64.b64encode(data).decode("ascii")


async def test_build_initial_messages_pure_image_only_blocks(tmp_path: Path):
    """纯图片（文本为空）→ content 全部为图像块。"""
    root = tmp_path / "attachments"
    relative_path = await _write_attachment(root, "att-a", _png_bytes())
    repo = _fake_repo({"att-a": _record("att-a", relative_path=relative_path)})
    agent = _make_agent(repo, root)

    messages = await agent._build_initial_messages("", None, attachments=[{"id": "att-a"}])

    human = messages[-1]
    assert isinstance(human.content, list)
    assert human.content
    assert all(
        isinstance(block, dict) and block.get("type") == "image" for block in human.content
    )


async def test_build_initial_messages_unresolvable_blocks_fall_back_to_string(
    tmp_path: Path,
):
    """blocks 解析为空（root 未接线）→ 回退纯字符串 content。"""
    repo = _fake_repo({"att-a": _record("att-a")})
    agent = _make_agent(repo, root=None)  # 未配置附件根目录 → 全部跳过

    messages = await agent._build_initial_messages(
        "看这张图", None, attachments=[{"id": "att-a"}]
    )

    human = messages[-1]
    assert isinstance(human, HumanMessage)
    assert human.content == "看这张图"


async def test_build_initial_messages_missing_record_falls_back_to_string(tmp_path: Path):
    """附件记录缺失 → blocks 为空 → 回退纯字符串 content。"""
    repo = _fake_repo({})  # get_attachments 返回空 → 记录缺失
    root = tmp_path / "attachments"
    agent = _make_agent(repo, root)

    messages = await agent._build_initial_messages(
        "看这张图", None, attachments=[{"id": "att-a"}]
    )

    assert messages[-1].content == "看这张图"


async def test_build_initial_messages_without_attachments_matches_legacy_path(tmp_path: Path):
    """attachments=None → 与旧路径一致：str content。"""
    agent = _make_agent(_fake_repo({}), tmp_path / "attachments")

    messages = await agent._build_initial_messages("plain text", None, attachments=None)

    human = messages[-1]
    assert isinstance(human, HumanMessage)
    assert human.content == "plain text"
    assert isinstance(human.content, str)


# ----------------------------------------------------------------------
# Token estimation
# ----------------------------------------------------------------------


def test_estimate_messages_tokens_counts_image_block_placeholder():
    """带 2 个 image 块的消息 = 文本估算 + 2×765。"""
    text = "hello"
    message = HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image", "base64": "aaa", "mime_type": "image/png"},
            {"type": "image", "base64": "bbb", "mime_type": "image/jpeg"},
        ]
    )

    assert estimate_messages_tokens([message]) == (
        estimate_tokens(text) + 2 * IMAGE_BLOCK_TOKEN_PLACEHOLDER
    )


def test_estimate_messages_tokens_unaffected_for_plain_text():
    """纯文本消息不受占位影响。"""
    message = HumanMessage(content="hello")

    assert estimate_messages_tokens([message]) == estimate_tokens("hello")
