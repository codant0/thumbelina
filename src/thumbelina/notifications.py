"""Notification manager for WebSocket-based push notifications."""

from __future__ import annotations

import logging
from typing import Any

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class NotificationManager:
    """Manages notification channels (WebSocket connections).

    Each user can have at most one active WebSocket subscription.
    Notifications are sent as JSON via the WebSocket connection.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, WebSocket] = {}

    async def subscribe(self, user_id: str, ws: WebSocket) -> None:
        """Subscribe a user's WebSocket connection for notifications.

        Parameters
        ----------
        user_id:
            The user identifier.
        ws:
            The active WebSocket connection.
        """
        # 如果已有连接，先关闭旧的
        old = self._subscribers.get(user_id)
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass
        self._subscribers[user_id] = ws

    async def unsubscribe(self, user_id: str) -> None:
        """Remove a user's WebSocket subscription.

        Parameters
        ----------
        user_id:
            The user identifier to unsubscribe.
        """
        self._subscribers.pop(user_id, None)

    async def notify(self, user_id: str, message: dict[str, Any]) -> bool:
        """Send a notification to a specific user.

        Parameters
        ----------
        user_id:
            The recipient user identifier.
        message:
            The JSON-serializable message payload.

        Returns
        -------
        bool
            True if the message was sent, False if the user is not subscribed.
        """
        ws = self._subscribers.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception as exc:
            logger.warning("Failed to notify user %s: %s", user_id, exc)
            # 移除失效连接
            self._subscribers.pop(user_id, None)
            return False

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Send a notification to all subscribed users.

        Parameters
        ----------
        message:
            The JSON-serializable message payload.

        Returns
        -------
        int
            Number of users successfully notified.
        """
        sent = 0
        failed_ids: list[str] = []
        for user_id, ws in self._subscribers.items():
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as exc:
                logger.warning("Failed to broadcast to user %s: %s", user_id, exc)
                failed_ids.append(user_id)
        # 清理失效连接
        for uid in failed_ids:
            self._subscribers.pop(uid, None)
        return sent

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)
