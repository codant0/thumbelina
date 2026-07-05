"""WeChat QR code login via iLink API.

Calls WeChat's public iLink endpoints to obtain a QR code and poll
for scan status. On success the credentials are saved into
``~/.weclaw/accounts/``.

Protocol reference: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md
"""

from __future__ import annotations

import base64
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ILinkSessionExpiredError(Exception):
    """Raised when iLink reports that the bot session has expired (errcode=-14)."""


# iLink public endpoints (same ones WeClaw uses internally)
_QR_CODE_URL = "https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3"
_QR_STATUS_URL = "https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status?qrcode="

_CONNECT_TIMEOUT = 10.0
_POLL_TIMEOUT = 45.0  # slightly longer than the 40 s long-poll


# ── Data models ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class QRCodeResult:
    """Response from the QR code fetch endpoint."""

    qrcode: str
    """Unique ID used for polling."""

    qrcode_img_content: str
    """Content to encode in the QR code (typically a URL)."""


@dataclass(frozen=True)
class WeChatCredentials:
    """Credentials returned after a successful scan."""

    bot_token: str
    ilink_bot_id: str
    base_url: str
    ilink_user_id: str


@dataclass(frozen=True)
class QRStatusResult:
    """Response from the QR status poll endpoint."""

    status: str
    """One of: ``wait``, ``scaned``, ``confirmed``, ``expired``."""

    credentials: WeChatCredentials | None = None
    """Populated only when *status* is ``confirmed``."""


# ── Manager ──────────────────────────────────────────────────────────


