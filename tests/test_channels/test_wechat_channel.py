"""Tests for WeChat ClawBot channel."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
        weclaw_api_url="http://127.0.0.1:18011",
        weclaw_token="",
        webhook_secret="",
    )


@pytest.fixture
def wechat_config_with_token() -> WeChatChannelConfig:
    """WeChat config with auth token."""
    return WeChatChannelConfig(
        enabled=True,
        weclaw_api_url="http://127.0.0.1:18011",
        weclaw_token="test-token",
        webhook_secret="",
    )


@pytest.fixture
def wechat_config_with_secret() -> WeChatChannelConfig:
    """WeChat config with webhook secret."""
    return WeChatChannelConfig(
        enabled=True,
        weclaw_api_url="http://127.0.0.1:18011",
        weclaw_token="",
        webhook_secret="my-secret",
    )


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock ThumbelinaAgent."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")
    return agent


@pytest.fixture
def channel(wechat_config: WeChatChannelConfig, mock_agent: MagicMock) -> WeChatChannel:
    """Create a WeChatChannel instance (not started)."""
    return WeChatChannel(config=wechat_config, agent=mock_agent)


@pytest.fixture
def started_channel(
    wechat_config: WeChatChannelConfig, mock_agent: MagicMock
) -> WeChatChannel:
    """Create a WeChatChannel instance with a mocked httpx client."""
    ch = WeChatChannel(config=wechat_config, agent=mock_agent)
    ch._client = MagicMock(spec=httpx.AsyncClient)
    ch._client.post = AsyncMock()
    ch._client.get = AsyncMock()
    ch._client.aclose = AsyncMock()
    return ch


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
        assert ch._client is None

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
    async def test_start_creates_client(
        self, wechat_config: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config, agent=mock_agent)
        with patch("thumbelina.channels.wechat_channel.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            await ch.start()
            mock_cls.assert_called_once()
            assert ch._client is not None

    @pytest.mark.asyncio
    async def test_start_with_token_sets_header(
        self, wechat_config_with_token: WeChatChannelConfig, mock_agent: MagicMock
    ) -> None:
        ch = WeChatChannel(config=wechat_config_with_token, agent=mock_agent)
        with patch("thumbelina.channels.wechat_channel.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            await ch.start()
            call_kwargs = mock_cls.call_args
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_stop_closes_client(self, started_channel: WeChatChannel) -> None:
        mock_client = started_channel._client
        await started_channel.stop()
        mock_client.aclose.assert_awaited_once()
        assert started_channel._client is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, channel: WeChatChannel) -> None:
        """stop() should be a no-op when client is None."""
        await channel.stop()
        assert channel._client is None


# ------------------------------------------------------------------
# Sending tests
# ------------------------------------------------------------------


class TestWeChatChannelSend:
    """Test send_message calls WeClaw API correctly."""

    @pytest.mark.asyncio
    async def test_send_message_success(self, started_channel: WeChatChannel) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        started_channel._client.post = AsyncMock(return_value=mock_resp)

        result = await started_channel.send_message("wxid_user1", "Hello!")

        started_channel._client.post.assert_awaited_once_with(
            "/api/send",
            json={"to": "wxid_user1", "text": "Hello!"},
        )
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_send_message_retries_on_connect_error(
        self, started_channel: WeChatChannel
    ) -> None:
        started_channel._client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(httpx.ConnectError):
            await started_channel.send_message("wxid_user1", "Hello!")

        # Should have retried (default _MAX_RETRIES = 2)
        assert started_channel._client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_send_message_retries_on_timeout(
        self, started_channel: WeChatChannel
    ) -> None:
        started_channel._client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Timed out")
        )

        with pytest.raises(httpx.TimeoutException):
            await started_channel.send_message("wxid_user1", "Hello!")

        assert started_channel._client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_send_message_no_retry_on_http_error(
        self, started_channel: WeChatChannel
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_resp,
            )
        )
        started_channel._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await started_channel.send_message("wxid_user1", "Hello!")

        # HTTP errors are not retried (only ConnectError/TimeoutException)
        assert started_channel._client.post.await_count == 1


# ------------------------------------------------------------------
# Incoming message handling tests
# ------------------------------------------------------------------


class TestWeChatChannelIncoming:
    """Test handle_incoming message processing."""

    @pytest.mark.asyncio
    async def test_handle_text_message(
        self, started_channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        result = await started_channel.handle_incoming("wxid_user1", "Hello!")

        mock_agent.run.assert_awaited_once_with("Hello!")
        assert result == "Agent response"

    @pytest.mark.asyncio
    async def test_handle_voice_message(
        self, started_channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        result = await started_channel.handle_incoming(
            "wxid_user1", "transcribed text", msg_type="voice"
        )

        mock_agent.run.assert_not_awaited()
        assert "voice" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_image_message(
        self, started_channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        result = await started_channel.handle_incoming(
            "wxid_user1", "", msg_type="image"
        )

        mock_agent.run.assert_not_awaited()
        assert "image" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_agent_error(
        self, started_channel: WeChatChannel, mock_agent: MagicMock
    ) -> None:
        mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM failure"))

        result = await started_channel.handle_incoming("wxid_user1", "Hello!")

        assert "error" in result.lower()


# ------------------------------------------------------------------
# Status tests
# ------------------------------------------------------------------


class TestWeChatChannelStatus:
    """Test check_status endpoint."""

    @pytest.mark.asyncio
    async def test_status_connected(self, started_channel: WeChatChannel) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        started_channel._client.get = AsyncMock(return_value=mock_resp)

        status = await started_channel.check_status()

        assert status["connected"] is True

    @pytest.mark.asyncio
    async def test_status_connection_refused(
        self, started_channel: WeChatChannel
    ) -> None:
        started_channel._client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        status = await started_channel.check_status()

        assert status["connected"] is False
        assert "refused" in status["error"].lower()

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
            weclaw_api_url="http://127.0.0.1:18011",
            weclaw_token="",
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

    def test_incoming_webhook(
        self, client_with_channel: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_channel = client_with_channel

        resp = client.post(
            "/api/v1/wechat/incoming",
            json={"from": "wxid_user1", "text": "Hello!", "type": "text"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Agent says hi"
        mock_channel.handle_incoming.assert_awaited_once()

    def test_send_endpoint(
        self, client_with_channel: tuple[TestClient, MagicMock]
    ) -> None:
        client, mock_channel = client_with_channel

        resp = client.post(
            "/api/v1/wechat/send",
            json={"user_id": "wxid_user1", "text": "Hello!"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        mock_channel.send_message.assert_awaited_once()

    def test_status_endpoint(
        self, client_with_channel: tuple[TestClient, MagicMock]
    ) -> None:
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

    def test_incoming_voice_type(
        self, client_with_channel: tuple[TestClient, MagicMock]
    ) -> None:
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
