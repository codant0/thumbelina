"""Tests for WeChat channel — direct iLink integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thumbelina.channels.config import WeChatChannelConfig
from thumbelina.channels.wechat_channel import WeChatChannel

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
    """Create a mock ThumbelinaAgent with memory manager."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")
    agent.current_conversation_id = None

    # Mock memory manager with conversation support
    mm = MagicMock()
    mm.get_conversations = AsyncMock(return_value=[])
    mm.create_conversation = AsyncMock(return_value="conv-wechat-123")
    agent.memory_manager = mm

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
        """start() should load credentials from ~/.weclaw/accounts/ when bot_token is empty."""
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
            json.dumps({
                "bot_token": "saved-token-123",
                "ilink_bot_id": "bot@id",
                "baseurl": "https://ilinkai.weixin.qq.com",
                "ilink_user_id": "user@id",
            }),
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
    async def test_start_raises_when_no_token_and_no_saved_creds(
        self, mock_agent: MagicMock, tmp_path
    ) -> None:
        """start() should raise RuntimeError when no token and no saved credentials."""
        config = WeChatChannelConfig(
            enabled=True,
            bot_token="",
            ilink_bot_id="bot@id",
            ilink_user_id="user@id",
        )
        ch = WeChatChannel(config=config, agent=mock_agent)

        empty_dir = tmp_path / "empty_accounts"
        empty_dir.mkdir()

        with (
            patch("thumbelina.channels.wechat_qrcode._accounts_dir", return_value=empty_dir),
            pytest.raises(RuntimeError, match="no bot_token"),
        ):
            await ch.start()


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

        mock_agent.run.assert_awaited_once_with("Hello!")
        assert result == "Agent response"

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
        """All WeChat users share the same '微信聊天' conversation."""
        await channel.handle_incoming("wxid_user1", "Hello!")
        await channel.handle_incoming("wxid_user2", "Hi!")

        assert mock_agent.run.await_count == 2

    @pytest.mark.asyncio
    async def test_handle_voice_message(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        result = await channel.handle_incoming(
            "wxid_user1", "transcribed text", msg_type="voice"
        )

        mock_agent.run.assert_not_called()
        assert "voice" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_image_message(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        result = await channel.handle_incoming("wxid_user1", "", msg_type="image")

        mock_agent.run.assert_not_called()
        assert "image" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_agent_error(
        self, channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
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

        mock_agent.memory_manager.create_conversation.assert_awaited_once_with(
            name="微信聊天", pinned=True,
        )
        assert mock_agent.current_conversation_id == "conv-wechat-123"

    @pytest.mark.asyncio
    async def test_reuses_existing_conversation(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        mock_agent.memory_manager.get_conversations = AsyncMock(
            return_value=[{"id": "existing-conv", "name": "微信聊天"}]
        )

        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        await ch._ensure_wechat_conversation()

        mock_agent.memory_manager.create_conversation.assert_not_awaited()
        assert mock_agent.current_conversation_id == "existing-conv"

    @pytest.mark.asyncio
    async def test_no_memory_manager_skips(
        self, wechat_config: WeChatChannelConfig
    ) -> None:
        agent = MagicMock()
        agent.memory_manager = None
        agent.current_conversation_id = None

        ch = WeChatChannel(config=wechat_config, agent=agent)
        await ch._ensure_wechat_conversation()

        assert agent.current_conversation_id is None


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
        assert "stopped" in status["error"].lower()

    @pytest.mark.asyncio
    async def test_status_not_started(self, channel: WeChatChannel) -> None:
        status = await channel.check_status()

        assert status["connected"] is False
        assert "not started" in status["error"].lower()


# ------------------------------------------------------------------
# Webhook API endpoint tests
# ------------------------------------------------------------------


class TestWeChatWebhookEndpoints:
    """Test FastAPI webhook endpoints via TestClient."""

    @pytest.fixture
    def client_with_channel(self, mock_agent: MagicMock):
        """Create a TestClient with WeChat channel injected."""
        from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )

        mock_memory = MagicMock()
        mock_memory.close = MagicMock()
        mock_memory.repository = MagicMock()
        mock_memory.repository.ping = AsyncMock(return_value=True)

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
            patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
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
        from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )

        mock_memory = MagicMock()
        mock_memory.close = MagicMock()
        mock_memory.repository = MagicMock()
        mock_memory.repository.ping = AsyncMock(return_value=True)

        with (
            patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
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
        from thumbelina.config.models import AppConfig, LLMConfig, MemoryConfig

        config = AppConfig(
            llm=LLMConfig(provider="openai", model="test", api_key="test-key"),
            memory=MemoryConfig(database_url="sqlite:///:memory:"),
        )

        mock_memory = MagicMock()
        mock_memory.close = MagicMock()
        mock_memory.repository = MagicMock()
        mock_memory.repository.ping = AsyncMock(return_value=True)

        with (
            patch("thumbelina.api.app.MemoryManager", return_value=mock_memory),
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
