"""WeChat iLink API routes.

Uses weixin-bot protocol for direct iLink communication.
See: https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from thumbelina.api.deps import get_wechat_channel
from thumbelina.channels.wechat_channel import WeChatChannel
from thumbelina.channels.wechat_qrcode import WeChatQRCodeManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wechat"])

# Lazy singleton — created on first use, shared across requests.
_qrcode_manager = None


def _get_qrcode_manager() -> WeChatQRCodeManager:
    global _qrcode_manager
    if _qrcode_manager is None:
        from thumbelina.channels.wechat_qrcode import WeChatQRCodeManager

        _qrcode_manager = WeChatQRCodeManager()
    return _qrcode_manager


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------


class WeChatIncomingMessage(BaseModel):
    """Payload for incoming WeChat messages (webhook or direct)."""

    from_: str = Field(alias="from", description="Sender's WeChat user ID")
    text: str = Field(default="", description="Message content")
    type: str = Field(default="text", description="Message type: text, voice, image")

    model_config = {"populate_by_name": True}


class WeChatSendMessage(BaseModel):
    """Request body for the /wechat/send endpoint."""

    user_id: str = Field(description="Recipient's WeChat user ID")
    text: str = Field(description="Message content")


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@router.post("/wechat/incoming")
async def wechat_incoming(
    message: WeChatIncomingMessage,
    request: Request,
    channel: WeChatChannel = Depends(get_wechat_channel),
) -> JSONResponse:
    """Webhook endpoint for incoming WeChat messages.

    This endpoint can receive messages from external services or directly
    from the iLink API. The endpoint validates an optional signature,
    delegates to ``WeChatChannel.handle_incoming``, and returns the agent response.
    """
    # Optional webhook secret verification
    secret = channel._config.webhook_secret
    if secret:
        signature = request.headers.get("X-WeClaw-Signature", "")
        if not _verify_signature(secret, await request.body(), signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

    response_text = await channel.handle_incoming(
        user_id=message.from_,
        text=message.text,
        msg_type=message.type,
    )

    return JSONResponse(content={"response": response_text})


@router.post("/wechat/send")
async def wechat_send(
    body: WeChatSendMessage,
    channel: WeChatChannel = Depends(get_wechat_channel),
) -> JSONResponse:
    """API endpoint to send a message to a WeChat user via iLink."""
    try:
        result = await channel.send_message(user_id=body.user_id, text=body.text)
    except Exception as exc:
        logger.exception("Failed to send message via iLink")
        raise HTTPException(
            status_code=502,
            detail=f"iLink send failed: {exc}",
        ) from exc

    return JSONResponse(content={"sent": True, "ilink_response": result})


@router.get("/wechat/status")
async def wechat_status(
    channel: WeChatChannel = Depends(get_wechat_channel),
) -> JSONResponse:
    """Check iLink connection status."""
    status = await channel.check_status()
    return JSONResponse(content=status)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature of the request body."""
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, "sha256").hexdigest()
    return hmac.compare_digest(expected, signature)


# ------------------------------------------------------------------
# QR Code Login schemas
# ------------------------------------------------------------------


class ConfirmLoginRequest(BaseModel):
    """Request body for POST /wechat/qrcode/confirm."""

    bot_token: str = Field(description="Bot token from iLink")
    ilink_bot_id: str = Field(description="iLink bot ID")
    base_url: str = Field(description="iLink base URL")
    ilink_user_id: str = Field(description="iLink user ID")


# ------------------------------------------------------------------
# QR Code Login routes
# ------------------------------------------------------------------


@router.post("/wechat/qrcode")
async def get_wechat_qrcode() -> JSONResponse:
    """Fetch a new QR code for WeChat login.

    Returns the QR code ID and content to render as a QR code image.
    The client should then poll ``GET /wechat/qrcode/status``.
    """
    manager = _get_qrcode_manager()
    try:
        result = await manager.fetch_qrcode()
    except Exception as exc:
        logger.exception("Failed to fetch QR code from iLink")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch QR code: {exc}",
        ) from exc

    return JSONResponse(
        content={
            "qrcode": result.qrcode,
            "qrcode_img_content": result.qrcode_img_content,
        }
    )


