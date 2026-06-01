"""FastAPI application factory for Thumbelina API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from thumbelina.api.routes import chat, conversations
from thumbelina.api.websocket import router as ws_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns
    -------
    FastAPI
        The configured FastAPI application instance.
    """
    app = FastAPI(title="Thumbelina API", version="0.1.0")

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Include routers
    app.include_router(chat.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(ws_router)

    return app
