"""WeChat channel — direct iLink long-polling integration.

Connects directly to WeChat's iLink bot API to receive messages via
long-polling and send replies, using the weixin-bot protocol.
Credentials are obtained from the QR code login flow and stored in
``~/.weclaw/accounts/``.

Protocol reference: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md

All WeChat messages are routed to a single pinned conversation named
"微信Clawbot" so they appear at the top of the conversation list in the
Web UI.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, cast

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.channels.base import Channel
from thumbelina.channels.config import WeChatChannelConfig
from thumbelina.channels.wechat_qrcode import ILinkSessionExpiredError

logger = logging.getLogger(__name__)

_WECHAT_CONVERSATION_NAME = "微信Clawbot"
# Legacy name used in older versions; migrated to _WECHAT_CONVERSATION_NAME on startup.
_WECHAT_LEGACY_CONVERSATION_NAME = "微信聊天"

# How often to log a polling summary (every N cycles)
_LOG_EVERY_N_POLLS = 100


class WeChatChannel(Channel):
    """WeChat channel using direct iLink long-polling.

    Parameters
    ----------
    config:
        WeChat-specific configuration including iLink credentials.
    agent:
        The Thumbelina agent used to process incoming messages.
    """

    def __init__(
        self,
        config: WeChatChannelConfig,
        agent: ThumbelinaAgent,
        on_message_callback: Callable[[str, str, str, str], Coroutine[Any, Any, None]]
        | None = None,
    ) -> None:
        self._config = config
        self._agent = agent
        self._ilink: Any = None  # ILinkClient, imported lazily
        self._poll_task: asyncio.Task[None] | None = None
        self._sync_buffer: str = ""
        self._poll_count: int = 0
        self._on_message_callback = on_message_callback
        self._last_wechat_user_id: str | None = None  # Track last WeChat user for responses
        self._last_context_token: str = ""  # Track context_token for replies
        self._needs_authentication: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the iLink client, ensure a WeChat conversation, and start polling.

        This is a "soft" start: if no credentials are available, or if the
        saved credentials are expired, the channel is still created but
        marked as needing authentication. The backend can start normally,
        and the frontend can prompt the user to scan a QR code.
        """
        from thumbelina.channels.wechat_qrcode import ILinkClient

        # If bot_token is empty but ilink_bot_id is set, try loading saved
        # credentials from ~/.weclaw/accounts/{bot_id}.json.  This happens
        # after a restart when the YAML config has been stripped of secrets.
        if not self._config.bot_token and self._config.ilink_bot_id:
            await self._load_saved_credentials()

        if not self._config.bot_token:
            self._needs_authentication = True
            logger.warning(
                "WeChat channel not started: no bot_token. Scan the QR code again to authenticate."
            )
            return

        self._needs_authentication = False
        self._ilink = ILinkClient(
            bot_token=self._config.bot_token,
            ilink_bot_id=self._config.ilink_bot_id,
            ilink_user_id=self._config.ilink_user_id,
            base_url=self._config.ilink_base_url,
        )

        await self._ensure_wechat_conversation()

        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "WeChat channel started (iLink direct, bot=%s)",
            self._config.ilink_bot_id,
        )

    async def _load_saved_credentials(self) -> None:
        """Load iLink credentials from ``~/.weclaw/accounts/{bot_id}.json``.

        Called during :meth:`start` when ``bot_token`` is empty but
        ``ilink_bot_id`` is available (typical after a restart when the
        YAML config has been stripped of secrets).
        """
        from thumbelina.channels.wechat_qrcode import (
            _accounts_dir,
            _normalize_id,
        )

        bot_id = _normalize_id(self._config.ilink_bot_id)
        cred_path = _accounts_dir() / f"{bot_id}.json"

        if not cred_path.exists():
            logger.warning("No saved credentials at %s", cred_path)
            return

        try:
            import json

            data = json.loads(cred_path.read_text(encoding="utf-8"))
            self._config.bot_token = data.get("bot_token", "")
            self._config.ilink_bot_id = data.get("ilink_bot_id", self._config.ilink_bot_id)
            self._config.ilink_user_id = data.get("ilink_user_id", self._config.ilink_user_id)
            base_url = data.get("baseurl", "")
            if base_url:
                self._config.ilink_base_url = base_url

            logger.info(
                "Loaded saved iLink credentials for bot %s",
                self._config.ilink_bot_id,
            )
        except Exception:
            logger.warning("Failed to load saved credentials from %s", cred_path, exc_info=True)

    async def _ensure_wechat_conversation(self) -> None:
        """Create or reuse a pinned '微信Clawbot' conversation for the agent.

        Migrates any legacy '微信聊天' conversation to the new name.
        """
        mm = self._agent.memory_manager
        if mm is None:
            logger.warning("No memory manager — WeChat messages will not be persisted")
            return

        try:
            # Migrate legacy-named conversation if present
            legacy_id = await self._find_conversation_by_name(mm, _WECHAT_LEGACY_CONVERSATION_NAME)
            if legacy_id:
                await mm.rename_conversation(legacy_id, _WECHAT_CONVERSATION_NAME)
                self._agent.current_conversation_id = legacy_id
                logger.info(
                    "Migrated WeChat conversation %s to '%s'",
                    legacy_id,
                    _WECHAT_CONVERSATION_NAME,
                )
                return

            # Check if a conversation with this name already exists
            existing_id = await self._find_conversation_by_name(mm, _WECHAT_CONVERSATION_NAME)
            if existing_id:
                self._agent.current_conversation_id = existing_id
                logger.info("Reusing existing WeChat conversation %s", existing_id)
                return

            # Create a new pinned conversation
            conv_id = await mm.create_conversation(
                name=_WECHAT_CONVERSATION_NAME,
                pinned=True,
            )
            self._agent.current_conversation_id = conv_id
            logger.info("Created WeChat conversation %s", conv_id)
        except Exception:
            logger.exception("Failed to ensure WeChat conversation")

    @staticmethod
    async def _find_conversation_by_name(mm: Any, name: str) -> str | None:
        """Find an existing conversation with the given name."""
        try:
            conversations = await mm.get_conversations()
            for conv in conversations:
                if conv.get("name") == name:
                    return cast(str, conv["id"])
        except Exception:
            logger.warning("Failed to search for existing WeChat conversation", exc_info=True)
        return None

    async def stop(self) -> None:
        """Cancel the poll loop and close the iLink client."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._ilink is not None:
            await self._ilink.close()
            self._ilink = None

        logger.info("WeChat channel stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_message(
        self,
        user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any]:
        """Send a text message to a WeChat user via iLink sendmessage.

        Parameters
        ----------
        user_id:
            WeChat user identifier.
        text:
            Message body.
        context_token:
            Context token from the incoming message (required by protocol).
            If not provided, uses the last received context_token.

        Returns
        -------
        dict
            Parsed JSON response from iLink.

        Raises
        ------
        RuntimeError
            If the channel has not been started or needs re-authentication.
        """
        if self._ilink is None:
            raise RuntimeError("WeChatChannel has not been started")

        if self._needs_authentication:
            raise RuntimeError(
                "WeChat session expired or not logged in. Please scan the QR code to authenticate."
            )

        # Use provided context_token or fall back to last received one
        effective_token = context_token or self._last_context_token
        if not effective_token:
            logger.warning(
                "No context_token available for send_message to %s — message may not be delivered",
                user_id,
            )

        return cast(
            dict[str, Any],
            await self._ilink.send_message(user_id, text, effective_token),
        )

    # ------------------------------------------------------------------
    # Receiving (called by the poll loop)
    # ------------------------------------------------------------------

    async def handle_incoming(
        self,
        user_id: str,
        text: str,
        msg_type: str = "text",
        source: str = "wechat",
    ) -> str:
        """Process an incoming message and return an agent response.

        All messages are routed to the shared "微信Clawbot" conversation.

        Parameters
        ----------
        user_id:
            Sender's WeChat user ID.
        text:
            Message content.
        msg_type:
            Message type (``text``, ``voice``, ``image``).
        source:
            Origin of the message (``wechat`` or ``frontend``).

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
            logger.debug(
                "Calling agent.run() for user %s (conv=%s)",
                user_id,
                self._agent.current_conversation_id,
            )
            response = await self._agent.run(text)
            logger.debug("Agent returned %d chars for user %s", len(response), user_id)

            # Notify connected WebSocket clients (only for WeChat messages, not frontend)
            # Frontend already receives the response directly via WebSocket
            if self._on_message_callback and response and source == "wechat":
                cid = self._agent.current_conversation_id or ""
                logger.info(
                    "Broadcasting message to WebSocket clients (source=%s, conv=%s)",
                    source,
                    cid,
                )
                try:
                    await self._on_message_callback(cid, text, response, source)
                except Exception:
                    logger.warning("on_message_callback failed", exc_info=True)

            return response
        except Exception:
            logger.exception("Agent failed to process message from %s", user_id)
            return "Sorry, I encountered an error processing your message."

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def check_status(self) -> dict[str, Any]:
        """Check whether the iLink poll loop is running.

        Returns
        -------
        dict
            Status dict with ``connected`` and ``needs_authentication`` keys
            and optional ``error``.
        """
        if self._needs_authentication:
            return {
                "connected": False,
                "needs_authentication": True,
                "error": (
                    "WeChat session expired or not logged in. "
                    "Please scan the QR code to authenticate."
                ),
            }
        if self._poll_task is None:
            return {
                "connected": False,
                "needs_authentication": False,
                "error": "Channel not started",
            }
        if self._poll_task.done():
            exc = self._poll_task.exception()
            return {
                "connected": False,
                "needs_authentication": False,
                "error": f"Poll loop stopped: {exc}" if exc else "Poll loop stopped",
            }
        return {"connected": True, "needs_authentication": False}

    # ------------------------------------------------------------------
    # Internal: background polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Continuously long-poll iLink for messages and dispatch them."""
        logger.info(
            "iLink poll loop started (bot=%s, base_url=%s)",
            self._config.ilink_bot_id,
            self._config.ilink_base_url,
        )
        consecutive_errors = 0
        max_consecutive = 5

        while True:
            try:
                messages, self._sync_buffer = await self._ilink.getupdates(
                    self._sync_buffer,
                )
                consecutive_errors = 0
                self._poll_count += 1

                if messages:
                    logger.info("Received %d message(s) from iLink", len(messages))
                    for msg in messages:
                        await self._process_message(msg)

                if self._poll_count % _LOG_EVERY_N_POLLS == 0:
                    logger.debug(
                        "iLink poll cycle %d completed (%d messages this cycle)",
                        self._poll_count,
                        len(messages),
                    )

            except asyncio.CancelledError:
                raise  # propagate cancellation

            except ILinkSessionExpiredError:
                self._needs_authentication = True
                logger.error(
                    "iLink session expired — stopping poll loop. "
                    "Re-authenticate via QR code to resume."
                )
                break

            except Exception as exc:
                consecutive_errors += 1
                logger.warning(
                    "iLink poll error (%d/%d): %s",
                    consecutive_errors,
                    max_consecutive,
                    exc,
                )
                if consecutive_errors >= max_consecutive:
                    logger.error(
                        "Too many consecutive iLink errors — "
                        "the bot session may have expired. "
                        "Re-authenticate via QR code to resume."
                    )
                # Back off before retrying
                backoff = min(3.0 * (2 ** (consecutive_errors - 1)), 60.0)
                await asyncio.sleep(backoff)

    async def _process_message(self, msg: Any) -> None:
        """Process a single incoming iLink message."""
        from thumbelina.channels.wechat_qrcode import extract_text

        # Only process finished messages from users
        if msg.message_type != 1:
            logger.debug(
                "Skipping message %s: message_type=%d (not user)",
                msg.message_id,
                msg.message_type,
            )
            return

        if msg.message_state != 2:
            logger.debug(
                "Skipping message %s: message_state=%d (not finished)",
                msg.message_id,
                msg.message_state,
            )
            return

        text = extract_text(msg)
        if not text:
            logger.debug("Ignoring non-text message %s", msg.message_id)
            return

        logger.info(
            "Processing message %s from %s: %.80s",
            msg.message_id,
            msg.from_user_id,
            text,
        )

        # Track the last WeChat user ID and context_token for sending responses
        self._last_wechat_user_id = msg.from_user_id
        self._last_context_token = msg.context_token  # Required by protocol

        try:
            response = await self.handle_incoming(
                user_id=msg.from_user_id,
                text=text,
                msg_type="text",
            )
        except Exception:
            logger.exception("handle_incoming failed for message %s", msg.message_id)
            response = "Sorry, I encountered an error processing your message."

        if not response:
            logger.warning(
                "Empty response for message %s from %s — skipping send",
                msg.message_id,
                msg.from_user_id,
            )
            return

        try:
            await self.send_message(
                msg.from_user_id,
                response,
                context_token=msg.context_token,
            )
            logger.info("Replied to %s (%.60s)", msg.from_user_id, response)
        except Exception:
            logger.exception(
                "Failed to send reply to %s for message %s",
                msg.from_user_id,
                msg.message_id,
            )
