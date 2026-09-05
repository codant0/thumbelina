"""WeChat QR code login via iLink API.

Calls WeChat's public iLink endpoints to obtain a QR code and poll
for scan status. On success the credentials are saved into
``CHANNEL/.weclaw/accounts/`` (relative to the working directory).

Protocol reference: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


class ILinkSessionExpiredError(Exception):
    """Raised when iLink reports that the bot session has expired (errcode=-14)."""


class ILinkMediaError(Exception):
    """Raised when the CDN 媒体协议失败（如缺少 upload_param、CDN 上传非 2xx、
    响应缺失 ``x-encrypted-param`` 头）。调用方可据此决定单张降级，不影响文本回复。"""


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
    def save_credentials(creds: WeChatCredentials, accounts_dir: str = "") -> str:
        """Save credentials to ``{accounts_dir}/{bot_id}.json``.

        The directory defaults to ``CHANNEL/.weclaw/accounts`` and can be
        overridden via *accounts_dir* (``channels.wechat.accounts_dir``).

        Returns the path to the saved file.

        Raises
        ------
        OSError
            If the file cannot be written.
        """
        accounts_dir_path = _accounts_dir(accounts_dir)
        accounts_dir_path.mkdir(parents=True, exist_ok=True)

        bot_id = _normalize_id(creds.ilink_bot_id)
        path = accounts_dir_path / f"{bot_id}.json"

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


def _accounts_dir(override: str = "") -> Path:
    """Return the credential storage directory.

    Defaults to ``CHANNEL/.weclaw/accounts`` relative to the working
    directory (same level as the MEMORY/TODO directories); a non-empty
    *override* (from ``channels.wechat.accounts_dir``) takes precedence.
    """
    if override:
        return Path(override).expanduser()
    return Path("CHANNEL") / ".weclaw" / "accounts"


def _normalize_id(raw: str) -> str:
    """Replace filesystem-unsafe characters in bot ID."""
    import re

    return re.sub(r"[^\w\-]", "-", raw)


def _credentials_path(accounts_dir: str, bot_id: str) -> Path:
    """Return the credentials file path for a normalized bot ID."""
    return _accounts_dir(accounts_dir) / f"{_normalize_id(bot_id)}.json"


def load_credentials(accounts_dir: str = "", bot_id: str = "") -> WeChatCredentials | None:
    """Load saved iLink credentials from ``{accounts_dir}/{bot_id}.json``.

    When *bot_id* is empty, the accounts directory is scanned and the most
    recently modified credentials file is used (useful when the bot ID is
    not known after a container rebuild — see :func:`discover_credentials`).

    Parameters
    ----------
    accounts_dir:
        Override for the credential storage directory
        (``channels.wechat.accounts_dir``); empty uses the default.
    bot_id:
        The iLink bot ID to look up. Empty = auto-discover.

    Returns
    -------
    WeChatCredentials | None
        The loaded credentials, or ``None`` if no credentials file exists
        or the file cannot be parsed.
    """
    if bot_id:
        path = _credentials_path(accounts_dir, bot_id)
        if path.exists():
            return _parse_credentials_file(path)
        return None

    discovered = discover_credentials_file(accounts_dir)
    if discovered is None:
        return None
    return _parse_credentials_file(discovered)


def discover_credentials_file(accounts_dir: str = "") -> Path | None:
    """Scan the accounts directory for the most recently saved credentials.

    Returns ``None`` when the directory does not exist or contains no
    ``*.json`` files. Only files whose name looks like ``{bot_id}.json``
    are considered.
    """
    dir_path = _accounts_dir(accounts_dir)
    if not dir_path.is_dir():
        return None

    candidates = [p for p in dir_path.glob("*.json") if p.is_file()]
    if not candidates:
        return None

    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    logger.info("Discovered credentials file: %s", newest)
    return newest


def _parse_credentials_file(path: Path) -> WeChatCredentials | None:
    """Parse a credentials JSON file into :class:`WeChatCredentials`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        bot_token = data.get("bot_token", "")
        ilink_bot_id = data.get("ilink_bot_id", "")
        if not bot_token or not ilink_bot_id:
            logger.warning("Credentials file %s is missing bot_token/ilink_bot_id", path)
            return None
        return WeChatCredentials(
            bot_token=bot_token,
            ilink_bot_id=ilink_bot_id,
            base_url=data.get("baseurl", ""),
            ilink_user_id=data.get("ilink_user_id", ""),
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse credentials file %s: %s", path, exc)
        return None


# ── AES 媒体加解密工具 ──────────────────────────────────────────────
#
# 微信 iLink CDN 上的媒体（图片等）统一使用 AES-128-ECB + PKCS7，key 16 字节。
# 野外观测到两种 key 编码并存：base64(原始16字节) 与 base64(hex字符串)，
# 部分 item 还直接给裸 hex（image_item.aeskey）——解析需全部兼容。


def _parse_aes_key(b64_or_hex: str) -> bytes:
    """把任一在野 key 编码统一解析为 16 字节原始 key。

    支持三种编码（裸 hex 优先判定，避免与 base64 字符集歧义）：

    - 裸 32-hex 字符串（``image_item.aeskey``）；
    - base64(原始 16 字节)（``media.aes_key`` 编码一）；
    - base64(hex 字符串)（``media.aes_key`` 编码二）。

    Raises
    ------
    ValueError
        编码无法识别或 key 不是 16 字节。
    """
    raw = b64_or_hex.strip()
    if not raw:
        raise ValueError("AES key 为空")

    # 1) 裸 32-hex（16 字节 key 的十六进制表示）
    if len(raw) == 32 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return bytes.fromhex(raw)

    # 2) base64：解码后为 16 字节原始 key，或 32 字节 hex 字符串
    try:
        decoded = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise ValueError(f"AES key 编码无法识别（既非裸 hex 也非合法 base64）: {exc}") from exc

    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            return bytes.fromhex(decoded.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"AES key base64 内容不是合法的 hex 字符串: {exc}") from exc

    raise ValueError(f"AES key 解码后长度异常（期望 16 字节或 32-hex，实际 {len(decoded)} 字节）")


def _normalize_aes_key(key: bytes | str) -> bytes:
    """把 *key*（bytes 或任一字符串编码）规范为 16 字节原始 key。"""
    raw_key = _parse_aes_key(key) if isinstance(key, str) else key
    if len(raw_key) != 16:
        raise ValueError(f"AES-128 key 必须为 16 字节，实际 {len(raw_key)} 字节")
    return raw_key


def aes_ecb_encrypt(data: bytes, key: bytes | str) -> bytes:
    """AES-128-ECB + PKCS7 加密，返回密文（出站图片上传用）。

    *key* 可为 16 字节原始 key 或任一在野字符串编码（见 :func:`_parse_aes_key`）。
    """
    raw_key = _normalize_aes_key(key)
    encryptor = Cipher(algorithms.AES(raw_key), modes.ECB()).encryptor()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    return encryptor.update(padded) + encryptor.finalize()


def aes_ecb_decrypt(data: bytes, key: bytes | str) -> bytes:
    """AES-128-ECB + PKCS7 解密，返回明文（入站媒体下载后调用）。

    *key* 可为 16 字节原始 key 或任一在野字符串编码（见 :func:`_parse_aes_key`）。

    Raises
    ------
    ValueError
        密文长度不是 16 的倍数，或 PKCS7 填充非法（常见于 key 不匹配）。
    """
    raw_key = _normalize_aes_key(key)
    if len(data) == 0 or len(data) % 16 != 0:
        raise ValueError(f"AES-ECB 密文长度必须是 16 的倍数，实际 {len(data)} 字节")
    decryptor = Cipher(algorithms.AES(raw_key), modes.ECB()).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


# ── iLink Message Types ────────────────────────────────────────────


@dataclass
class ILMessageItem:
    """A single item inside an iLink message."""

    type: int
    """1=Text, 2=Image, 3=Voice, 4=File, 5=Video."""

    text: str = ""
    """Text content (for type=1)."""

    # ── 图片项（type=2）字段，由 getupdates 解析器从 image_item 填充 ──

    image_media_eqp: str = ""
    """``image_item.media.encrypt_query_param`` — CDN 下载签名令牌。"""

    image_aes_key_b64: str = ""
    """``image_item.media.aes_key`` — base64 编码（两种在野编码之一，原样保留）。"""

    image_aeskey_hex: str = ""
    """``image_item.aeskey`` — 裸 32-hex；解密 key 优先级高于 media.aes_key。"""

    image_full_url: str = ""
    """服务器提供的完整下载 URL（若有）；使用前必须过 CDN 域 allowlist。"""

    image_size: int = 0
    """``image_item.mid_size`` — 密文/中尺寸图字节数。"""

    image_width: int = 0
    """图片宽度（thumb_width，服务器仅提供缩略图尺寸时即为其宽）。"""

    image_height: int = 0
    """图片高度（thumb_height，服务器仅提供缩略图尺寸时即为其高）。"""

    def resolved_aes_key(self) -> str | None:
        """按协议优先级解析图片 AES key，返回裸 32-hex 字符串。

        优先级：item 级 ``aeskey``（裸 hex）> ``media.aes_key``
        （后者兼容 base64(原始16字节) / base64(hex字符串) 两种编码）。

        Returns
        -------
        str | None
            裸 hex key；两者皆缺或编码无法解析时返回 ``None``（调用方降级）。
        """
        if self.image_aeskey_hex:
            return self.image_aeskey_hex
        if self.image_aes_key_b64:
            try:
                return _parse_aes_key(self.image_aes_key_b64).hex()
            except ValueError as exc:
                logger.warning("无法解析 image_item.media.aes_key 编码: %s", exc)
                return None
        return None


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


def _message_item_from_raw(raw_item: dict[str, Any]) -> ILMessageItem:
    """把 getupdates 的单个 ``item_list`` 条目解析为 :class:`ILMessageItem`。

    图片项（type=2）字段从 ``image_item`` 填充；AES key 两种在野编码
    原样保留（``image_aeskey_hex`` / ``image_aes_key_b64``），使用方经
    :meth:`ILMessageItem.resolved_aes_key` 按「aeskey hex > media.aes_key」
    优先级取值。
    """
    image_item = raw_item.get("image_item") or {}
    media = image_item.get("media") or {}
    return ILMessageItem(
        type=raw_item.get("type", 0),
        text=raw_item.get("text_item", {}).get("text", ""),
        image_media_eqp=media.get("encrypt_query_param", ""),
        image_aes_key_b64=media.get("aes_key", ""),
        image_aeskey_hex=image_item.get("aeskey", ""),
        # full_url 兼容三种在野位置：image_item.full_url / image_item.url / media.full_url
        image_full_url=(
            image_item.get("full_url") or image_item.get("url") or media.get("full_url") or ""
        ),
        image_size=image_item.get("mid_size", 0),
        image_width=image_item.get("width") or image_item.get("thumb_width", 0),
        image_height=image_item.get("height") or image_item.get("thumb_height", 0),
    )


# ── iLink Client ───────────────────────────────────────────────────

_DEFAULT_ILINK_BASE = "https://ilinkai.weixin.qq.com"

NOVA_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
"""微信 iLink CDN 固定域（媒体下载/上传共用）。"""

_CDN_HOST_SUFFIX = ".cdn.weixin.qq.com"
"""CDN 域 allowlist 后缀——payload 里的 full_url 只允许 ``*.cdn.weixin.qq.com``（SSRF 防护）。"""


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
            items = [_message_item_from_raw(item) for item in raw.get("item_list", [])]
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

    # ── Media (download) ───────────────────────────────────────────

    @staticmethod
    def _is_allowed_cdn_url(url: str) -> bool:
        """CDN 域 allowlist：仅放行 ``https`` 且主机为 ``*.cdn.weixin.qq.com`` 的 URL。

        防 SSRF：payload 里的 full_url 可能被构造指向内网/任意主机，
        域不匹配即拒绝（用 parsed.hostname 判定，避免查询串伪造）。
        """
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = parsed.hostname or ""
        return host.endswith(_CDN_HOST_SUFFIX)

    async def download_media(
        self,
        encrypt_query_param: str,
        aes_key: bytes | str,
        full_url: str | None = None,
    ) -> bytes:
        """从微信 CDN 下载媒体并解密，返回明文字节（入站图片等）。

        - URL：``GET {NOVA_CDN_BASE}/download?encrypted_query_param=<urlencode>``；
          **不带任何鉴权头**（encrypt_query_param 本身即服务端签名令牌）。
        - 服务器若提供了 *full_url* 则优先使用，但其域必须匹配
          ``*.cdn.weixin.qq.com``（SSRF 防护），否则拒绝。
        - 解密：AES-128-ECB + PKCS7，key 16 字节（编码兼容见
          :func:`_parse_aes_key`；优先级见 :meth:`ILMessageItem.resolved_aes_key`）。

        Raises
        ------
        ValueError
            full_url 未通过域 allowlist、AES key 编码无法识别，
            或 PKCS7 填充非法（常见于 key 不匹配）。
        httpx.HTTPError
            CDN 网络层/HTTP 状态错误原样向上传播（调用方决定降级）。
        """
        if full_url:
            if not self._is_allowed_cdn_url(full_url):
                # 错误消息只带 host + path：full_url 查询串是服务端签名
                # 令牌，不应进入异常文本/日志。
                parsed = urlparse(full_url)
                raise ValueError(
                    f"拒绝非微信 CDN 域的 full_url（SSRF 防护）: "
                    f"host={parsed.hostname or ''} path={parsed.path}"
                )
            url = full_url
        else:
            url = (
                f"{NOVA_CDN_BASE}/download"
                f"?encrypted_query_param={quote(encrypt_query_param, safe='')}"
            )

        client = await self._get_client()
        resp = await client.get(url)  # 协议要求：GET 且不带任何鉴权头
        resp.raise_for_status()
        return aes_ecb_decrypt(resp.content, aes_key)

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

    # ── Media (upload/send) ────────────────────────────────────────

    async def send_image(
        self,
        user_id: str,
        data: bytes,
        context_token: str,
        file_ext: str = "jpg",
    ) -> None:
        """发送图片给微信用户（三步流程；iLink 无 uploadmedia 端点）。

        协议步骤（设计文档 §1.2）：

        1. ``POST /ilink/bot/getuploadurl``（bot_token 鉴权）：携带随机
           AES key（裸 hex）、明文 md5、PKCS7 填充后大小等，换取
           ``upload_param``；
        2. ``POST {CDN}/upload?encrypted_query_param=<upload_param>&filekey=<filekey>``
           ——**必须 POST**（不能用 PUT），body 为 AES-ECB 密文，
           ``Content-Type: application/octet-stream``；响应头
           **``x-encrypted-param``** 即回引令牌；
        3. ``POST /ilink/bot/sendmessage``：image_item 的
           ``media.aes_key`` 必须是 **base64(hex字符串)** 而非
           base64(原始字节)——编码错误则对方看到灰框；
           ``mid_size`` 为密文字节数。

        平台约束（腾讯 iLink）：

        - 回复必须落在用户最后一条消息的 **24 小时窗口**内；
        - 仅支持 **1v1 私聊**，不能主动发起会话；
        - 文字说明（caption）需作为**独立文本消息先行发送**（调用方负责，
          参见 :meth:`send_message`）。

        Parameters
        ----------
        user_id:
            接收方微信用户 ID。
        data:
            图片明文字节。
        context_token:
            入站消息携带的 context_token（协议必需的路由锚点）。
        file_ext:
            图片扩展名（如 ``jpg``/``png``）；协议载荷不携带，仅用于日志。

        Raises
        ------
        ILinkMediaError
            getuploadurl 未返回 ``upload_param``、CDN 上传返回非 2xx，
            或响应缺失 ``x-encrypted-param`` 头。
        httpx.HTTPError
            iLink API / CDN 网络层错误原样向上传播（调用方决定降级）。
        """
        aes_key_hex = secrets.token_hex(16)  # 16 字节 → 32 裸 hex 字符
        ciphertext = aes_ecb_encrypt(data, aes_key_hex)
        filekey = secrets.token_hex(16)  # 16 字节 → 32 hex 字符
        client_id = f"weclaw-{int(time.time())}-{random.randint(1000, 9999)}"

        # ── 第 1 步：getuploadurl 换取 upload_param ──
        client = await self._get_client()
        resp = await client.post(
            f"{self.base_url}/ilink/bot/getuploadurl",
            json={
                "filekey": filekey,
                "media_type": 1,  # 1=IMAGE
                "to_user_id": user_id,
                "rawsize": len(data),
                "rawfilemd5": hashlib.md5(data).hexdigest(),  # 明文 md5（协议要求）
                "filesize": len(ciphertext),  # PKCS7 填充后大小
                "no_need_thumb": True,
                "aeskey": aes_key_hex,
            },
            headers=self._headers(),
        )
        resp.raise_for_status()
        upload_data = resp.json()
        upload_param = upload_data.get("upload_param", "")
        if not upload_param:
            raise ILinkMediaError("getuploadurl 响应缺少 upload_param")

        # ── 第 2 步：CDN POST 密文（必须 POST），取回 x-encrypted-param ──
        cdn_resp = await client.post(
            (
                f"{NOVA_CDN_BASE}/upload"
                f"?encrypted_query_param={quote(upload_param, safe='')}"
                f"&filekey={quote(filekey, safe='')}"
            ),
            content=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
        )
        if cdn_resp.status_code < 200 or cdn_resp.status_code >= 300:
            raise ILinkMediaError(f"CDN 上传失败: HTTP {cdn_resp.status_code}")
        encrypted_param = cdn_resp.headers.get("x-encrypted-param", "")
        if not encrypted_param:
            raise ILinkMediaError("CDN 上传响应缺少 x-encrypted-param 头")

        # ── 第 3 步：sendmessage 引用已上传媒体 ──
        msg_body = {
            "from_user_id": self.ilink_bot_id,
            "to_user_id": user_id,
            "client_id": client_id,
            "message_type": 2,  # BOT message type
            "message_state": 2,  # FINISH state
            "item_list": [
                {
                    "type": 2,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": encrypted_param,
                            # 关键 gotcha：必须是 base64(hex字符串)，而非 base64(原始字节)
                            "aes_key": base64.b64encode(aes_key_hex.encode("ascii")).decode(
                                "ascii"
                            ),
                            "encrypt_type": 1,
                        },
                        "mid_size": len(ciphertext),
                    },
                },
            ],
        }
        # context_token is mandatory for message delivery
        if context_token:
            msg_body["context_token"] = context_token

        send_resp = await client.post(
            f"{self.base_url}/ilink/bot/sendmessage",
            json={"msg": msg_body},
            headers=self._headers(),
        )
        send_resp.raise_for_status()
        send_data = send_resp.json()

        ret = send_data.get("ret", 0)
        errcode = send_data.get("errcode", ret)
        if errcode != 0:
            logger.warning(
                "iLink sendmessage(图片, ext=%s) returned errcode=%s: %s",
                file_ext,
                errcode,
                send_data.get("errmsg", send_data.get("retmsg", "")),
            )
        logger.info(
            "图片已发送至 %s（%d 明文字节 / %d 密文字节, ext=%s）",
            user_id,
            len(data),
            len(ciphertext),
            file_ext,
        )

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
