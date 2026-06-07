"""QQ Bot API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from thumbelina.api.deps import get_qq_channel
from thumbelina.channels.qq_channel import QQChannel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["qq"])


@router.get("/qq/status")
async def qq_status(
    channel: QQChannel = Depends(get_qq_channel),
) -> JSONResponse:
    """Check QQ Bot connection status."""
    status = await channel.check_status()
    return JSONResponse(content=status)
