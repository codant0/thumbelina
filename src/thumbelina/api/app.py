"""FastAPI application factory for Thumbelina API."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes import chat, conversations
from thumbelina.api.websocket import router as ws_router
from thumbelina.config import AppConfig, load_config
from thumbelina.llm.factory import create_provider
from thumbelina.memory.manager import MemoryManager
from thumbelina.security.auth import AuthService
from thumbelina.security.rate_limit import RateLimiter

# Paths exempt from authentication
_AUTH_WHITELIST = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class _AuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that validates Bearer JWT tokens.

    Attached only when ``config.auth.secret_key`` is non-empty.
    """

    def __init__(self, app, auth_service: AuthService) -> None:
        super().__init__(app)
        self._auth = auth_service

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _AUTH_WHITELIST:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = auth_header[len("Bearer "):]
        payload = self._auth.verify_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        request.state.user_id = payload.user_id
        request.state.user_roles = payload.roles
        return await call_next(request)


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that applies per-IP rate limiting."""

    def __init__(self, app, limiter: RateLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"

        if not self._limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
            )

        return await call_next(request)


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

    agent = ThumbelinaAgent(
        llm_provider=llm_provider,
        memory_manager=memory,
        request_timeout=config.llm.request_timeout,
    )
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
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add rate limit middleware (before auth so 429 is returned before 401)
    if config.rate_limit.enabled:
        limiter = RateLimiter(
            max_requests=config.rate_limit.max_requests,
            window_seconds=config.rate_limit.window_seconds,
        )
        app.add_middleware(_RateLimitMiddleware, limiter=limiter)

    # Add auth middleware when a secret key is configured
    if config.auth.secret_key:
        auth_service = AuthService(secret_key=config.auth.secret_key)
        app.add_middleware(_AuthMiddleware, auth_service=auth_service)

    # Health check endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Include routers
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(ws_router)

    return app
