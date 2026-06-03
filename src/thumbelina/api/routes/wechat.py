"""WeChat ClawBot API routes."""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from thumbelina.api.deps import get_wechat_channel
from thumbelina.channels.wechat_channel import WeChatChannel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wechat"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------


class WeChatIncomingMessage(BaseModel):
    """Payload sent by WeClaw to Thumbelina's webhook."""

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
    """Webhook endpoint for WeClaw to deliver incoming WeChat messages.

    WeClaw POSTs messages here.  The endpoint validates an optional
    signature, delegates to ``WeChatChannel.handle_incoming``, and
    returns the agent response.
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
    """API endpoint to send a message to a WeChat user via WeClaw."""
    try:
        result = await channel.send_message(user_id=body.user_id, text=body.text)
    except Exception as exc:
        logger.exception("Failed to send message via WeClaw")
        raise HTTPException(
            status_code=502,
            detail=f"WeClaw send failed: {exc}",
        ) from exc

    return JSONResponse(content={"sent": True, "weclaw_response": result})


@router.get("/wechat/status")
async def wechat_status(
    channel: WeChatChannel = Depends(get_wechat_channel),
) -> JSONResponse:
    """Check WeClaw connection status."""
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