class WeChatQRCodeManager:
    """Manages the WeChat QR-code login flow via iLink API."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(_POLL_TIMEOUT, connect=_CONNECT_TIMEOUT),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Fetch QR code ────────────────────────────────────────────────

    async def fetch_qrcode(self) -> QRCodeResult:
        """Fetch a new QR code from the iLink API.

        Raises
        ------
        httpx.HTTPStatusError
            If the iLink API returns a non-2xx status.
        httpx.ConnectError
            If the iLink API is unreachable.
        """
        client = await self._get_client()
        resp = await client.get(
            _QR_CODE_URL,
            headers={"SKRouteTag": "1001"},
        )
        resp.raise_for_status()
        data = resp.json()

        qrcode = data.get("qrcode", "")
        img_content = data.get("qrcode_img_content", "")

        if not qrcode:
            raise ValueError("iLink API returned empty qrcode")

        logger.info("Fetched QR code: %s", qrcode[:16])
        return QRCodeResult(qrcode=qrcode, qrcode_img_content=img_content)

    # ── Poll status ──────────────────────────────────────────────────

    async def poll_status(self, qrcode: str) -> QRStatusResult:
        """Poll the iLink API once for the QR code scan status.

        This is a **single** long-poll request (up to ~40 s).  The caller
        should loop until the status is ``confirmed`` or ``expired``.

        Parameters
        ----------
        qrcode:
            The QR code ID returned by :meth:`fetch_qrcode`.

        Raises
        ------
        httpx.HTTPStatusError
            If the iLink API returns a non-2xx status.
        """
        client = await self._get_client()
        resp = await client.get(
            _QR_STATUS_URL + qrcode,
            headers={
                "SKRouteTag": "1001",
                "iLink-App-ClientVersion": "1",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "wait")
        creds: WeChatCredentials | None = None

        if status == "confirmed":
            creds = WeChatCredentials(
                bot_token=data.get("bot_token", ""),
                ilink_bot_id=data.get("ilink_bot_id", ""),
                base_url=data.get("baseurl", ""),
                ilink_user_id=data.get("ilink_user_id", ""),
            )
            logger.info("QR code confirmed for bot %s", creds.ilink_bot_id)

        return QRStatusResult(status=status, credentials=creds)

    # ── Save credentials ─────────────────────────────────────────────

    @staticmethod
    def save_credentials(creds: WeChatCredentials) -> str:
        """Save credentials to ``~/.weclaw/accounts/{bot_id}.json``.

        Returns the path to the saved file.

        Raises
        ------
        OSError
            If the file cannot be written.
        """
        accounts_dir = _accounts_dir()
        accounts_dir.mkdir(parents=True, exist_ok=True)

        bot_id = _normalize_id(creds.ilink_bot_id)
        path = accounts_dir / f"{bot_id}.json"

        path.write_text(
            json.dumps(
                {
                    "bot_token": creds.bot_token,
                    "ilink_bot_id": creds.ilink_bot_id,
                    "baseurl": creds.base_url,
                    "ilink_user_id": creds.ilink_user_id,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        logger.info("Credentials saved to %s", path)
        return str(path)


# ── Helpers ──────────────────────────────────────────────────────────


def _accounts_dir() -> Path:
    """Return ``~/.weclaw/accounts``."""
    return Path.home() / ".weclaw" / "accounts"


def _normalize_id(raw: str) -> str:
    """Replace filesystem-unsafe characters in bot ID."""
    import re

    return re.sub(r"[^\w\-]", "-", raw)


# ── iLink Message Types ────────────────────────────────────────────


@dataclass
class ILMessageItem:
    """A single item inside an iLink message."""

    type: int
    """1=Text, 2=Image, 3=Voice, 4=File, 5=Video."""

    text: str = ""
    """Text content (for type=1)."""


@dataclass
class ILMessage:
    """An incoming message from the iLink getupdates API."""

    message_id: int
    from_user_id: str
    to_user_id: str
    message_type: int
    """1=User, 2=Bot."""
    message_state: int
    """0=New, 1=Generating, 2=Finish."""
    context_token: str = ""
    """Routing anchor for replies - must be passed back verbatim."""
    items: list[ILMessageItem] = field(default_factory=list)


# ── iLink Client ───────────────────────────────────────────────────

_DEFAULT_ILINK_BASE = "https://ilinkai.weixin.qq.com"


class ILinkClient:
    """Direct WeChat iLink API client for long-polling and sending.

    Implements the weixin-bot protocol for direct iLink API communication.
    See: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md
    """

    def __init__(
        self,
        bot_token: str,
        ilink_bot_id: str,
        ilink_user_id: str,
        base_url: str = _DEFAULT_ILINK_BASE,
    ) -> None:
        self.bot_token = bot_token
        self.ilink_bot_id = ilink_bot_id
        self.ilink_user_id = ilink_user_id
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        # Generate X-WECHAT-UIN: base64 of random uint32 as decimal string
        random_uin = str(random.randint(100000000, 999999999))
        self._uin = base64.b64encode(random_uin.encode()).decode()

    def _generate_uin(self) -> str:
        """Generate a new X-WECHAT-UIN for each request (per protocol spec)."""
        random_uin = str(random.randint(100000000, 999999999))
        return base64.b64encode(random_uin.encode()).decode()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "X-WECHAT-UIN": self._generate_uin(),
            "SKRouteTag": "1001",
        }

    # ── Receive (long-poll) ────────────────────────────────────────

    async def getupdates(self, sync_buffer: str = "") -> tuple[list[ILMessage], str]:
        """Long-poll for new messages (~35 s).

        Returns ``(messages, new_sync_buffer)``.
        """
        client = await self._get_client()

        # Per protocol spec: use get_updates_buf and base_info
        request_body = {
            "get_updates_buf": sync_buffer,
            "base_info": {
                "bot_id": self.ilink_bot_id,
                "user_id": self.ilink_user_id,
            },
        }

        resp = await client.post(
            f"{self.base_url}/ilink/bot/getupdates",
            json=request_body,
            headers=self._headers(),
        )

        # iLink returns 200 even on auth errors — check the JSON body
        resp.raise_for_status()
        data = resp.json()

        # Check for errors (protocol uses "ret" field)
        ret = data.get("ret", 0)
        errcode = data.get("errcode", ret)  # Support both formats

        if errcode == -14:
            logger.error("iLink session expired (errcode=-14) — re-authenticate via QR code")
            raise ILinkSessionExpiredError("iLink session expired")
        if errcode != 0:
            logger.warning(
                "iLink getupdates returned errcode=%s: %s",
                errcode,
                data.get("errmsg", data.get("retmsg", "")),
            )

        # Protocol uses "get_updates_buf" for cursor
        new_sync = data.get("get_updates_buf", data.get("sync_buffer", sync_buffer))
        raw_msgs = data.get("msgs", data.get("messages")) or []
        messages: list[ILMessage] = []

        for raw in raw_msgs:
            items = [
                ILMessageItem(
                    type=item.get("type", 0),
                    text=item.get("text_item", {}).get("text", ""),
                )
                for item in raw.get("item_list", [])
            ]
            messages.append(
                ILMessage(
                    message_id=raw.get("message_id", 0),
                    from_user_id=raw.get("from_user_id", ""),
                    to_user_id=raw.get("to_user_id", ""),
                    message_type=raw.get("message_type", 0),
                    message_state=raw.get("message_state", 0),
                    context_token=raw.get("context_token", ""),
                    items=items,
                )
            )

        return messages, new_sync

    # ── Send ───────────────────────────────────────────────────────

    async def send_message(
        self,
        user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any]:
        """Send a text reply to a WeChat user via iLink sendmessage.

        Parameters
        ----------
        user_id:
            Recipient's WeChat user ID.
        text:
            Message text content.
        context_token:
            Context token from the incoming message (required by protocol).
        """
        client = await self._get_client()
        client_id = f"weclaw-{int(time.time())}-{random.randint(1000, 9999)}"

        # Per protocol spec: msg structure with context_token
        msg_body = {
            "from_user_id": self.ilink_bot_id,
            "to_user_id": user_id,
            "client_id": client_id,
            "message_type": 2,  # BOT message type
            "message_state": 2,  # FINISH state
            "item_list": [
                {"type": 1, "text_item": {"text": text}},
            ],
        }

        # context_token is mandatory for message delivery
        if context_token:
            msg_body["context_token"] = context_token

        resp = await client.post(
            f"{self.base_url}/ilink/bot/sendmessage",
            json={"msg": msg_body},
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        # Check for errors
        ret = data.get("ret", 0)
        errcode = data.get("errcode", ret)
        if errcode != 0:
            logger.warning(
                "iLink sendmessage returned errcode=%s: %s",
                errcode,
                data.get("errmsg", data.get("retmsg", "")),
            )
        return data  # type: ignore[no-any-return]

    # ── Lifecycle ──────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def extract_text(msg: ILMessage) -> str:
    """Return the first text item from a message, or empty string."""
    for item in msg.items:
        if item.type == 1 and item.text:
            return item.text
    return ""