@router.get("/wechat/qrcode/status")
async def wechat_qrcode_status(
    qrcode: str = Query(..., description="QR code ID to poll"),
) -> JSONResponse:
    """Poll the scan status of a QR code.

    This endpoint performs a single long-poll (~40 s).  The client
    should call it repeatedly until the status is ``confirmed`` or
    ``expired``.
    """
    manager = _get_qrcode_manager()
    try:
        result = await manager.poll_status(qrcode)
    except Exception as exc:
        logger.exception("Failed to poll QR status from iLink")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to poll status: {exc}",
        ) from exc

    body: dict[str, Any] = {"status": result.status}
    if result.credentials is not None:
        body["credentials"] = {
            "bot_token": result.credentials.bot_token,
            "ilink_bot_id": result.credentials.ilink_bot_id,
            "base_url": result.credentials.base_url,
            "ilink_user_id": result.credentials.ilink_user_id,
        }

    return JSONResponse(content=body)


@router.post("/wechat/qrcode/confirm")
async def confirm_wechat_login(
    body: ConfirmLoginRequest,
    request: Request,
) -> JSONResponse:
    """Save credentials and enable the WeChat channel.

    The client calls this after receiving ``status=confirmed`` from the
    poll endpoint. This saves the credentials to ``CHANNEL/.weclaw/accounts/``
    and hot-enables the WeChat channel via the runtime config manager.
    """
    from thumbelina.channels.wechat_qrcode import WeChatCredentials

    config = request.app.state.config
    accounts_dir = config.channels.wechat.accounts_dir

    creds = WeChatCredentials(
        bot_token=body.bot_token,
        ilink_bot_id=body.ilink_bot_id,
        base_url=body.base_url,
        ilink_user_id=body.ilink_user_id,
    )

    manager = _get_qrcode_manager()
    try:
        saved_path = manager.save_credentials(creds, accounts_dir)
    except OSError as exc:
        logger.exception("Failed to save credentials")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save credentials: {exc}",
        ) from exc

    # Auto-enable and start the WeChat channel via runtime config manager
    from thumbelina.channels.config import WeChatChannelConfig

    new_channel_config = WeChatChannelConfig(
        enabled=True,
        bot_token=body.bot_token,
        ilink_bot_id=body.ilink_bot_id,
        ilink_user_id=body.ilink_user_id,
        ilink_base_url=body.base_url,
        accounts_dir=accounts_dir,
        webhook_secret=config.channels.wechat.webhook_secret,
    )

    runtime_manager = getattr(request.app.state, "runtime_config_manager", None)
    agent = getattr(request.app.state, "agent", None)
    connected = False

    if runtime_manager is not None and agent is not None:
        try:
            from thumbelina.api.websocket import broadcast_chat_message

            # Signature must mirror the app.py lifespan callback: handle_incoming
            # invokes it with 5 positional args (including inbound image refs,
            # 设计 §2). A stale 4-arg signature raises TypeError on every turn
            # (swallowed by the caller) and the web UI stops receiving
            # channel_message frames until restart.
            async def _on_wechat_message(
                cid: str,
                user_text: str,
                response: str,
                source: str = "wechat",
                attachments: list[dict[str, Any]] | None = None,
            ) -> None:
                await broadcast_chat_message(
                    {
                        "channel_message": {
                            "channel": "wechat",
                            "conversation_id": cid,
                            "user_message": user_text,
                            "response": response,
                            "source": source,
                            "attachments": attachments,
                        }
                    }
                )

            connected = await runtime_manager.swap_channel(
                channel_name="wechat",
                new_config=new_channel_config,
                app_state=request.app.state,
                agent=agent,
                on_message_callback=_on_wechat_message,
            )
        except Exception:
            logger.warning(
                "Failed to auto-start WeChat channel after login",
                exc_info=True,
            )
            # swap_channel already persists the config before attempting to
            # start, so ilink_bot_id is saved even on failure.  Nothing more
            # to do here — the channel will retry on next restart.
    else:
        # No runtime manager — update in-memory config and persist directly
        # so ilink_bot_id survives restart.
        config.channels.wechat = new_channel_config
        config_path = getattr(request.app.state, "config_path", None)
        if config_path is not None:
            try:
                from thumbelina.config.persistence import save_config

                save_config(config, config_path)
            except Exception:
                logger.warning("Failed to persist config after login", exc_info=True)

    logger.info(
        "WeChat login confirmed for bot %s — channel enabled, connected=%s",
        body.ilink_bot_id,
        connected,
    )

    return JSONResponse(
        content={
            "status": "ok",
            "bot_id": body.ilink_bot_id,
            "credentials_path": saved_path,
            "connected": connected,
        }
    )
