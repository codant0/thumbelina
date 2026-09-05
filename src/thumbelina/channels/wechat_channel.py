"""WeChat channel — direct iLink long-polling integration.

Connects directly to WeChat's iLink bot API to receive messages via
long-polling and send replies, using the weixin-bot protocol.
Credentials are obtained from the QR code login flow and stored in
``CHANNEL/.weclaw/accounts/``.

Protocol reference: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md

All WeChat messages are routed to a single pinned conversation named
"微信Clawbot" so they appear at the top of the conversation list in the
Web UI.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, cast

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.channels.base import Channel
from thumbelina.channels.config import WeChatChannelConfig
from thumbelina.channels.wechat_qrcode import ILinkSessionExpiredError
from thumbelina.concurrency import per_conversation_lock

logger = logging.getLogger(__name__)

_WECHAT_CONVERSATION_NAME = "微信Clawbot"
# Legacy name used in older versions; migrated to _WECHAT_CONVERSATION_NAME on startup.
_WECHAT_LEGACY_CONVERSATION_NAME = "微信聊天"

# How often to log a polling summary (every N cycles)
_LOG_EVERY_N_POLLS = 100

# 单张入站图片下载/落盘失败时的占位文本(沿用旧版 non-text stub 文案):
# 降级为占位文字随本轮文本进入模型,不中断整个对话轮次(设计 §2)。
_IMAGE_PLACEHOLDER = "[image message received -- currently only text is supported]"


def _sniff_image_mime(data: bytes) -> tuple[str, str]:
    """从魔数嗅探图片 mime 与落盘扩展名;无法识别时按 JPEG 兜底。

    入站 image_item 不携带扩展名/mime 字段,只能靠文件头判断;微信
    图片以 JPEG 为主,故默认值取 ``image/jpeg``。
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "image/jpeg", "jpg"


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
        on_message_callback: Callable[
            [str, str, str, str, list[dict[str, Any]] | None], Coroutine[Any, Any, None]
        ]
        | None = None,
        runtime: Any | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._agent = agent
        self._runtime = runtime
        self._ilink: Any = None  # ILinkClient, imported lazily
        self._poll_task: asyncio.Task[None] | None = None
        self._sync_buffer: str = ""
        self._poll_count: int = 0
        self._on_message_callback = on_message_callback
        self._last_wechat_user_id: str | None = None  # Track last WeChat user for responses
        self._last_context_token: str = ""  # Track context_token for replies
        self._needs_authentication: bool = False

    @property
    def last_user_id(self) -> str | None:
        """Most recent WeChat user, used as the default notify recipient."""
        return self._last_wechat_user_id

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

        # 附件根目录接线(设计 §3-W2):共享 agent 从未在其他入口被接线
        # (WS 每连接克隆自行覆盖),微信入站图片需要落盘到与上传路由
        # 同源的根目录。惰性导入避免 channels → api 循环依赖;失败不
        # 阻断通道启动(后续下载路径会回退默认目录)。
        try:
            from thumbelina.api.routes.attachments import resolve_attachments_root

            app_state = getattr(getattr(self._runtime, "app", None), "state", None)
            self._agent.attachments_root = resolve_attachments_root(
                getattr(app_state, "config", None)
            )
        except Exception:
            logger.warning("Failed to wire attachments root for WeChat agent", exc_info=True)

        # If bot_token is empty, try loading saved credentials from the
        # accounts directory.  This happens after a restart when the YAML
        # config has been stripped of secrets.  Unlike the previous logic,
        # this does NOT require ilink_bot_id to be pre-populated: the
        # accounts directory is scanned and the latest credentials file is
        # discovered automatically, so a container rebuild that lost the
        # config/database (but kept the credentials volume) still recovers.
        if not self._config.bot_token:
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

    async def _load_saved_credentials(self) -> bool:
        """Load iLink credentials from the accounts directory.

        Load order:
        1. ``{accounts_dir}/{bot_id}.json`` — exact match when
           ``ilink_bot_id`` is already known (from YAML/database).
        2. Auto-discovery — scan the accounts directory and load the most
           recently saved credentials file.  This covers the case where the
           bot ID itself was lost (e.g. config database not persisted),
           as long as the credentials volume survived the rebuild.

        Returns ``True`` when credentials were loaded and applied to
        ``self._config``.
        """
        from thumbelina.channels.wechat_qrcode import load_credentials

        creds = load_credentials(
            accounts_dir=self._config.accounts_dir,
            bot_id=self._config.ilink_bot_id,
        )

        if creds is None:
            logger.warning(
                "No saved iLink credentials found in %s",
                self._config.accounts_dir or "CHANNEL/.weclaw/accounts",
            )
            return False

        self._config.bot_token = creds.bot_token
        self._config.ilink_bot_id = creds.ilink_bot_id
        self._config.ilink_user_id = creds.ilink_user_id
        if creds.base_url:
            self._config.ilink_base_url = creds.base_url

        logger.info(
            "Loaded saved iLink credentials for bot %s",
            self._config.ilink_bot_id,
        )
        return True

    async def _ensure_wechat_conversation(self) -> None:
        """Create or reuse a pinned '微信Clawbot' conversation for the agent.

        Migrates any legacy '微信聊天' conversation to the new name.
        """
        mm = self._agent.repository_manager
        if mm is None:
            logger.warning("No repository manager — WeChat messages will not be persisted")
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

    async def send_image(self, user_id: str, data: bytes, context_token: str = "") -> None:
        """Send an image to a WeChat user via the iLink 3-step upload flow.

        Thin wrapper over :meth:`ILinkClient.send_image` (getuploadurl → CDN
        POST → sendmessage). Used by the WebSocket sync path to forward Web
        attachments to the WeChat peer.

        Platform constraints (Tencent iLink): replies must land within the
        **24-hour window** following the user's last message; **1v1 private
        chats only** — the bot cannot initiate a conversation. Send any
        caption/reply text via :meth:`send_message` **before** calling this
        (protocol requires text to precede images).

        Raises
        ------
        RuntimeError
            If the channel has not been started or needs re-authentication.
        ILinkMediaError / httpx.HTTPError
            Protocol or network failure — callers degrade per-image.
        """
        if self._ilink is None:
            raise RuntimeError("WeChatChannel has not been started")

        if self._needs_authentication:
            raise RuntimeError(
                "WeChat session expired or not logged in. Please scan the QR code to authenticate."
            )

        # Use provided context_token or fall back to last received one
        effective_token = context_token or self._last_context_token
        await self._ilink.send_image(user_id, data, effective_token)

    # ------------------------------------------------------------------
    # Receiving (called by the poll loop)
    # ------------------------------------------------------------------

    async def handle_incoming(
        self,
        user_id: str,
        text: str,
        msg_type: str = "text",
        source: str = "wechat",
        attachments: list[dict[str, Any]] | None = None,
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
        attachments:
            Optional image attachment refs (``[{id, mime, width?, height?}]``)
            for inbound WeChat images (设计 §2). They are persisted with the
            user message and turned into image blocks by ``agent.run``.
            Empty *text* + refs is allowed (pure-image turn); a turn with
            neither is skipped entirely.

        Returns
        -------
        str
            The agent's response text.
        """
        if not text.strip() and not attachments:
            logger.info(
                "Received empty message (type=%s) from %s; skipping agent",
                msg_type,
                user_id,
            )
            return ""

        try:
            cid = self._agent.current_conversation_id or None
            logger.debug(
                "Calling agent.run() for user %s (conv=%s)",
                user_id,
                cid,
            )
            # 与 WebSocket/HTTP 入口共享 per-conversation 锁：同一会话的
            # 并发轮次会交错读改写同一检查点线程，必须串行化。
            async with per_conversation_lock(cid):
                # 应用会话的端点/角色并解析上下文窗口，与 HTTP/WebSocket
                # 共用同一套逻辑（惰性导入避免 channels → api 循环依赖）。
                window_tokens = None
                if self._runtime is not None and cid:
                    try:
                        from thumbelina.api.routes.chat import (
                            apply_conversation_runtime,
                            resolve_run_window,
                        )

                        await apply_conversation_runtime(self._runtime, self._agent, cid)
                        window_tokens = await resolve_run_window(self._runtime, self._agent, cid)
                    except Exception:
                        logger.warning("Failed to apply WeChat conversation runtime", exc_info=True)
                        window_tokens = None
                if window_tokens is not None:
                    response = await self._agent.run(
                        text, context_window_tokens=window_tokens, attachments=attachments
                    )
                else:
                    response = await self._agent.run(text, attachments=attachments)
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
                    # 入站图片 refs 随帧广播,前端并入乐观用户消息(设计 §2)。
                    await self._on_message_callback(cid, text, response, source, attachments)
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

    async def _collect_image_attachments(self, msg: Any) -> tuple[list[dict[str, Any]], int]:
        """Download, decrypt and persist every image item of *msg* (设计 §2).

        逐张走 W1 协议层:``download_media``(AES-ECB 解密)→ 落盘到附件根
        目录 ``yyyy/mm/<uuid>.<ext>`` → ``repo.create_attachment`` 入库,
        组 ``[{id, mime, width?, height?}]`` refs 供 ``agent.run`` 持久化
        并组装图像块。

        Fail-soft per image:缺 eqp/key、下载、落盘、入库任一失败只计入
        返回的 ``failed_count``(调用方降级为占位文本),绝不抛出、不中断
        对话轮次。

        Returns
        -------
        tuple[list[dict[str, Any]], int]
            ``(refs, failed_count)`` — 成功图片的附件引用列表与失败张数。
        """
        image_items = [item for item in msg.items if item.type == 2]
        if not image_items:
            return [], 0

        mm = self._agent.repository_manager
        if mm is None:
            logger.warning("No repository manager — skipping %d image item(s)", len(image_items))
            return [], len(image_items)

        # start() 已把共享 agent 的 attachments_root 接线到与上传路由同源
        # 的根目录;缺失时(接线失败/旧配置)回退默认目录,保证轮次不中断。
        root = self._agent.attachments_root
        if root is None:
            from thumbelina.api.routes.attachments import resolve_attachments_root

            root = resolve_attachments_root(None)

        from thumbelina.filestore import ensure_dir, write_bytes_atomic

        refs: list[dict[str, Any]] = []
        failed = 0
        for item in image_items:
            try:
                aes_key = item.resolved_aes_key()
                if not item.image_media_eqp or not aes_key:
                    raise ValueError("image item missing encrypt_query_param or AES key")
                data = await self._ilink.download_media(
                    item.image_media_eqp,
                    aes_key,
                    full_url=item.image_full_url or None,
                )
                mime, ext = _sniff_image_mime(data)
                now = datetime.now()
                file_id = uuid.uuid4().hex
                relative_path = f"{now:%Y/%m}/{file_id}.{ext}"
                full = root / f"{now:%Y}" / f"{now:%m}" / f"{file_id}.{ext}"
                ensure_dir(full.parent)
                write_bytes_atomic(full, data)
                record = await mm.create_attachment(
                    mime=mime,
                    size=len(data),
                    relative_path=relative_path,
                    width=item.image_width or None,
                    height=item.image_height or None,
                    sha256=hashlib.sha256(data).hexdigest(),
                )
                ref: dict[str, Any] = {"id": record["id"], "mime": mime}
                if item.image_width:
                    ref["width"] = item.image_width
                if item.image_height:
                    ref["height"] = item.image_height
                refs.append(ref)
            except Exception:
                failed += 1
                logger.warning(
                    "Failed to download inbound image for %s — degrading to placeholder",
                    msg.from_user_id,
                    exc_info=True,
                )
        return refs, failed

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

        # 入站图片(设计 §2):逐张下载解密 → 附件管道入库 → refs 随用户
        # 消息持久化并喂给模型。单张失败降级为占位文本,不中断轮次。
        refs, failed_images = await self._collect_image_attachments(msg)
        if failed_images:
            placeholder = "\n".join([_IMAGE_PLACEHOLDER] * failed_images)
            text = f"{text}\n{placeholder}" if text.strip() else placeholder

        # 纯图片轮(空文本 + 有图)允许触发;两者皆空才跳过。
        if not text.strip() and not refs:
            logger.debug("Ignoring message %s (no text, no images)", msg.message_id)
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
                msg_type="image" if refs else "text",
                attachments=refs or None,
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
