"""FastAPI application factory for Thumbelina API."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes import chat, conversations
from thumbelina.api.websocket import router as ws_router
from thumbelina.config import AppConfig, load_config
from thumbelina.llm.factory import create_provider
from thumbelina.memory.manager import MemoryManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""
    config: AppConfig = app.state.config

    memory = MemoryManager(config.memory.database_url)
    app.state.memory_manager = memory

    llm_provider = create_provider(
        config.llm.provider,
        model=config.llm.model,
        api_key=config.llm.api_key,
    )

    agent = ThumbelinaAgent(llm_provider=llm_provider, memory_manager=memory)
    app.state.agent = agent

    yield

    memory.close()


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    config:
        Optional application configuration.  When *None* the configuration
        is loaded from environment variables.

    Returns
    -------
    FastAPI
        The configured FastAPI application instance.
    """
    if config is None:
        config = load_config()

    app = FastAPI(title="Thumbelina API", version="0.1.0", lifespan=lifespan)
    app.state.config = config

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
