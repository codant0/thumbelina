"""Tests for WeChat channel — direct iLink integration."""

from __future__ import annotations

import asyncio
import base64
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.channels.config import WeChatChannelConfig
from thumbelina.channels.wechat_channel import WeChatChannel
from thumbelina.channels.wechat_qrcode import (
    ILinkSessionExpiredError,
    ILMessage,
    ILMessageItem,
)
from thumbelina.repository.repository import ConversationRepository

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def wechat_config() -> WeChatChannelConfig:
    """Default WeChat channel configuration for tests."""
    return WeChatChannelConfig(
        enabled=True,
        bot_token="test-token",
        ilink_bot_id="bot@id",
        ilink_user_id="user@id",
        ilink_base_url="https://ilinkai.weixin.qq.com",
        webhook_secret="",
    )


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock ThumbelinaAgent with repository manager."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")
    agent.current_conversation_id = None

    # Mock repository manager with conversation support
    mm = MagicMock()
    mm.get_conversations = AsyncMock(return_value=[])
    mm.create_conversation = AsyncMock(return_value="conv-wechat-123")
    mm.rename_conversation = AsyncMock(return_value=True)
    agent.repository_manager = mm

    return agent


@pytest.fixture
def channel(wechat_config: WeChatChannelConfig, mock_agent: MagicMock) -> WeChatChannel:
    """Create a WeChatChannel instance (not started)."""
    return WeChatChannel(config=wechat_config, agent=mock_agent)


# ------------------------------------------------------------------
# Initialization tests
# ------------------------------------------------------------------


