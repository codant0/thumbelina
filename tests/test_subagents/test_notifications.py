"""Tests for the NotificationManager."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from thumbelina.notifications import NotificationManager


@pytest.fixture
def manager():
    """Create a NotificationManager."""
    return NotificationManager()


@pytest.fixture
def mock_ws():
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_class_exists(self):
        """NotificationManager should be importable."""
        assert NotificationManager is not None

    def test_initial_subscriber_count(self, manager):
        """Should start with zero subscribers."""
        assert manager.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscribe(self, manager, mock_ws):
        """Should subscribe a user."""
        await manager.subscribe("user1", mock_ws)
        assert manager.subscriber_count == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, manager, mock_ws):
        """Should unsubscribe a user."""
        await manager.subscribe("user1", mock_ws)
        await manager.unsubscribe("user1")
        assert manager.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent(self, manager):
        """Unsubscribing a non-existent user should be a no-op."""
        await manager.unsubscribe("nobody")
        assert manager.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_notify_subscribed_user(self, manager, mock_ws):
        """Should send notification to subscribed user."""
        await manager.subscribe("user1", mock_ws)
        result = await manager.notify("user1", {"type": "test"})
        assert result is True
        mock_ws.send_json.assert_awaited_once_with({"type": "test"})

    @pytest.mark.asyncio
    async def test_notify_unsubscribed_user(self, manager):
        """Should return False for unsubscribed user."""
        result = await manager.notify("nobody", {"type": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_handles_send_failure(self, manager, mock_ws):
        """Should remove subscriber on send failure."""
        mock_ws.send_json = AsyncMock(side_effect=Exception("connection lost"))
        await manager.subscribe("user1", mock_ws)

        result = await manager.notify("user1", {"type": "test"})
        assert result is False
        # 失败后应该自动移除
        assert manager.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_broadcast(self, manager):
        """Should broadcast to all subscribers."""
        ws1 = AsyncMock()
        ws1.send_json = AsyncMock()
        ws2 = AsyncMock()
        ws2.send_json = AsyncMock()

        await manager.subscribe("user1", ws1)
        await manager.subscribe("user2", ws2)

        sent = await manager.broadcast({"type": "announcement"})
        assert sent == 2
        ws1.send_json.assert_awaited_once_with({"type": "announcement"})
        ws2.send_json.assert_awaited_once_with({"type": "announcement"})

    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(self, manager):
        """Broadcast with no subscribers should return 0."""
        sent = await manager.broadcast({"type": "test"})
        assert sent == 0

    @pytest.mark.asyncio
    async def test_broadcast_partial_failure(self, manager):
        """Should count successful sends and remove failed subscribers."""
        ws_ok = AsyncMock()
        ws_ok.send_json = AsyncMock()
        ws_fail = AsyncMock()
        ws_fail.send_json = AsyncMock(side_effect=Exception("broken"))

        await manager.subscribe("good", ws_ok)
        await manager.subscribe("bad", ws_fail)

        sent = await manager.broadcast({"type": "test"})
        assert sent == 1
        # 失败的连接应该被移除
        assert manager.subscriber_count == 1

    @pytest.mark.asyncio
    async def test_subscribe_replaces_old_connection(self, manager):
        """New subscription should close the old connection."""
        old_ws = AsyncMock()
        old_ws.send_json = AsyncMock()
        old_ws.close = AsyncMock()
        new_ws = AsyncMock()
        new_ws.send_json = AsyncMock()

        await manager.subscribe("user1", old_ws)
        await manager.subscribe("user1", new_ws)

        # 旧连接应该被关闭
        old_ws.close.assert_awaited_once()
        assert manager.subscriber_count == 1

        # 通知应该发送到新连接
        await manager.notify("user1", {"type": "test"})
        new_ws.send_json.assert_awaited_once()
