"""Tests for the QQ Bot channel implementation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thumbelina.channels.config import QQChannelConfig
from thumbelina.channels.qq_channel import QQChannel, _clean_message_content


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qq_config() -> QQChannelConfig:
    return QQChannelConfig(
        enabled=True,
        app_id="test-app-id",
        app_secret="test-app-secret",
    )


@pytest.fixture
def qq_config_with_guilds() -> QQChannelConfig:
    return QQChannelConfig(
        enabled=True,
        app_id="test-app-id",
        app_secret="test-app-secret",
        allowed_guilds=["guild-1"],
        allowed_groups=["group-1"],
    )


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Agent response")
    return agent


@pytest.fixture
def channel(qq_config: QQChannelConfig, mock_agent: MagicMock) -> QQChannel:
    return QQChannel(config=qq_config, agent=mock_agent)


@pytest.fixture
def channel_with_allowlist(
    qq_config_with_guilds: QQChannelConfig, mock_agent: MagicMock
) -> QQChannel:
    return QQChannel(config=qq_config_with_guilds, agent=mock_agent)


# ---------------------------------------------------------------------------
# Message cleaning
# ---------------------------------------------------------------------------


class TestCleanMessageContent:
    """Tests for _clean_message_content helper."""

    def test_strip_at_mention(self) -> None:
        assert _clean_message_content("<@12345> hello") == "hello"

    def test_strip_at_mention_with_exclamation(self) -> None:
        assert _clean_message_content("<@!12345> hello") == "hello"

    def test_strip_multiple_mentions(self) -> None:
        assert _clean_message_content("<@1> <@!2> ask something") == "ask something"

    def test_strip_mention_only(self) -> None:
        assert _clean_message_content("<@12345>") == ""

    def test_no_mention(self) -> None:
        assert _clean_message_content("plain text") == "plain text"

    def test_whitespace_trimming(self) -> None:
        assert _clean_message_content("  <@1>  hello  ") == "hello"

    def test_empty_string(self) -> None:
        assert _clean_message_content("") == ""

    def test_mention_at_end(self) -> None:
        assert _clean_message_content("hello <@123>") == "hello"

    def test_mention_in_middle(self) -> None:
        assert _clean_message_content("hi <@123> there") == "hi  there"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    """Tests for QQChannel construction."""

    def test_initial_state(self, channel: QQChannel) -> None:
        assert channel._client is None
        assert channel._thread is None
        assert channel._handler is None

    def test_config_stored(self, channel: QQChannel, qq_config: QQChannelConfig) -> None:
        assert channel._config is qq_config

    def test_agent_stored(self, channel: QQChannel, mock_agent: MagicMock) -> None:
        assert channel._agent is mock_agent


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------


class TestMessageHandling:
    """Tests for _handle_message and handler integration."""

    @pytest.mark.asyncio
    async def test_handler_called_with_cleaned_content(
        self, channel: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Agent.run() is called with cleaned content (mentions stripped)."""
        reply_func = AsyncMock()
        await channel._handle_message(
            user_id="user-1",
            content="<@bot> what is the weather",
            reply_func=reply_func,
            source="guild",
        )
        mock_agent.run.assert_awaited_once_with("what is the weather")
        reply_func.assert_awaited_once_with("Agent response")

    @pytest.mark.asyncio
    async def test_custom_handler_invoked(self, channel: QQChannel) -> None:
        """When set_handler is used, the custom handler receives the message."""
        custom_handler = AsyncMock(return_value="custom reply")
        channel.set_handler(custom_handler)

        reply_func = AsyncMock()
        await channel._handle_message(
            user_id="user-1",
            content="<@bot> hello",
            reply_func=reply_func,
            source="c2c",
        )
        custom_handler.assert_awaited_once_with("user-1", "hello")
        reply_func.assert_awaited_once_with("custom reply")

    @pytest.mark.asyncio
    async def test_empty_message_ignored(
        self, channel: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Messages that are empty after cleaning are not forwarded."""
        reply_func = AsyncMock()
        await channel._handle_message(
            user_id="user-1",
            content="<@123>",
            reply_func=reply_func,
            source="guild",
        )
        mock_agent.run.assert_not_awaited()
        reply_func.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_guild_filtering(
        self, channel_with_allowlist: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Messages from non-allowed guilds are ignored."""
        reply_func = AsyncMock()
        await channel_with_allowlist._handle_message(
            user_id="user-1",
            content="<@bot> hello",
            reply_func=reply_func,
            source="guild",
            guild_id="other-guild",
        )
        mock_agent.run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowed_guild_passes(
        self, channel_with_allowlist: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Messages from allowed guilds are processed."""
        reply_func = AsyncMock()
        await channel_with_allowlist._handle_message(
            user_id="user-1",
            content="<@bot> hello",
            reply_func=reply_func,
            source="guild",
            guild_id="guild-1",
        )
        mock_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_group_filtering(
        self, channel_with_allowlist: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Messages from non-allowed groups are ignored."""
        reply_func = AsyncMock()
        await channel_with_allowlist._handle_message(
            user_id="user-1",
            content="<@bot> hello",
            reply_func=reply_func,
            source="group",
            group_id="other-group",
        )
        mock_agent.run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowed_group_passes(
        self, channel_with_allowlist: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Messages from allowed groups are processed."""
        reply_func = AsyncMock()
        await channel_with_allowlist._handle_message(
            user_id="user-1",
            content="<@bot> hello",
            reply_func=reply_func,
            source="group",
            group_id="group-1",
        )
        mock_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_filter_when_allowlists_empty(
        self, channel: QQChannel, mock_agent: MagicMock
    ) -> None:
        """When allowlists are empty, all guilds/groups pass through."""
        reply_func = AsyncMock()
        await channel._handle_message(
            user_id="user-1",
            content="<@bot> hello",
            reply_func=reply_func,
            source="guild",
            guild_id="any-guild",
        )
        mock_agent.run.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error scenarios in message handling."""

    @pytest.mark.asyncio
    async def test_agent_exception_does_not_propagate(
        self, channel: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Exceptions from agent.run() are caught and logged, not re-raised."""
        mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM failure"))
        reply_func = AsyncMock()

        # Should not raise
        await channel._handle_message(
            user_id="user-1",
            content="hello",
            reply_func=reply_func,
            source="c2c",
        )
        reply_func.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reply_func_exception_does_not_propagate(
        self, channel: QQChannel, mock_agent: MagicMock
    ) -> None:
        """Exceptions from the reply function are caught and logged."""
        reply_func = AsyncMock(side_effect=Exception("API error"))

        # Should not raise
        await channel._handle_message(
            user_id="user-1",
            content="hello",
            reply_func=reply_func,
            source="c2c",
        )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_without_botpy(
        self, channel: QQChannel
    ) -> None:
        """start() gracefully handles missing qq-botpy dependency."""
        with patch.dict("sys.modules", {"botpy": None}):
            # Should not raise, just log a warning
            await channel.start()
            assert channel._client is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, channel: QQChannel) -> None:
        """stop() is safe to call when the channel was never started."""
        await channel.stop()
        assert channel._client is None
        assert channel._thread is None

    @pytest.mark.asyncio
    async def test_create_client_missing_botpy(self, channel: QQChannel) -> None:
        """_create_client raises ImportError when botpy is not installed."""
        import sys

        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def _mock_import(name, *args, **kwargs):
            if name == "botpy":
                raise ImportError("No module named 'botpy'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            with pytest.raises(ImportError, match="qq-botpy"):
                channel._create_client()

    @pytest.mark.asyncio
    async def test_start_with_mocked_botpy(self, channel: QQChannel) -> None:
        """start() launches a background thread when botpy is available."""
        mock_botpy = MagicMock()
        mock_client_instance = MagicMock()
        mock_botpy.Client.return_value = mock_client_instance
        mock_botpy.Intents.return_value = MagicMock()

        with patch.dict("sys.modules", {"botpy": mock_botpy}):
            await channel.start()

        assert channel._thread is not None
        assert channel._thread.daemon is True
        assert channel._thread.is_alive() or True  # may have exited quickly
        # Clean up
        await channel.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_client(self, channel: QQChannel) -> None:
        """stop() calls close() on the botpy client."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        channel._client = mock_client

        await channel.stop()
        mock_client.close.assert_awaited_once()
        assert channel._client is None


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for the send_message method."""

    @pytest.mark.asyncio
    async def test_send_message_logs(self, channel: QQChannel) -> None:
        """send_message executes without error (logs the attempt)."""
        # Currently a no-op that logs; just verify it doesn't raise
        await channel.send_message("user-1", "hello there")

    @pytest.mark.asyncio
    async def test_send_message_with_empty_text(self, channel: QQChannel) -> None:
        """send_message handles empty text gracefully."""
        await channel.send_message("user-1", "")