class TestWeChatChannelInit:
    """Test channel initialization."""

    def test_channel_stores_config(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        assert ch._config is wechat_config
        assert ch._agent is mock_agent
        assert ch._ilink is None
        assert ch._poll_task is None

    @pytest.mark.asyncio
    async def test_channel_not_started_raises(self, channel: WeChatChannel) -> None:
        """send_message should raise RuntimeError before start()."""
        with pytest.raises(RuntimeError, match="not been started"):
            await channel.send_message("user1", "hello")


# ------------------------------------------------------------------
# Lifecycle tests
# ------------------------------------------------------------------


class TestWeChatChannelLifecycle:
    """Test start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_ilink_client(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        mock_ilink.close = AsyncMock()

        with patch(
            "thumbelina.channels.wechat_qrcode.ILinkClient",
            return_value=mock_ilink,
        ):
            with patch("asyncio.create_task") as mock_create_task:
                mock_task = MagicMock()
                mock_task.cancel = MagicMock()
                mock_task.__await__ = MagicMock(return_value=iter([]))
                mock_create_task.return_value = mock_task
                await ch.start()
                assert ch._ilink is mock_ilink
                mock_create_task.assert_called_once()
                # Should have set the conversation ID
                assert mock_agent.current_conversation_id == "conv-wechat-123"

    @pytest.mark.asyncio
    async def test_start_wires_shared_agent_attachments_root(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock, tmp_path
    ) -> None:
        """start() 把共享 agent 的 attachments_root 接线到与上传路由同源的
        附件根目录(设计 §3-W2);WS 克隆路径在 connect 时自行覆盖,互不影响。"""
        from types import SimpleNamespace

        runtime = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    config=SimpleNamespace(
                        repository=SimpleNamespace(attachments_directory=str(tmp_path))
                    )
                )
            )
        )
        ch = WeChatChannel(config=wechat_config, agent=mock_agent, runtime=runtime)
        mock_ilink = AsyncMock()
        mock_ilink.close = AsyncMock()

        with (
            patch("thumbelina.channels.wechat_qrcode.ILinkClient", return_value=mock_ilink),
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_task.__await__ = MagicMock(return_value=iter([]))
            mock_create_task.return_value = mock_task
            await ch.start()

        assert mock_agent.attachments_root == tmp_path

    @pytest.mark.asyncio
    async def test_start_without_runtime_falls_back_to_default_root(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        """runtime 缺失(单测 fixture)时不抛错,回退默认附件目录。"""
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        mock_ilink.close = AsyncMock()

        with (
            patch("thumbelina.channels.wechat_qrcode.ILinkClient", return_value=mock_ilink),
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_task.__await__ = MagicMock(return_value=iter([]))
            mock_create_task.return_value = mock_task
            await ch.start()

        assert mock_agent.attachments_root is not None

    @pytest.mark.asyncio
    async def test_stop_cancels_poll_and_closes_client(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        mock_ilink.close = AsyncMock()
        ch._ilink = mock_ilink

        # Create a real asyncio task that we can cancel
        async def long_running():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        ch._poll_task = task

        await ch.stop()

        assert task.cancelled()
        mock_ilink.close.assert_awaited_once()
        assert ch._ilink is None
        assert ch._poll_task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, channel: WeChatChannel) -> None:
        """stop() should be a no-op when not started."""
        await channel.stop()
        assert channel._ilink is None

    @pytest.mark.asyncio
    async def test_start_loads_saved_credentials_when_token_empty(
        self, mock_agent: MagicMock, tmp_path
    ) -> None:
        """start() should load credentials from the accounts dir when bot_token is empty."""
        import json

        config = WeChatChannelConfig(
            enabled=True,
            bot_token="",
            ilink_bot_id="bot@id",
            ilink_user_id="user@id",
            ilink_base_url="https://ilinkai.weixin.qq.com",
        )
        ch = WeChatChannel(config=config, agent=mock_agent)

        # Create a fake credentials file
        accounts_dir = tmp_path / ".weclaw" / "accounts"
        accounts_dir.mkdir(parents=True)
        cred_file = accounts_dir / "bot-id.json"
        cred_file.write_text(
            json.dumps(
                {
                    "bot_token": "saved-token-123",
                    "ilink_bot_id": "bot@id",
                    "baseurl": "https://ilinkai.weixin.qq.com",
                    "ilink_user_id": "user@id",
                }
            ),
            encoding="utf-8",
        )

        mock_ilink = AsyncMock()
        mock_ilink.close = AsyncMock()

        with (
            patch("thumbelina.channels.wechat_qrcode._accounts_dir", return_value=accounts_dir),
            patch(
                "thumbelina.channels.wechat_qrcode.ILinkClient",
                return_value=mock_ilink,
            ),
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_task.__await__ = MagicMock(return_value=iter([]))
            mock_create_task.return_value = mock_task
            await ch.start()
            assert config.bot_token == "saved-token-123"
            assert ch._ilink is mock_ilink

    @pytest.mark.asyncio
    async def test_start_auto_discovers_credentials_when_bot_id_unknown(
        self, mock_agent: MagicMock, tmp_path
    ) -> None:
        """start() should auto-discover saved credentials even when ilink_bot_id
        is unknown (container rebuild lost the config/database but kept the
        credentials volume)."""
        import json

        config = WeChatChannelConfig(
            enabled=True,
            bot_token="",
            ilink_bot_id="",
            ilink_user_id="",
            ilink_base_url="https://ilinkai.weixin.qq.com",
            accounts_dir=str(tmp_path),
        )
        ch = WeChatChannel(config=config, agent=mock_agent)

        # Single credentials file in the accounts dir
        accounts_dir = tmp_path
        cred_file = accounts_dir / "bot-id.json"
        cred_file.write_text(
            json.dumps(
                {
                    "bot_token": "discovered-token",
                    "ilink_bot_id": "bot@discovered",
                    "baseurl": "https://ilinkai.weixin.qq.com",
                    "ilink_user_id": "user@discovered",
                }
            ),
            encoding="utf-8",
        )

        mock_ilink = AsyncMock()
        mock_ilink.close = AsyncMock()

        with (
            patch(
                "thumbelina.channels.wechat_qrcode.ILinkClient",
                return_value=mock_ilink,
            ),
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_task.__await__ = MagicMock(return_value=iter([]))
            mock_create_task.return_value = mock_task
            await ch.start()
            assert config.bot_token == "discovered-token"
            assert config.ilink_bot_id == "bot@discovered"
            assert config.ilink_user_id == "user@discovered"
            assert ch._ilink is mock_ilink
            assert ch._needs_authentication is False

    @pytest.mark.asyncio
    async def test_start_does_not_pick_wrong_account_when_bot_id_known(
        self, mock_agent: MagicMock, tmp_path
    ) -> None:
        """When ilink_bot_id is known, an exact-match file is required —
        a mismatched file must NOT be auto-loaded."""
        import json

        config = WeChatChannelConfig(
            enabled=True,
            bot_token="",
            ilink_bot_id="expected@bot",
            ilink_user_id="",
            ilink_base_url="https://ilinkai.weixin.qq.com",
            accounts_dir=str(tmp_path),
        )
        ch = WeChatChannel(config=config, agent=mock_agent)

        # Only a credentials file for a DIFFERENT bot exists
        cred_file = tmp_path / "other-bot.json"
        cred_file.write_text(
            json.dumps(
                {
                    "bot_token": "other-token",
                    "ilink_bot_id": "other@bot",
                    "baseurl": "https://ilinkai.weixin.qq.com",
                    "ilink_user_id": "other@user",
                }
            ),
            encoding="utf-8",
        )

        await ch.start()

        assert ch._needs_authentication is True
        assert ch._ilink is None
        assert config.bot_token == ""

    @pytest.mark.asyncio
    async def test_start_marks_needs_auth_when_no_token_and_no_saved_creds(
        self, mock_agent: MagicMock, tmp_path
    ) -> None:
        """start() should mark channel as needing auth when no token and no saved credentials."""
        config = WeChatChannelConfig(
            enabled=True,
            bot_token="",
            ilink_bot_id="bot@id",
            ilink_user_id="user@id",
        )
        ch = WeChatChannel(config=config, agent=mock_agent)

        empty_dir = tmp_path / "empty_accounts"
        empty_dir.mkdir()

        with patch("thumbelina.channels.wechat_qrcode._accounts_dir", return_value=empty_dir):
            await ch.start()

        assert ch._needs_authentication is True
        assert ch._ilink is None
        assert ch._poll_task is None
        status = await ch.check_status()
        assert status["needs_authentication"] is True
        assert status["connected"] is False


# ------------------------------------------------------------------
# Sending tests
# ------------------------------------------------------------------


class TestWeChatChannelSend:
    """Test send_message delegates to ILinkClient."""

    @pytest.mark.asyncio
    async def test_send_message_success(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        mock_ilink.send_message = AsyncMock(return_value={"status": "ok"})
        ch._ilink = mock_ilink

        # With context_token
        result = await ch.send_message("wxid_user1", "Hello!", context_token="ctx-123")
        mock_ilink.send_message.assert_awaited_once_with("wxid_user1", "Hello!", "ctx-123")
        assert result == {"status": "ok"}

        # Without context_token (uses empty string default)
        mock_ilink.send_message.reset_mock()
        result = await ch.send_message("wxid_user1", "Hello!")
        mock_ilink.send_message.assert_awaited_once_with("wxid_user1", "Hello!", "")


class TestWeChatChannelSendImage:
    """send_image 薄封装:委托 ILinkClient.send_image(设计 §2 出站转发)。"""

    @pytest.mark.asyncio
    async def test_send_image_delegates_to_ilink(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        ch._ilink = mock_ilink

        await ch.send_image("wxid_user1", b"png-bytes", context_token="ctx-123")

        mock_ilink.send_image.assert_awaited_once_with("wxid_user1", b"png-bytes", "ctx-123")

    @pytest.mark.asyncio
    async def test_send_image_falls_back_to_last_context_token(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        ch._ilink = mock_ilink
        ch._last_context_token = "tok-last"

        await ch.send_image("wxid_user1", b"png-bytes")

        mock_ilink.send_image.assert_awaited_once_with("wxid_user1", b"png-bytes", "tok-last")

    @pytest.mark.asyncio
    async def test_send_image_not_started_raises(self, channel: WeChatChannel) -> None:
        with pytest.raises(RuntimeError, match="not been started"):
            await channel.send_image("wxid_user1", b"png-bytes")


class TestWeChatChannelLastUser:
    """last_user_id exposes the most recent WeChat user for the notify tool."""

    def test_last_user_id_defaults_to_none(self, channel: WeChatChannel) -> None:
        assert channel.last_user_id is None

    def test_last_user_id_reflects_last_wechat_user(self, channel: WeChatChannel) -> None:
        channel._last_wechat_user_id = "wxid_user1"
        assert channel.last_user_id == "wxid_user1"

    @pytest.mark.asyncio
    async def test_process_message_records_last_user(self, channel: WeChatChannel) -> None:
        msg = MagicMock()
        msg.message_type = 1
        msg.message_state = 2
        msg.message_id = "m-1"
        msg.from_user_id = "wxid_sender"
        msg.context_token = "ctx-1"

        with patch("thumbelina.channels.wechat_qrcode.extract_text", return_value="hi"):
            await channel._process_message(msg)

        assert channel.last_user_id == "wxid_sender"


# ------------------------------------------------------------------
# Incoming message handling tests
# ------------------------------------------------------------------


class TestWeChatChannelIncoming:
    """Test handle_incoming message processing."""

    @pytest.mark.asyncio
    async def test_handle_text_message_calls_agent(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        result = await channel.handle_incoming("wxid_user1", "Hello!")

        mock_agent.run.assert_awaited_once_with("Hello!", attachments=None)
        assert result == "Agent response"

    @pytest.mark.asyncio
    async def test_handle_message_passes_context_window_tokens(self, mock_agent):
        """微信消息路径应像 HTTP/WebSocket 一样解析并传入上下文窗口（#8）。"""
        from types import SimpleNamespace

        endpoint_manager = MagicMock()
        endpoint_manager.get_active_endpoint_model = AsyncMock(return_value=None)
        state = SimpleNamespace(
            endpoint_manager=endpoint_manager,
            config=SimpleNamespace(llm=SimpleNamespace(context_window_tokens=64_000)),
        )
        runtime = SimpleNamespace(app=SimpleNamespace(state=state))

        mock_agent.current_conversation_id = "conv-wechat-123"
        mock_agent.repository_manager.get_conversation = AsyncMock(
            return_value={"id": "conv-wechat-123", "endpoint_id": None}
        )
        ch = WeChatChannel(
            config=WeChatChannelConfig(
                enabled=True,
                bot_token="test-token",
                ilink_bot_id="bot@id",
                ilink_user_id="user@id",
                ilink_base_url="https://ilinkai.weixin.qq.com",
            ),
            agent=mock_agent,
            runtime=runtime,
        )

        await ch.handle_incoming("wxid_user1", "Hello!")

        mock_agent.run.assert_awaited_once_with(
            "Hello!", context_window_tokens=64_000, attachments=None
        )

    @pytest.mark.asyncio
    async def test_handle_multiple_messages_calls_agent_each_time(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        await channel.handle_incoming("wxid_user1", "Hello!")
        await channel.handle_incoming("wxid_user1", "World!")

        assert mock_agent.run.await_count == 2

    @pytest.mark.asyncio
    async def test_handle_different_users_shares_same_agent(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        """All WeChat users share the same '微信Clawbot' conversation."""
        await channel.handle_incoming("wxid_user1", "Hello!")
        await channel.handle_incoming("wxid_user2", "Hi!")

        assert mock_agent.run.await_count == 2

    @pytest.mark.asyncio
    async def test_handle_voice_message(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        """非 text stub 已移除(设计 §3-W2):带转写文本的 voice 照常进入 agent。"""
        result = await channel.handle_incoming("wxid_user1", "transcribed text", msg_type="voice")

        mock_agent.run.assert_awaited_once_with("transcribed text", attachments=None)
        assert result == "Agent response"

    @pytest.mark.asyncio
    async def test_handle_image_message_without_refs_skips(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        """空文本 + 无附件 refs → 跳过整轮(无内容可生成),不调用 agent。"""
        result = await channel.handle_incoming("wxid_user1", "", msg_type="image")

        mock_agent.run.assert_not_called()
        assert result == ""

    @pytest.mark.asyncio
    async def test_handle_empty_text_with_refs_runs_pure_image_turn(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        """空文本 + 有图 refs(设计 §2)→ 纯图片轮照常进入 agent。"""
        refs = [{"id": "att-1", "mime": "image/jpeg", "width": 100, "height": 80}]

        result = await channel.handle_incoming("wxid_user1", "", msg_type="image", attachments=refs)

        mock_agent.run.assert_awaited_once_with("", attachments=refs)
        assert result == "Agent response"

    @pytest.mark.asyncio
    async def test_broadcast_includes_attachments_for_inbound_images(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        """channel_message 广播帧(设计 §2):入站图片 refs 随回调第 5 参透传。"""
        callback = AsyncMock()
        ch = WeChatChannel(config=wechat_config, agent=mock_agent, on_message_callback=callback)
        refs = [{"id": "att-1", "mime": "image/png"}]

        await ch.handle_incoming("wxid_user1", "看图", attachments=refs)

        callback.assert_awaited_once_with("", "看图", "Agent response", "wechat", refs)

    @pytest.mark.asyncio
    async def test_broadcast_text_only_has_none_attachments(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        callback = AsyncMock()
        ch = WeChatChannel(config=wechat_config, agent=mock_agent, on_message_callback=callback)

        await ch.handle_incoming("wxid_user1", "纯文本")

        callback.assert_awaited_once_with("", "纯文本", "Agent response", "wechat", None)

    @pytest.mark.asyncio
    async def test_handle_agent_error(self, channel: WeChatChannel, mock_agent: MagicMock) -> None:
        mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM failure"))

        result = await channel.handle_incoming("wxid_user1", "Hello!")

        assert "error" in result.lower()


class TestWeChatConversationSetup:
    """Test _ensure_wechat_conversation logic."""

    @pytest.mark.asyncio
    async def test_creates_new_conversation_when_none_exists(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        await ch._ensure_wechat_conversation()

        mock_agent.repository_manager.create_conversation.assert_awaited_once_with(
            name="微信Clawbot",
            pinned=True,
        )
        assert mock_agent.current_conversation_id == "conv-wechat-123"

    @pytest.mark.asyncio
    async def test_reuses_existing_conversation(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        mock_agent.repository_manager.get_conversations = AsyncMock(
            return_value=[{"id": "existing-conv", "name": "微信Clawbot"}]
        )

        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        await ch._ensure_wechat_conversation()

        mock_agent.repository_manager.create_conversation.assert_not_awaited()
        assert mock_agent.current_conversation_id == "existing-conv"

    @pytest.mark.asyncio
    async def test_no_repository_manager_skips(self, wechat_config: WeChatChannelConfig) -> None:
        agent = MagicMock()
        agent.repository_manager = None
        agent.current_conversation_id = None

        ch = WeChatChannel(config=wechat_config, agent=agent)
        await ch._ensure_wechat_conversation()

        assert agent.current_conversation_id is None

    @pytest.mark.asyncio
    async def test_migrates_legacy_named_conversation(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        mock_agent.repository_manager.get_conversations = AsyncMock(
            return_value=[{"id": "legacy-conv", "name": "微信聊天"}]
        )

        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        await ch._ensure_wechat_conversation()

        mock_agent.repository_manager.rename_conversation.assert_awaited_once_with(
            "legacy-conv", "微信Clawbot"
        )
        mock_agent.repository_manager.create_conversation.assert_not_awaited()
        assert mock_agent.current_conversation_id == "legacy-conv"


# ------------------------------------------------------------------
# Status tests
# ------------------------------------------------------------------


class TestWeChatChannelStatus:
    """Test check_status endpoint."""

    @pytest.mark.asyncio
    async def test_status_connected(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_task = MagicMock()
        mock_task.done.return_value = False
        ch._poll_task = mock_task

        status = await ch.check_status()

        assert status["connected"] is True
        assert status["needs_authentication"] is False

    @pytest.mark.asyncio
    async def test_status_poll_loop_stopped(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.exception.return_value = None
        ch._poll_task = mock_task

        status = await ch.check_status()

        assert status["connected"] is False
        assert status["needs_authentication"] is False
        assert "stopped" in status["error"].lower()

    @pytest.mark.asyncio
    async def test_status_not_started(self, channel: WeChatChannel) -> None:
        status = await channel.check_status()

        assert status["connected"] is False
        assert status["needs_authentication"] is False
        assert "not started" in status["error"].lower()

    @pytest.mark.asyncio
    async def test_status_needs_authentication(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        ch._needs_authentication = True

        status = await ch.check_status()

        assert status["connected"] is False
        assert status["needs_authentication"] is True
        assert "qr code" in status["error"].lower()


# ------------------------------------------------------------------
# Poll loop tests
# ------------------------------------------------------------------


class TestWeChatChannelPollLoop:
    """Test the iLink long-polling loop."""

    @pytest.mark.asyncio
    async def test_poll_loop_stops_on_session_expired(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        """The poll loop should stop and mark needs_authentication on errcode=-14."""
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        mock_ilink = AsyncMock()
        mock_ilink.getupdates = AsyncMock(side_effect=ILinkSessionExpiredError("expired"))
        mock_ilink.close = AsyncMock()
        ch._ilink = mock_ilink

        # Run the loop briefly; it should exit after the first auth failure.
        task = asyncio.create_task(ch._poll_loop())
        await asyncio.wait_for(task, timeout=1.0)

        assert ch._needs_authentication is True
        assert ch._poll_task is None  # stop() is not called, task simply finished
        mock_ilink.getupdates.assert_awaited_once()


# ------------------------------------------------------------------
# Inbound image pipeline (设计 §2 / §3-W3)
# ------------------------------------------------------------------


def _png_bytes(width: int = 4, height: int = 3) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)


def _mock_llm_provider() -> MagicMock:
    provider = MagicMock()
    provider.chat_model = MagicMock()
    provider.chat_model.ainvoke = AsyncMock(return_value=AIMessage(content="Agent response"))
    provider.chat_model.bind_tools.return_value = provider.chat_model
    return provider


def _image_message() -> ILMessage:
    """One image item with eqp + bare-hex key (W1 parsed fields)."""
    return ILMessage(
        message_id=101,
        from_user_id="wxid_sender",
        to_user_id="bot@id",
        message_type=1,
        message_state=2,
        context_token="ctx-img-1",
        items=[
            ILMessageItem(
                type=2,
                image_media_eqp="eqp-token",
                image_aeskey_hex="ab" * 16,
                image_width=640,
                image_height=480,
            )
        ],
    )


class TestWeChatInboundImages:
    """微信入站图片全链路:download_media → 落盘入库 → refs 持久化 → 图像块进模型。"""

    @pytest.fixture
    def repo(self) -> ConversationRepository:
        return ConversationRepository("sqlite:///:memory:")

    @pytest.fixture
    async def conversation_id(self, repo: ConversationRepository) -> str:
        return await repo.create_conversation()

    @pytest.fixture
    def real_agent(self, repo: ConversationRepository, tmp_path) -> ThumbelinaAgent:
        agent = ThumbelinaAgent(llm_provider=_mock_llm_provider(), repository_manager=repo)
        agent.attachments_root = tmp_path / "attachments"
        return agent

    @pytest.fixture
    def channel(
        self, wechat_config: WeChatChannelConfig, real_agent: ThumbelinaAgent
    ) -> WeChatChannel:
        ch = WeChatChannel(config=wechat_config, agent=real_agent)
        ch._ilink = AsyncMock()
        return ch

    @pytest.mark.asyncio
    async def test_process_message_image_full_pipeline(
        self,
        channel: WeChatChannel,
        real_agent: ThumbelinaAgent,
        repo: ConversationRepository,
        conversation_id: str,
        tmp_path,
    ) -> None:
        """mock download_media 返回真实 PNG → Attachment 行 + 落盘文件 +
        user 消息带 refs 持久化 + LLM 收到图像块 + 回复照常发出。"""
        png = _png_bytes()
        ilink = channel._ilink
        ilink.download_media = AsyncMock(return_value=png)
        real_agent.current_conversation_id = conversation_id

        await channel._process_message(_image_message())

        # 1) 附件行已入库,字节已落盘(yyyy/mm/<uuid>.png)
        messages = await repo.get_messages(conversation_id)
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 1
        refs = user_messages[0]["attachments"]
        assert refs is not None and len(refs) == 1
        ref = refs[0]
        assert ref["mime"] == "image/png"
        assert ref["width"] == 640
        assert ref["height"] == 480

        record = await repo.get_attachment(ref["id"])
        assert record is not None
        assert record["relative_path"].count("/") == 2  # yyyy/mm/<uuid>.png
        assert (real_agent.attachments_root / record["relative_path"]).read_bytes() == png

        # 2) LLM 收到最后一条 HumanMessage = 纯图像块(纯图片轮,无文本块)
        chat_model = real_agent.llm_provider.chat_model
        assert chat_model.ainvoke.called
        human = chat_model.ainvoke.call_args[0][0][-1]
        assert isinstance(human, HumanMessage)
        assert isinstance(human.content, list)
        assert human.content
        assert all(isinstance(b, dict) and b.get("type") == "image" for b in human.content)
        image_block = human.content[0]
        assert image_block["mime_type"] == "image/png"
        assert image_block["base64"] == base64.b64encode(png).decode("ascii")

        # 3) 回复文本照常经 send_message 发回(携带入站 context_token)
        ilink.send_message.assert_awaited_once()
        send_args = ilink.send_message.await_args
        assert send_args.args[0] == "wxid_sender"
        assert send_args.args[1] == "Agent response"
        assert send_args.args[2] == "ctx-img-1"

    @pytest.mark.asyncio
    async def test_process_message_download_failure_degrades_to_placeholder(
        self, channel: WeChatChannel
    ) -> None:
        """单张图片下载失败 → 占位文本替代该图进入本轮,轮次不中断。"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="Agent response")
        mock_agent.current_conversation_id = None
        mock_agent.attachments_root = None
        mock_agent.repository_manager = MagicMock()
        channel._agent = mock_agent
        channel._ilink.download_media = AsyncMock(side_effect=RuntimeError("CDN down"))

        await channel._process_message(_image_message())

        # agent.run 收到占位文本而非中断;纯下载失败无 refs
        run_args = mock_agent.run.await_args
        assert "[image message received" in run_args.args[0]
        assert run_args.kwargs.get("attachments") is None
        # 回复照常发出
        channel._ilink.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_message_no_text_no_images_skips(self, channel: WeChatChannel) -> None:
        """无文本且无图片项 → 整轮跳过,不调 agent 也不回复。"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="Agent response")
        channel._agent = mock_agent

        msg = ILMessage(
            message_id=102,
            from_user_id="wxid_sender",
            to_user_id="bot@id",
            message_type=1,
            message_state=2,
            context_token="ctx-2",
            items=[],
        )
        await channel._process_message(msg)

        mock_agent.run.assert_not_called()
        channel._ilink.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_message_text_and_image_combined(
        self,
        channel: WeChatChannel,
        real_agent: ThumbelinaAgent,
        repo: ConversationRepository,
        conversation_id: str,
    ) -> None:
        """图文混合消息:文本与图像 refs 同轮持久化,LLM 收到文本块+图像块。"""
        png = _png_bytes(8, 5)
        channel._ilink.download_media = AsyncMock(return_value=png)
        real_agent.current_conversation_id = conversation_id

        msg = _image_message()
        msg.items.insert(0, ILMessageItem(type=1, text="这是什么"))
        await channel._process_message(msg)

        messages = await repo.get_messages(conversation_id)
        user_messages = [m for m in messages if m["role"] == "user"]
        assert user_messages[0]["content"] == "这是什么"
        refs = user_messages[0]["attachments"]
        assert refs is not None and len(refs) == 1

        human = real_agent.llm_provider.chat_model.ainvoke.call_args[0][0][-1]
        text_blocks = [b for b in human.content if isinstance(b, dict) and b.get("type") == "text"]
        image_blocks = [
            b for b in human.content if isinstance(b, dict) and b.get("type") == "image"
        ]
        assert text_blocks and text_blocks[0]["text"] == "这是什么"
        assert len(image_blocks) == 1


# ------------------------------------------------------------------
# Webhook API endpoint tests
# ------------------------------------------------------------------


class TestWeChatWebhookEndpoints:
    """Test FastAPI webhook endpoints via TestClient."""

    @pytest.fixture
    def client_with_channel(self, mock_agent: MagicMock):
        """Create a TestClient with WeChat channel injected."""
        from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        )

        mock_repository = MagicMock()
        mock_repository.close = MagicMock()
        mock_repository.conversation_repository = MagicMock()
        mock_repository.conversation_repository.ping = AsyncMock(return_value=True)

        mock_channel = MagicMock(spec=WeChatChannel)
        mock_channel.handle_incoming = AsyncMock(return_value="Agent says hi")
        mock_channel.send_message = AsyncMock(return_value={"status": "ok"})
        mock_channel.check_status = AsyncMock(return_value={"connected": True})
        mock_channel._config = WeChatChannelConfig(
            enabled=True,
            bot_token="tok",
            ilink_bot_id="bot@id",
            ilink_user_id="user@id",
            webhook_secret="",
        )

        with (
            patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
            patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
            patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
        ):
            from thumbelina.api.app import create_app

            app = create_app(config)
            app.state.wechat_channel = mock_channel
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, mock_channel

    def test_incoming_webhook(self, client_with_channel: tuple[TestClient, MagicMock]) -> None:
        client, mock_channel = client_with_channel

        resp = client.post(
            "/api/v1/wechat/incoming",
            json={"from": "wxid_user1", "text": "Hello!", "type": "text"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Agent says hi"
        mock_channel.handle_incoming.assert_awaited_once()

    def test_send_endpoint(self, client_with_channel: tuple[TestClient, MagicMock]) -> None:
        client, mock_channel = client_with_channel

        resp = client.post(
            "/api/v1/wechat/send",
            json={"user_id": "wxid_user1", "text": "Hello!"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        mock_channel.send_message.assert_awaited_once()

    def test_status_endpoint(self, client_with_channel: tuple[TestClient, MagicMock]) -> None:
        client, mock_channel = client_with_channel

        resp = client.get("/api/v1/wechat/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True

    def test_incoming_when_channel_not_initialized(self, mock_agent: MagicMock):
        """404 when wechat_channel is not on app.state."""
        from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        )

        mock_repository = MagicMock()
        mock_repository.close = MagicMock()
        mock_repository.conversation_repository = MagicMock()
        mock_repository.conversation_repository.ping = AsyncMock(return_value=True)

        with (
            patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
            patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
            patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
        ):
            from thumbelina.api.app import create_app

            app = create_app(config)
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/wechat/incoming",
                    json={"from": "wxid_user1", "text": "Hello!", "type": "text"},
                )
                assert resp.status_code == 404

    def test_incoming_voice_type(self, client_with_channel: tuple[TestClient, MagicMock]) -> None:
        client, mock_channel = client_with_channel

        resp = client.post(
            "/api/v1/wechat/incoming",
            json={"from": "wxid_user1", "text": "transcribed", "type": "voice"},
        )

        assert resp.status_code == 200
        mock_channel.handle_incoming.assert_awaited_once_with(
            user_id="wxid_user1", text="transcribed", msg_type="voice"
        )

    def test_send_when_channel_not_initialized(self, mock_agent: MagicMock):
        """404 when wechat_channel is not on app.state."""
        from thumbelina.config.models import AppConfig, LLMConfig, RepositoryConfig

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            repository=RepositoryConfig(database_url="sqlite:///:memory:"),
        )

        mock_repository = MagicMock()
        mock_repository.close = MagicMock()
        mock_repository.conversation_repository = MagicMock()
        mock_repository.conversation_repository.ping = AsyncMock(return_value=True)

        with (
            patch("thumbelina.api.app.RepositoryManager", return_value=mock_repository),
            patch("thumbelina.api.app.create_provider", return_value=MagicMock()),
            patch("thumbelina.api.app.ThumbelinaAgent", return_value=mock_agent),
        ):
            from thumbelina.api.app import create_app

            app = create_app(config)
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/wechat/send",
                    json={"user_id": "wxid_user1", "text": "Hello!"},
                )
                assert resp.status_code == 404
