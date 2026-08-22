"""Channel abstract base class for IM integrations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Type alias: a handler that receives (user_id, text) and returns a response.
MessageHandler = Callable[[str, str], Awaitable[str]]


class Channel(ABC):
    """Abstract base class for all IM channel implementations.

    Subclasses must implement ``start``, ``stop``, and ``send_message``.
    Use ``set_handler`` to register an async callback that processes
    incoming messages and returns a response string.
    """

    def __init__(self) -> None:
        self._handler: MessageHandler | None = None
        self._last_user_id: str | None = None

    @property
    def last_user_id(self) -> str | None:
        """Most recent user who interacted with this channel, if any."""
        return self._last_user_id

    def set_handler(self, handler: MessageHandler) -> None:
        """Register a message-handling callback.

        Parameters
        ----------
        handler:
            An async callable ``(user_id: str, text: str) -> str`` that
            processes an incoming message and returns the response text.
        """
        self._handler = handler

    @abstractmethod
    async def start(self) -> None:
        """Start the channel connection."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel connection."""

    @abstractmethod
    async def send_message(
        self,
        user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any] | None:
        """Send a message to a specific user.

        Parameters
        ----------
        user_id:
            The target user identifier.
        text:
            The message text to send.
        context_token:
            Optional channel-specific context token (e.g. WeChat iLink).
        """
