"""Tests for the WebSocket multimodal attachment protocol (Task B3 / B6).

Uses a real :class:`ThumbelinaAgent` (mock LLM provider, in-memory SQLite
repository) so the full production path is exercised: WS frame validation →
attachment existence check → user-message persistence → image block
assembly → LLM call. No real LLM requests are made.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.repository.repository import ConversationRepository

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _mock_provider() -> MagicMock:
    """Mock LLMProvider whose chat_model records ainvoke calls."""
    provider = MagicMock()
    provider.chat_model = MagicMock()
    provider.chat_model.ainvoke = AsyncMock(return_value=AIMessage(content="Agent response"))
    provider.chat_model.bind_tools.return_value = provider.chat_model
    return provider


def _png_bytes(width: int = 3, height: int = 2) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)


def _seed_attachment(
    root: Path,
    repo: ConversationRepository,
    data: bytes | None = None,
    mime: str = "image/png",
) -> dict:
    """Write bytes below *root* and record the attachment; returns metadata."""
    data = data if data is not None else _png_bytes()
    relative_path = f"2026/01/seed-{uuid4().hex}.png"
    full = root / relative_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return asyncio.run(
        repo.create_attachment(
            mime=mime,
            size=len(data),
            relative_path=relative_path,
            width=3,
            height=2,
            sha256=hashlib.sha256(data).hexdigest(),
        )
    )


def _collect_until_done(ws, max_messages: int = 15) -> list[dict]:
    frames = []
    for _ in range(max_messages):
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("done"):
            break
    return frames


def _last_human_message(client) -> HumanMessage:
    """The final message the (mock) LLM received in the last ainvoke call."""
    chat_model = client.app.state.agent.llm_provider.chat_model
    messages = chat_model.ainvoke.call_args[0][0]
    return messages[-1]


def _get_messages(repo: ConversationRepository, conversation_id: str) -> list[dict]:
    return asyncio.run(repo.get_messages(conversation_id))


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def ws_repo() -> ConversationRepository:
    return ConversationRepository("sqlite:///:memory:")


@pytest.fixture
def attachments_root(tmp_path: Path) -> Path:
    return tmp_path / "attachments"


@pytest.fixture
def conversation_id(ws_repo: ConversationRepository) -> str:
    return asyncio.run(ws_repo.create_conversation())


@pytest.fixture
def multimodal_client(client, ws_repo, attachments_root: Path):
    """Client with a real agent (mock LLM) + real repository + non-streaming."""
    client.app.state.config.repository.attachments_directory = str(attachments_root)
    client.app.state.config.llm.streaming_enabled = False
    agent = ThumbelinaAgent(llm_provider=_mock_provider(), repository_manager=ws_repo)
    client.app.state.agent = agent
    client.app.state.repository_manager = ws_repo
    return client


# ----------------------------------------------------------------------
# Valid multimodal turns
# ----------------------------------------------------------------------


def test_valid_frame_persists_attachments_and_sends_image_blocks(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """text + 2 附件：user 消息带富化后的 attachments JSON；LLM 收到 2 个图像块。

    设计 §3.2/§4.2:上行原始引用 ``[{id, alt?}]`` 在 WS 层用附件记录补全为
    ``[{id, mime, width, height, alt?}]`` 后落库(保持原顺序与重复项)。
    """
    first = _seed_attachment(attachments_root, ws_repo, _png_bytes(3, 2))
    second = _seed_attachment(attachments_root, ws_repo, _png_bytes(9, 4))
    refs = [{"id": first["id"], "alt": "first"}, {"id": second["id"]}]

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {"message": "看这两张图", "conversation_id": conversation_id, "attachments": refs}
        )
        frames = _collect_until_done(ws)

    assert any(frame.get("response") == "Agent response" for frame in frames)
    assert any(frame.get("done") for frame in frames)
    assert not any("error" in frame for frame in frames)

    # 持久化的 user 消息携带富化后的 attachments JSON(读回等价列表)
    messages = _get_messages(ws_repo, conversation_id)
    user_messages = [m for m in messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "看这两张图"
    assert user_messages[0]["attachments"] == [
        {"id": first["id"], "mime": "image/png", "width": 3, "height": 2, "alt": "first"},
        {"id": second["id"], "mime": "image/png", "width": 3, "height": 2},
    ]

    # fake LLM 收到的最后一条 HumanMessage：list content，首块 text + 2 图像块
    human = _last_human_message(multimodal_client)
    assert isinstance(human, HumanMessage)
    assert isinstance(human.content, list)
    text_blocks = [b for b in human.content if isinstance(b, dict) and b.get("type") == "text"]
    image_blocks = [b for b in human.content if isinstance(b, dict) and b.get("type") == "image"]
    assert text_blocks and text_blocks[0]["text"] == "看这两张图"
    assert len(image_blocks) == 2
    assert image_blocks[0]["base64"] == base64.b64encode(_png_bytes(3, 2)).decode("ascii")
    assert image_blocks[0]["mime_type"] == "image/png"
    assert image_blocks[1]["base64"] == base64.b64encode(_png_bytes(9, 4)).decode("ascii")
    assert image_blocks[1]["mime_type"] == "image/png"


def test_empty_text_with_attachments_passes_guard(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """message="" + 附件 → 不回 Empty message，纯图像块进入模型。"""
    record = _seed_attachment(attachments_root, ws_repo)

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "",
                "conversation_id": conversation_id,
                "attachments": [{"id": record["id"]}],
            }
        )
        frames = _collect_until_done(ws)

    assert any(frame.get("done") for frame in frames)
    assert not any(frame.get("error") == "Empty message" for frame in frames)

    messages = _get_messages(ws_repo, conversation_id)
    user_messages = [m for m in messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == ""
    assert user_messages[0]["attachments"] == [
        {"id": record["id"], "mime": "image/png", "width": 3, "height": 2}
    ]

    human = _last_human_message(multimodal_client)
    assert isinstance(human.content, list)
    # 纯图片轮：全部为图像块，没有文本块
    assert human.content
    assert all(isinstance(block, dict) and block.get("type") == "image" for block in human.content)


def test_duplicate_attachment_ids_send_single_image_block(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """重复 id（[{id:a},{id:a}]）→ LLM 只收到 1 个图像块（first-wins）。"""
    record = _seed_attachment(attachments_root, ws_repo)
    refs = [{"id": record["id"]}, {"id": record["id"]}]

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "重复图", "conversation_id": conversation_id, "attachments": refs})
        frames = _collect_until_done(ws)

    assert any(frame.get("done") for frame in frames)

    human = _last_human_message(multimodal_client)
    image_blocks = [b for b in human.content if isinstance(b, dict) and b.get("type") == "image"]
    assert len(image_blocks) == 1

    # 持久化层保留原始引用列表的顺序与重复项(富化补全元数据;去重只发生在模型视图)
    enriched = {"id": record["id"], "mime": "image/png", "width": 3, "height": 2}
    user_messages = [m for m in _get_messages(ws_repo, conversation_id) if m["role"] == "user"]
    assert user_messages[0]["attachments"] == [enriched, enriched]


# ----------------------------------------------------------------------
# Rejected frames
# ----------------------------------------------------------------------


def test_missing_attachment_id_rejects_without_persist_or_generation(
    multimodal_client, ws_repo, conversation_id
):
    """引用不存在 id → 错误帧含 missing_attachment_ids，且不落库不生成。"""
    chat_model = multimodal_client.app.state.agent.llm_provider.chat_model

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "hello",
                "conversation_id": conversation_id,
                "attachments": [{"id": "missing-1"}, {"id": "missing-2"}],
            }
        )
        frame = ws.receive_json()
        assert frame["error"] == "Invalid attachment"
        assert frame["missing_attachment_ids"] == ["missing-1", "missing-2"]
        assert frame["conversation_id"] == conversation_id

        # 连接仍然可用；确认没有生成任务在跑
        ws.send_json({"stop": True})
        assert ws.receive_json().get("stopped") is True

    assert _get_messages(ws_repo, conversation_id) == []
    assert not chat_model.ainvoke.called


def test_missing_attachment_error_frame_uses_resolved_conversation_id(multimodal_client, ws_repo):
    """回归:首条消息(无 conversation_id)引用缺失附件 → 错误帧携带服务端
    新建会话的 cid,而非 parsed.conversation_id(None)。前端依赖该 id 清除
    等待态;带 None 会白等到 90s 超时。"""
    chat_model = multimodal_client.app.state.agent.llm_provider.chat_model

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "hello", "attachments": [{"id": "missing-1"}]})
        created = ws.receive_json()
        assert set(created.keys()) == {"conversation_created"}
        cid = created["conversation_created"]

        frame = ws.receive_json()
        assert frame["error"] == "Invalid attachment"
        assert frame["missing_attachment_ids"] == ["missing-1"]
        assert frame["conversation_id"] == cid

    assert _get_messages(ws_repo, cid) == []
    assert not chat_model.ainvoke.called


def test_more_than_four_attachments_rejected_by_validator(
    multimodal_client, ws_repo, conversation_id
):
    """超 4 个附件 → validator 拒绝（Invalid message format 错误帧）。"""
    chat_model = multimodal_client.app.state.agent.llm_provider.chat_model
    refs = [{"id": f"att-{i}"} for i in range(5)]

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {"message": "too many", "conversation_id": conversation_id, "attachments": refs}
        )
        frame = ws.receive_json()
        assert frame == {"error": "Invalid message format"}

        ws.send_json({"stop": True})
        assert ws.receive_json().get("stopped") is True

    assert _get_messages(ws_repo, conversation_id) == []
    assert not chat_model.ainvoke.called


# ----------------------------------------------------------------------
# WeChat-bound conversations (设计 §2:附件端到端放行)
# ----------------------------------------------------------------------


def test_wechat_conversation_with_text_persists_attachments_and_forwards_images(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """微信会话 + 文本 + 附件（设计 §2 取代旧"丢弃"行为）：

    - 富化后的 refs 随 user 消息持久化；
    - LLM 收到文本块 + 图像块（多模态理解）；
    - 回复文本先同步微信，随后附件字节经 channel.send_image 逐张转发。
    """
    record = _seed_attachment(attachments_root, ws_repo)
    wechat_channel = MagicMock()
    wechat_channel.send_message = AsyncMock()
    wechat_channel.send_image = AsyncMock()
    wechat_channel._last_wechat_user_id = "wxid_friend"
    wechat_channel._last_context_token = "tok-123"
    multimodal_client.app.state.wechat_channel = wechat_channel
    multimodal_client.app.state.wechat_conversation_id = conversation_id

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "带图说话",
                "conversation_id": conversation_id,
                "attachments": [{"id": record["id"]}],
            }
        )
        frames = _collect_until_done(ws)
        # 微信转发发生在 done 帧之后的同一生成任务内；保持连接打开直到转发完成，
        # 避免连接关闭取消任务造成 flake。
        for _ in range(100):
            if wechat_channel.send_message.await_count and wechat_channel.send_image.await_count:
                break
            time.sleep(0.02)

    assert any(frame.get("response") == "Agent response" for frame in frames)
    assert any(frame.get("done") for frame in frames)
    assert not any("error" in frame for frame in frames)

    # 富化后的 refs 随 user 消息持久化（设计 §2:不再丢弃）
    user_messages = [m for m in _get_messages(ws_repo, conversation_id) if m["role"] == "user"]
    assert user_messages[0]["content"] == "带图说话"
    assert user_messages[0]["attachments"] == [
        {"id": record["id"], "mime": "image/png", "width": 3, "height": 2}
    ]

    # LLM 收到 list content：文本块 + 图像块（图像字节来自附件根目录）
    human = _last_human_message(multimodal_client)
    assert isinstance(human, HumanMessage)
    assert isinstance(human.content, list)
    text_blocks = [b for b in human.content if isinstance(b, dict) and b.get("type") == "text"]
    image_blocks = [b for b in human.content if isinstance(b, dict) and b.get("type") == "image"]
    assert text_blocks and text_blocks[0]["text"] == "带图说话"
    assert len(image_blocks) == 1
    assert image_blocks[0]["base64"] == base64.b64encode(_png_bytes()).decode("ascii")
    assert image_blocks[0]["mime_type"] == "image/png"

    # 回复文本先同步给微信
    assert wechat_channel.send_message.await_count == 1
    assert wechat_channel.send_message.call_args.args[1] == "Agent response"
    assert wechat_channel.send_message.call_args.kwargs.get("context_token") == "tok-123"

    # 附件图片随后逐张转发（读取附件根目录下的真实字节）
    assert wechat_channel.send_image.await_count == 1
    forward_args = wechat_channel.send_image.await_args
    assert forward_args.args[0] == "wxid_friend"
    assert forward_args.args[1] == _png_bytes()
    assert forward_args.kwargs.get("context_token") == "tok-123"


def test_wechat_conversation_image_only_message_proceeds(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """微信 + 纯图片（设计 §2 取代旧错误帧拒绝）：照常生成，无错误帧，
    user 消息空文本 + 富化 refs 落库，LLM 收到纯图像块 HumanMessage。"""
    chat_model = multimodal_client.app.state.agent.llm_provider.chat_model
    record = _seed_attachment(attachments_root, ws_repo)
    multimodal_client.app.state.wechat_conversation_id = conversation_id

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "",
                "conversation_id": conversation_id,
                "attachments": [{"id": record["id"]}],
            }
        )
        frames = _collect_until_done(ws)

    assert any(frame.get("response") == "Agent response" for frame in frames)
    assert any(frame.get("done") for frame in frames)
    assert not any("error" in frame for frame in frames)

    user_messages = [m for m in _get_messages(ws_repo, conversation_id) if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == ""
    assert user_messages[0]["attachments"] == [
        {"id": record["id"], "mime": "image/png", "width": 3, "height": 2}
    ]

    assert chat_model.ainvoke.called
    human = _last_human_message(multimodal_client)
    assert isinstance(human.content, list)
    assert human.content
    assert all(isinstance(block, dict) and block.get("type") == "image" for block in human.content)


def test_wechat_conversation_send_image_failure_degrades_text_only(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """单张图片转发失败（send_image 抛错）→ 仅 warning 跳过该图，
    文本回复照常同步，无错误帧、不影响本轮其余部分。"""
    record = _seed_attachment(attachments_root, ws_repo)
    wechat_channel = MagicMock()
    wechat_channel.send_message = AsyncMock()
    wechat_channel.send_image = AsyncMock(side_effect=RuntimeError("CDN upload failed"))
    wechat_channel._last_wechat_user_id = "wxid_friend"
    wechat_channel._last_context_token = "tok-123"
    multimodal_client.app.state.wechat_channel = wechat_channel
    multimodal_client.app.state.wechat_conversation_id = conversation_id

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "带图说话",
                "conversation_id": conversation_id,
                "attachments": [{"id": record["id"]}],
            }
        )
        frames = _collect_until_done(ws)
        for _ in range(100):
            if wechat_channel.send_message.await_count and wechat_channel.send_image.await_count:
                break
            time.sleep(0.02)

    assert not any("error" in frame for frame in frames)
    # 文本回复不受图片转发失败影响
    assert wechat_channel.send_message.await_count == 1
    assert wechat_channel.send_message.call_args.args[1] == "Agent response"
    # 图片发送尝试过一次即失败;refs 仍随消息落库(多模态理解不受影响)
    assert wechat_channel.send_image.await_count == 1
    user_messages = [m for m in _get_messages(ws_repo, conversation_id) if m["role"] == "user"]
    assert user_messages[0]["attachments"] == [
        {"id": record["id"], "mime": "image/png", "width": 3, "height": 2}
    ]


def test_wechat_conversation_pure_image_empty_response_still_forwards_images(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """微信 + 纯图片 + 模型空回复：文本同步跳过，但附件图片仍逐张转发。

    回归：转发曾嵌在 ``is_wechat_conversation and full_response`` 内，
    空回复的纯图片轮会静默丢弃 send_image。
    """
    record = _seed_attachment(attachments_root, ws_repo)
    wechat_channel = MagicMock()
    wechat_channel.send_message = AsyncMock()
    wechat_channel.send_image = AsyncMock()
    wechat_channel._last_wechat_user_id = "wxid_friend"
    wechat_channel._last_context_token = "tok-123"
    multimodal_client.app.state.wechat_channel = wechat_channel
    multimodal_client.app.state.wechat_conversation_id = conversation_id
    # 模型空回复（mock LLM 返回空 content → full_response=""）
    chat_model = multimodal_client.app.state.agent.llm_provider.chat_model
    chat_model.ainvoke = AsyncMock(return_value=AIMessage(content=""))

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "",
                "conversation_id": conversation_id,
                "attachments": [{"id": record["id"]}],
            }
        )
        frames = _collect_until_done(ws)
        # 转发发生在 done 帧之后的同一生成任务内；保持连接打开直到转发完成。
        for _ in range(100):
            if wechat_channel.send_image.await_count:
                break
            time.sleep(0.02)

    assert any(frame.get("done") for frame in frames)
    assert not any("error" in frame for frame in frames)

    # 空回复：文本同步跳过
    assert wechat_channel.send_message.await_count == 0
    # 但图片转发不依赖 full_response，仍然执行
    assert wechat_channel.send_image.await_count == 1
    forward_args = wechat_channel.send_image.await_args
    assert forward_args.args[0] == "wxid_friend"
    assert forward_args.args[1] == _png_bytes()
    assert forward_args.kwargs.get("context_token") == "tok-123"


def test_wechat_conversation_non_image_attachment_skipped_for_forward(
    multimodal_client, ws_repo, attachments_root, conversation_id
):
    """非图片 mime 的附件不进入微信转发（debug 跳过），文本回复照常同步。"""
    record = _seed_attachment(attachments_root, ws_repo, mime="application/pdf")
    wechat_channel = MagicMock()
    wechat_channel.send_message = AsyncMock()
    wechat_channel.send_image = AsyncMock()
    wechat_channel._last_wechat_user_id = "wxid_friend"
    wechat_channel._last_context_token = "tok-123"
    multimodal_client.app.state.wechat_channel = wechat_channel
    multimodal_client.app.state.wechat_conversation_id = conversation_id

    with multimodal_client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "message": "这是份文档",
                "conversation_id": conversation_id,
                "attachments": [{"id": record["id"]}],
            }
        )
        frames = _collect_until_done(ws)
        # 等待生成任务收尾（若有转发发生也在此窗口内出现）
        for _ in range(100):
            if wechat_channel.send_message.await_count:
                break
            time.sleep(0.02)

    assert any(frame.get("done") for frame in frames)
    assert not any("error" in frame for frame in frames)
    # 文本照常同步
    assert wechat_channel.send_message.await_count == 1
    # 非图片附件被显式跳过，send_image 不调用
    wechat_channel.send_image.assert_not_awaited()
