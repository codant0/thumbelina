"""Tests for message attachments persistence and attachment CRUD (Task B1/B4/B6).

Covers the ``messages.attachments`` JSON column (serialize/deserialize with
fail-soft semantics) and the ``attachments`` table CRUD on
:class:`~thumbelina.repository.repository.ConversationRepository`.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import update

from thumbelina.repository.models import Message
from thumbelina.repository.repository import ConversationRepository


@pytest.fixture
def repo() -> ConversationRepository:
    """Real repository backed by in-memory SQLite (StaticPool, cross-thread)."""
    return ConversationRepository("sqlite:///:memory:")


def _set_raw_attachments(repo: ConversationRepository, conversation_id: str, raw: str | None):
    """Bypass the API and write the raw JSON column directly (corruption cases)."""
    with repo._get_session() as session:
        session.execute(
            update(Message)
            .where(Message.conversation_id == conversation_id)
            .values(attachments=raw)
        )
        session.commit()


def _first_message(messages: list[dict]) -> dict:
    assert len(messages) == 1
    return messages[0]


# ----------------------------------------------------------------------
# messages.attachments JSON column
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_message_with_attachments_round_trips(repo: ConversationRepository):
    """add_message(attachments=[...]) → get_messages 读回等价 list。"""
    conversation_id = await repo.create_conversation()
    refs = [
        {"id": "att-1", "mime": "image/png", "width": 3, "height": 2},
        {"id": "att-2", "alt": "截图"},
    ]

    await repo.add_message(
        conversation_id=conversation_id, role="user", content="看图", attachments=refs
    )

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] == refs


@pytest.mark.asyncio
async def test_add_message_without_attachments_reads_none(repo: ConversationRepository):
    """老消息（未携带附件）读回 attachments 为 None。"""
    conversation_id = await repo.create_conversation()

    await repo.add_message(conversation_id=conversation_id, role="user", content="hello")

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] is None


@pytest.mark.asyncio
async def test_empty_attachments_list_reads_none(repo: ConversationRepository):
    """空列表序列化为 NULL 列，读回 None（与老消息统一）。"""
    conversation_id = await repo.create_conversation()

    await repo.add_message(
        conversation_id=conversation_id, role="user", content="hello", attachments=[]
    )

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] is None


@pytest.mark.asyncio
async def test_malformed_json_reads_none(repo: ConversationRepository):
    """坏 JSON 行（手工 UPDATE 注入）读回 None（fail-soft，不炸读路径）。"""
    conversation_id = await repo.create_conversation()
    await repo.add_message(conversation_id=conversation_id, role="user", content="hello")
    _set_raw_attachments(repo, conversation_id, "{not-valid-json")

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] is None


@pytest.mark.asyncio
async def test_non_list_json_reads_none(repo: ConversationRepository):
    """合法 JSON 但不是 list（例如 object）→ None。"""
    conversation_id = await repo.create_conversation()
    await repo.add_message(conversation_id=conversation_id, role="user", content="hello")
    _set_raw_attachments(repo, conversation_id, json.dumps({"id": "att-1"}))

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] is None


@pytest.mark.asyncio
async def test_non_dict_items_are_filtered(repo: ConversationRepository):
    """list 中混入非 dict 元素 → 过滤掉，只保留 dict 项。"""
    conversation_id = await repo.create_conversation()
    await repo.add_message(conversation_id=conversation_id, role="user", content="hello")
    _set_raw_attachments(
        repo, conversation_id, json.dumps([{"id": "keep"}, "junk", 3, None])
    )

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] == [{"id": "keep"}]


@pytest.mark.asyncio
async def test_all_non_dict_items_read_none(repo: ConversationRepository):
    """过滤后为空 → None（而不是空列表）。"""
    conversation_id = await repo.create_conversation()
    await repo.add_message(conversation_id=conversation_id, role="user", content="hello")
    _set_raw_attachments(repo, conversation_id, json.dumps(["junk", 3]))

    message = _first_message(await repo.get_messages(conversation_id))
    assert message["attachments"] is None


# ----------------------------------------------------------------------
# attachments table CRUD
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attachment_crud_round_trip(repo: ConversationRepository):
    """create → get → get_attachments（缺 id 不在结果）→ delete → get 为 None。"""
    record = await repo.create_attachment(
        mime="image/png",
        size=24,
        relative_path="2026/09/abc.png",
        width=3,
        height=2,
        sha256="deadbeef",
    )

    assert record["id"]
    assert record["mime"] == "image/png"
    assert record["size"] == 24
    assert record["relative_path"] == "2026/09/abc.png"
    assert record["width"] == 3
    assert record["height"] == 2
    assert record["sha256"] == "deadbeef"
    assert record["created_at"] is not None

    fetched = await repo.get_attachment(record["id"])
    assert fetched == record

    batch = await repo.get_attachments([record["id"], "missing-id"])
    assert set(batch) == {record["id"]}
    assert batch[record["id"]] == record

    assert await repo.delete_attachment(record["id"]) is True
    assert await repo.get_attachment(record["id"]) is None


@pytest.mark.asyncio
async def test_get_attachments_empty_list_short_circuits(repo: ConversationRepository):
    assert await repo.get_attachments([]) == {}


@pytest.mark.asyncio
async def test_delete_missing_attachment_returns_false(repo: ConversationRepository):
    assert await repo.delete_attachment("no-such-attachment") is False
