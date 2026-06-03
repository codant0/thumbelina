"""WeChat ClawBot channel -- bridges Thumbelina to WeChat via WeClaw HTTP API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.channels.base import Channel
from thumbelina.channels.config import WeChatChannelConfig

logger = logging.getLogger(__name__)

# Default timeouts (seconds)
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 30.0
_MAX_RETRIES = 2


class WeChatChannel(Channel):
    """WeChat channel backed by WeClaw HTTP bridge.

    Parameters
    ----------
    config:
        WeChat-specific configuration (API URL, token, etc.).
    agent:
        The Thumbelina agent used to process incoming messages.
    """

    def __init__(
        self,
        config: WeChatChannelConfig,
        agent: ThumbelinaAgent,
    ) -> None:
        self._config = config
        self._agent = agent
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the httpx client for sending messages to WeClaw."""
        headers: dict[str, str] = {}
        if self._config.weclaw_token:
            headers["Authorization"] = f"Bearer {self._config.weclaw_token}"
        self._client = httpx.AsyncClient(
            base_url=self._config.weclaw_api_url,
            headers=headers,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )
        logger.info("WeChat channel started (WeClaw API: %s)", self._config.weclaw_api_url)

    async def stop(self) -> None:
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("WeChat channel stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_message(self, user_id: str, text: str) -> dict[str, Any]:
        """Send a text message to a WeChat user via WeClaw.

        Parameters
        ----------
        user_id:
            WeChat user identifier (e.g. ``wxid_xxxx``).
        text:
            Message body.

        Returns
        -------
        dict
            Parsed JSON response from WeClaw.

        Raises
        ------
        httpx.ConnectError
            If WeClaw is not reachable.
        httpx.TimeoutException
            If the request times out after retries.
        RuntimeError
            If the channel has not been started.
        """
        if self._client is None:
            raise RuntimeError("WeChatChannel has not been started")

        payload = {"to": user_id, "text": text}
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await self._client.post("/api/send", json=payload)
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "WeClaw send attempt %d/%d failed: %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )

        # All retries exhausted
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Receiving (called by the webhook route)
    # ------------------------------------------------------------------

    async def handle_incoming(
        self,
        user_id: str,
        text: str,
        msg_type: str = "text",
    ) -> str:
        """Process an incoming message from WeClaw and return a response.

        Parameters
        ----------
        user_id:
            Sender's WeChat user ID.
        text:
            Message content.
        msg_type:
            Message type (``text``, ``voice``, ``image``).

        Returns
        -------
        str
            The agent's response text.
        """
        if msg_type != "text":
            logger.info(
                "Received non-text message (type=%s) from %s; skipping agent",
                msg_type,
                user_id,
            )
            return f"[{msg_type} message received -- currently only text is supported]"

        try:
            response = await self._agent.run(text)
            return response
        except Exception:
            logger.exception("Agent failed to process message from %s", user_id)
            return "Sorry, I encountered an error processing your message."

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def check_status(self) -> dict[str, Any]:
        """Check whether WeClaw is reachable.

        Returns
        -------
        dict
            Status dict with ``connected`` key and optional ``error``.
        """
        if self._client is None:
            return {"connected": False, "error": "Channel not started"}

        try:
            resp = await self._client.get("/health")
            return {"connected": resp.status_code == 200}
        except httpx.ConnectError:
            return {"connected": False, "error": "Connection refused"}
        except httpx.TimeoutException:
            return {"connected": False, "error": "Timeout"}
        except Exception as exc:
            return {"connected": False, "error": str(exc)}
