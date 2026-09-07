"""QQ Bot channel implementation using qq-botpy SDK."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import TYPE_CHECKING, Any

from thumbelina.channels.base import Channel

if TYPE_CHECKING:
    from thumbelina.agent.graph import ThumbelinaAgent
    from thumbelina.channels.config import QQChannelConfig

logger = logging.getLogger(__name__)

# Pattern to strip QQ @mention tags like <@user_id> or <@!user_id>
_AT_MENTION_RE = re.compile(r"<@!?\w+>")


def _clean_message_content(content: str) -> str:
    """Strip @mention tags and normalize whitespace from QQ message content.

    Parameters
    ----------
    content:
        Raw message content from QQ, potentially containing ``<@user_id>`` tags.

    Returns
    -------
    str
        Cleaned message text with mentions removed and whitespace trimmed.
    """
    cleaned = _AT_MENTION_RE.sub("", content)
    return cleaned.strip()


class QQChannel(Channel):
    """QQ Bot channel powered by the ``qq-botpy`` SDK.

    Parameters
    ----------
    config:
        QQ channel configuration (app_id, app_secret, etc.).
    agent:
        The ThumbelinaAgent instance used to process messages.
    """

    def __init__(
        self,
        config: QQChannelConfig,
        agent: ThumbelinaAgent,
    ) -> None:
        super().__init__()
        self._config = config
        self._agent = agent
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = asyncio.Event()
        # QQ 通道按 spec §8 无人值守：每条入站消息都通过一个 pinned
        # QQ 会话走 _apply_conversation_permission 接线，保证 mode 与
        # 工作区在 ContextVar 中落地（spec §8 规则 2：confirm 一律 deny）。
        # 启动时由 start() 创建/复用并写入 self._agent.current_conversation_id。
        self._conversation_name = "QQClawbot"

    def _create_client(self) -> Any:
        """Create and return a botpy Client subclass.

        The client overrides event handlers to route incoming messages
        through the Thumbelina agent.

        Returns
        -------
        Any
            A ``botpy.Client`` instance (or a mock in tests).

        Raises
        ------
        ImportError
            If ``qq-botpy`` is not installed.
        """
        try:
            import botpy  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "qq-botpy is required for the QQ channel. Install it with: pip install qq-botpy"
            )

        channel = self

        class _ThumbelinaBotClient(botpy.Client):  # type: ignore[misc]
            """Internal botpy client that delegates messages to Thumbelina."""

            async def on_ready(self) -> None:
                logger.info("QQ Bot connected and ready.")
                channel._ready.set()

            async def on_at_message_create(self, message: Any) -> None:
                """Handle guild @messages."""
                await channel._handle_message(
                    user_id=message.author.id if hasattr(message, "author") else "unknown",
                    content=message.content if hasattr(message, "content") else "",
                    reply_func=lambda text: message.reply(content=text),
                    source="guild",
                    guild_id=getattr(message, "guild_id", None),
                )

            async def on_group_at_message_create(self, message: Any) -> None:
                """Handle group @messages."""
                await channel._handle_message(
                    user_id=message.author.id if hasattr(message, "author") else "unknown",
                    content=message.content if hasattr(message, "content") else "",
                    reply_func=lambda text: message.reply(content=text),
                    source="group",
                    group_id=getattr(message, "group_openid", None),
                )

            async def on_c2c_message_create(self, message: Any) -> None:
                """Handle private (C2C) messages."""
                await channel._handle_message(
                    user_id=message.author.id if hasattr(message, "author") else "unknown",
                    content=message.content if hasattr(message, "content") else "",
                    reply_func=lambda text: message.reply(content=text),
                    source="c2c",
                )

        intents = botpy.Intents(
            public_guild_messages=True,
            public_messages=True,
        )
        return _ThumbelinaBotClient(intents=intents)

    async def _ensure_qq_conversation(self) -> None:
        """复用或创建 pinned QQ 会话(与微信 WeChatChannel._ensure_wechat_conversation 同模式)。

        用于把 spec §8 的 apply_conversation_runtime 接线到会话 id;缺失
        时入站消息仍按 ContextVar 默认值(fail-closed)兜底,绝不抛出。
        """
        mm = self._agent.repository_manager
        if mm is None:
            logger.warning("No repository manager — QQ messages will not be persisted")
            return
        try:
            conversations = await mm.get_conversations()
            for conv in conversations:
                if conv.get("name") == self._conversation_name:
                    self._agent.current_conversation_id = conv["id"]
                    logger.info("Reusing existing QQ conversation %s", conv["id"])
                    return
            conv_id = await mm.create_conversation(
                name=self._conversation_name,
                pinned=True,
            )
            self._agent.current_conversation_id = conv_id
            logger.info("Created QQ conversation %s", conv_id)
        except Exception:
            logger.exception("Failed to ensure QQ conversation")

    async def _handle_message(
        self,
        user_id: str,
        content: str,
        reply_func: Any,
        source: str,
        guild_id: str | None = None,
        group_id: str | None = None,
    ) -> None:
        """Process an incoming QQ message through the agent.

        Parameters
        ----------
        user_id:
            The QQ user ID of the message sender.
        content:
            Raw message content (may include @mention tags).
        reply_func:
            Async callable to send the reply back to QQ.
        source:
            Message source type: ``"guild"``, ``"group"``, or ``"c2c"``.
        guild_id:
            Guild ID (for guild messages).
        group_id:
            Group ID (for group messages).
        """
        # Check allow-lists for guild and group messages
        if source == "guild" and self._config.allowed_guilds:
            if guild_id and guild_id not in self._config.allowed_guilds:
                logger.debug("Ignoring message from non-allowed guild %s", guild_id)
                return
        if source == "group" and self._config.allowed_groups:
            if group_id and group_id not in self._config.allowed_groups:
                logger.debug("Ignoring message from non-allowed group %s", group_id)
                return

        cleaned = _clean_message_content(content)
        if not cleaned:
            logger.debug("Ignoring empty message from %s", user_id)
            return

        self._last_user_id = user_id

        logger.info(
            "QQ message from %s [%s]: %s",
            user_id,
            source,
            cleaned[:100],
        )

        # spec §8:QQ 通道无人值守(无审批者)。每条入站消息前调一次
        # apply_conversation_runtime(unattended=True):为闸门/工具级
        # security_review 写入正确的 ContextVar(permission + workspace),
        # 失败仅 WARNING,继续走 ContextVar 默认值兜底。
        cid = getattr(self._agent, "current_conversation_id", None)
        if cid and self._agent.repository_manager is not None:
            try:
                from thumbelina.api.routes.chat import apply_conversation_runtime

                # QQ 通道没有 runtime shim,共享 self._agent 上的 app.state
                # 没有引用;apply_conversation_runtime 只访问 app.state 上的
                # endpoint_manager(可空)与 config(可空),空上下文满足需求。
                from types import SimpleNamespace

                await apply_conversation_runtime(
                    SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                    self._agent,
                    cid,
                    unattended=True,
                )
            except Exception:
                logger.warning("Failed to apply QQ conversation runtime", exc_info=True)

        try:
            # Use the registered handler if set, otherwise fall back to agent
            if self._handler is not None:
                response = await self._handler(user_id, cleaned)
            else:
                response = await self._agent.run(cleaned)

            if response:
                await reply_func(response)
        except Exception:
            logger.error("Error processing QQ message from %s", user_id, exc_info=True)

    async def start(self) -> None:
        """Start the QQ Bot connection in a background thread.

        Since ``botpy.Client.run()`` is a blocking call that manages its
        own event loop, it is executed in a dedicated daemon thread.
        """
        try:
            self._client = self._create_client()
        except ImportError:
            logger.warning("Cannot start QQ channel: qq-botpy is not installed.")
            return

        # 启动时复用/创建 pinned QQ 会话(与微信 WeChatChannel 同模式),
        # 写入 self._agent.current_conversation_id 供后续入站消息调用
        # apply_conversation_runtime(..., unattended=True) 使用。
        # 失败仅 WARNING,通道照常启动 — agent.run() 仍走 ContextVar 默认
        # 值(fail-closed:只读 + 无审批者)。
        try:
            await self._ensure_qq_conversation()
        except Exception:
            logger.warning("Failed to ensure QQ conversation", exc_info=True)

        def _run_bot() -> None:
            try:
                self._client.run(
                    appid=self._config.app_id,
                    secret=self._config.app_secret,
                )
            except Exception:
                logger.error("QQ Bot client exited with error", exc_info=True)

        self._thread = threading.Thread(target=_run_bot, name="qq-bot", daemon=True)
        self._thread.start()
        logger.info("QQ Bot channel started (appid=%s)", self._config.app_id)

    async def stop(self) -> None:
        """Stop the QQ Bot connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                logger.warning("Error closing QQ Bot client", exc_info=True)
            self._client = None
        self._thread = None
        logger.info("QQ Bot channel stopped.")

    async def check_status(self) -> dict[str, Any]:
        """Check whether the QQ Bot is connected."""
        if self._client is None:
            return {"connected": False, "error": "Channel not started"}
        if self._thread is None or not self._thread.is_alive():
            return {"connected": False, "error": "Bot thread not running"}
        return {"connected": self._ready.is_set()}

    async def send_message(
        self,
        user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any] | None:
        """Send a proactive message to a QQ user.

        Parameters
        ----------
        user_id:
            The target user ID.
        text:
            The message text.
        context_token:
            Unused by QQ; accepted for compatibility with the base class.

        Note
        ----
        Proactive messaging in QQ requires the bot to have prior
        interaction with the user. This method is a placeholder that
        logs the attempt. Actual implementation depends on the botpy
        API for post-group-message or post-c2c-message.
        """
        logger.info("Sending QQ message to %s: %s", user_id, text[:100])
        # botpy proactive messaging requires specific API calls
        # that depend on the message source (guild/group/c2c).
        # This is logged for now; actual sending is handled per-event.
        return None
