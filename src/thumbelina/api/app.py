"""FastAPI application factory for Thumbelina API."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes import (
    chat,
    conversations,
    data,
    plugins,
    qq,
    rag,
    skills,
    tasks,
    wechat,
)
from thumbelina.api.routes import (
    config as config_routes,
)
from thumbelina.api.websocket import router as ws_router
from thumbelina.config import AppConfig, load_config
from thumbelina.llm.endpoint_manager import EndpointManager
from thumbelina.llm.factory import create_provider
from thumbelina.llm.preset_manager import PresetManager
from thumbelina.memory.manager import MemoryManager
from thumbelina.notifications import NotificationManager
from thumbelina.scheduler.scheduler import ScheduledTask
from thumbelina.security.auth import AuthService
from thumbelina.security.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

# Paths exempt from authentication
_AUTH_WHITELIST = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def require_roles(
    request: Request,
    allowed_roles: list[str],
) -> bool:
    """Check that the authenticated user has at least one of the required roles.

    Parameters
    ----------
    request:
        The incoming request (must have ``user_roles`` set by auth middleware).
    allowed_roles:
        Roles that are permitted to access the resource.

    Returns
    -------
    bool
        *True* if the user has a matching role, *False* otherwise.
    """
    user_roles: list[str] = getattr(request.state, "user_roles", [])
    return any(role in allowed_roles for role in user_roles)


class _AuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that validates Bearer JWT tokens.

    Attached only when ``config.auth.secret_key`` is non-empty.
    """

    def __init__(
        self,
        app: ASGIApp,
        auth_service: AuthService,
        required_roles: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._auth = auth_service
        self._required_roles = required_roles

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.url.path in _AUTH_WHITELIST:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = auth_header[len("Bearer ") :]
        payload = self._auth.verify_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        request.state.user_id = payload.user_id
        request.state.user_roles = payload.roles

        # Global role check (when required_roles is configured)
        if self._required_roles and not require_roles(request, self._required_roles):
            return JSONResponse(
                status_code=403,
                content={"detail": "Insufficient permissions"},
            )

        return await call_next(request)


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that applies per-IP rate limiting."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"

        if not self._limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
            )

        return await call_next(request)


class _LazyLLMProvider:
    """Placeholder LLM provider that defers real provider creation until first use."""

    def __init__(self, provider_name: str, kwargs: dict) -> None:
        self._provider_name = provider_name
        self._kwargs = kwargs
        self._real = None

    def _ensure(self):
        if self._real is None:
            try:
                self._real = create_provider(self._provider_name, **self._kwargs)
            except Exception as exc:
                raise RuntimeError(
                    f"LLM provider '{self._provider_name}' is not available. "
                    f"Please activate a model in Web UI Settings. Error: {exc}"
                ) from exc
        return self._real

    @property
    def model(self):
        return self._kwargs.get("model", "unknown")

    @property
    def chat_model(self):
        return self._ensure().chat_model

    async def chat(self, messages):
        return await self._ensure().chat(messages)

    async def stream(self, messages):
        async for chunk in self._ensure().stream(messages):
            yield chunk

    def chat_sync(self, messages):
        return self._ensure().chat_sync(messages)

    async def list_models(self, **kwargs):
        return await self._ensure().list_models(**kwargs)

    async def speed_test(self, model, **kwargs):
        return await self._ensure().speed_test(model, **kwargs)

    async def test_connection(self, **kwargs):
        return await self._ensure().test_connection(**kwargs)

    def swap_provider(self, real_provider):
        self._real = real_provider


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""
    config: AppConfig = app.state.config

    memory = MemoryManager(config.memory.database_url)
    app.state.memory_manager = memory

    llm_kwargs: dict[str, Any] = {"model": config.llm.model}
    if config.llm.api_key:
        llm_kwargs["api_key"] = config.llm.api_key
    if config.llm.base_url:
        llm_kwargs["base_url"] = config.llm.base_url

    try:
        llm_provider = create_provider(config.llm.provider, **llm_kwargs)
    except Exception as exc:
        logger.warning(
            "LLM provider %s not configured (%s). Configure via Web UI Settings.",
            config.llm.provider,
            exc,
        )
        llm_provider = _LazyLLMProvider(config.llm.provider, llm_kwargs)

    # Initialize feedback repository
    feedback_repo = None
    try:
        from thumbelina.memory.feedback_repo import FeedbackRepository

        feedback_repo = FeedbackRepository(db_url=config.memory.database_url)
        app.state.feedback_repo = feedback_repo
    except Exception:
        logger.warning("Feedback repository not initialized", exc_info=True)

    # Initialize optional subsystems
    skill_engine = None
    skill_repo = None
    try:
        from thumbelina.skills.application import SkillApplicationEngine
        from thumbelina.skills.repository import SkillRepository

        skill_repo = SkillRepository(db_url=config.memory.database_url)
        skill_engine = SkillApplicationEngine(
            repository=skill_repo,
            llm_provider=llm_provider,
            feedback_repo=feedback_repo,
        )
    except Exception:
        logger.warning("Skill engine not initialized", exc_info=True)

    composition_engine = None
    try:
        from thumbelina.skills.composition_engine import CompositionEngine
        from thumbelina.skills.composition_repo import CompositionRepository

        if skill_repo is None:
            from thumbelina.skills.repository import SkillRepository

            skill_repo = SkillRepository(db_url=config.memory.database_url)
        comp_repo = CompositionRepository(db_url=config.memory.database_url)
        composition_engine = CompositionEngine(
            composition_repo=comp_repo,
            skill_repo=skill_repo,
            llm_provider=llm_provider,
        )
    except Exception:
        logger.debug("Composition engine not initialized", exc_info=True)

    subagent_manager = None
    try:
        from thumbelina.subagents.manager import SubagentManager

        subagent_manager = SubagentManager(llm_provider=llm_provider)
    except Exception:
        logger.debug("Subagent manager not initialized", exc_info=True)

    # Initialize RAG components
    rag_kb_repo = None
    rag_doc_repo = None
    rag_store_manager = None
    rag_embedding_registry = None
    try:
        from thumbelina.rag.embedding.registry import EmbeddingRegistry
        from thumbelina.rag.embedding.store_manager import ChromaStoreManager
        from thumbelina.rag.knowledge_base.db import init_rag_db
        from thumbelina.rag.knowledge_base.repository import (
            DocumentRepository,
            KnowledgeBaseRepository,
        )

        # 复用主数据库引擎初始化 RAG 表
        rag_session_factory = init_rag_db(memory.repository.engine)
        rag_kb_repo = KnowledgeBaseRepository(session_factory=rag_session_factory)
        rag_doc_repo = DocumentRepository(session_factory=rag_session_factory)

        # 向量存储
        try:
            import chromadb

            chroma_client = chromadb.PersistentClient(path="./data/chroma")
        except Exception:
            import chromadb

            chroma_client = chromadb.EphemeralClient()
        rag_store_manager = ChromaStoreManager(chroma_client)

        # Embedding 注册
        rag_embedding_registry = EmbeddingRegistry()
        try:
            from thumbelina.rag.embedding.provider_hf import HuggingFaceEmbedding

            rag_embedding_registry.register("Qwen/Qwen3-Embedding-0.6B", HuggingFaceEmbedding)
            logger.info("HuggingFace embedding provider registered")
        except Exception:
            logger.debug("HuggingFace embedding not available", exc_info=True)

        # 存储到 app.state
        app.state.rag_kb_repo = rag_kb_repo
        app.state.rag_doc_repo = rag_doc_repo
        app.state.rag_store_manager = rag_store_manager
        app.state.rag_embedding_registry = rag_embedding_registry

        logger.info("RAG components initialized")
    except Exception:
        logger.debug("RAG not initialized (missing dependencies)", exc_info=True)

    # 通知管理器
    notification_manager = NotificationManager()
    app.state.notification_manager = notification_manager

    scheduler = None
    try:
        from thumbelina.scheduler.scheduler import TaskScheduler

        scheduler = TaskScheduler()

        # 任务完成时广播通知
        async def _on_due_task(task: ScheduledTask) -> None:
            await notification_manager.broadcast(
                {
                    "type": "task_completed",
                    "task_id": task.id,
                    "description": task.description,
                }
            )

        await scheduler.start(on_due_task=_on_due_task)
    except Exception:
        logger.debug("Scheduler not initialized", exc_info=True)

    # Initialize user profiler
    user_profiler = None
    try:
        from thumbelina.memory.profiler import UserProfiler
        from thumbelina.memory.user_profile_repo import UserProfileRepository

        profile_repo = UserProfileRepository(db_url=config.memory.database_url)
        user_profiler = UserProfiler(
            llm_provider=llm_provider,
            profile_repo=profile_repo,
        )
        app.state.user_profiler = user_profiler
    except Exception:
        logger.debug("User profiler not initialized", exc_info=True)

    # Initialize conversation auto-namer (shares the active LLM provider)
    from thumbelina.memory.namer import ConversationNamer

    conversation_namer = ConversationNamer(llm_provider=llm_provider)
    app.state.conversation_namer = conversation_namer

    # Load plugins from configured directories (with sandbox validation)
    if config.plugin_dirs:
        from thumbelina.plugins.manager import PluginManager
        from thumbelina.plugins.sandbox import PluginSandbox
        from thumbelina.plugins.sandboxed_loader import SandboxedPluginLoader

        sandbox = PluginSandbox()
        loader = SandboxedPluginLoader(sandbox=sandbox)
        plugin_manager = PluginManager(sandboxed_loader=loader)

        for plugin_dir in config.plugin_dirs:
            try:
                loaded = await plugin_manager.load_plugins_from_directory(plugin_dir)
                if loaded:
                    logger.info("Loaded %d plugins from %s", loaded, plugin_dir)
            except Exception:
                logger.warning("Failed to load plugins from %s", plugin_dir, exc_info=True)
        app.state.plugin_manager = plugin_manager

    from thumbelina.tools import get_all_tools

    agent = ThumbelinaAgent(
        llm_provider=llm_provider,
        tools=get_all_tools(),
        memory_manager=memory,
        request_timeout=config.llm.request_timeout,
        skill_engine=skill_engine,
        subagent_manager=subagent_manager,
        scheduler=scheduler,
        composition_engine=composition_engine,
        user_profiler=user_profiler,
        conversation_namer=conversation_namer,
    )
    app.state.agent = agent

    # Inject RAG components into agent
    if rag_store_manager is not None:
        agent._rag_store_manager = rag_store_manager
    if rag_embedding_registry is not None:
        agent._rag_embedding_registry = rag_embedding_registry

    # Store subsystem references for runtime hot-swap access
    app.state.skill_engine = skill_engine
    app.state.composition_engine = composition_engine
    app.state.subagent_manager = subagent_manager

    # Initialize config repository for database-backed configuration
    from thumbelina.config.config_repo import ConfigRepository

    config_repo = ConfigRepository(db_url=config.memory.database_url)
    app.state.config_repo = config_repo

    # Initialize LLM endpoint manager backed by the config repository
    endpoint_manager = EndpointManager(config_repo=config_repo)
    app.state.endpoint_manager = endpoint_manager

    # Import YAML config to database on first startup (if DB is empty)
    from thumbelina.config.loader import import_yaml_to_db

    config_path = getattr(app.state, "config_path", None)
    try:
        if await config_repo.is_empty():
            imported = import_yaml_to_db(config_path, config.memory.database_url)
            if imported:
                logger.info("Imported %d config keys from YAML to database", imported)
        else:
            logger.debug("Database already contains config — skipping YAML import")
    except Exception:
        logger.warning("Failed to import YAML config to database", exc_info=True)

    # Initialize runtime configuration manager
    from thumbelina.config.runtime_manager import RuntimeConfigManager

    runtime_manager = RuntimeConfigManager(
        config=config,
        config_path=getattr(app.state, "config_path", None),
        config_repo=config_repo,
    )
    app.state.runtime_config_manager = runtime_manager

    # Load configuration overrides from database BEFORE initializing channels
    # This ensures channels use database config, not just YAML
    await runtime_manager.load_from_database()
    logger.info("Loaded configuration from database")

    # Initialize LLM preset manager after runtime config is loaded
    preset_manager = PresetManager(
        config_repo=config_repo,
        runtime_manager=runtime_manager,
        agent=agent,
        skill_engine=getattr(app.state, "skill_engine", None),
        composition_engine=getattr(app.state, "composition_engine", None),
        subagent_manager=getattr(app.state, "subagent_manager", None),
        user_profiler=getattr(app.state, "user_profiler", None),
    )
    app.state.preset_manager = preset_manager
    try:
        await preset_manager.restore_active_preset()
    except Exception:
        logger.warning("Failed to restore active LLM preset", exc_info=True)

    # Restore the default LLM endpoint (Web UI "Models") on startup so the
    # agent uses the user-activated model instead of requiring environment
    # variables. Only applies when no preset was restored above.
    try:
        if await preset_manager.get_active_preset() is None:
            active = await endpoint_manager.get_active_endpoint_model()
            if active is not None and active[0].api_key:
                default_endpoint, active_model = active
                endpoint_kwargs: dict[str, Any] = {
                    "api_key": default_endpoint.api_key,
                    "model": active_model,
                }
                if default_endpoint.base_url:
                    endpoint_kwargs["base_url"] = default_endpoint.base_url
                restored_provider = create_provider(default_endpoint.provider, **endpoint_kwargs)
                agent.swap_provider(restored_provider)
                if getattr(app.state, "skill_engine", None) is not None:
                    app.state.skill_engine.llm_provider = restored_provider
                if getattr(app.state, "composition_engine", None) is not None:
                    app.state.composition_engine.llm_provider = restored_provider
                if getattr(app.state, "subagent_manager", None) is not None:
                    app.state.subagent_manager.llm_provider = restored_provider
                if getattr(app.state, "user_profiler", None) is not None:
                    app.state.user_profiler.llm_provider = restored_provider
                if getattr(app.state, "conversation_namer", None) is not None:
                    app.state.conversation_namer.llm_provider = restored_provider
                config.llm.provider = default_endpoint.provider
                config.llm.model = active_model
                config.llm.api_key = default_endpoint.api_key
                config.llm.base_url = default_endpoint.base_url or None
                logger.info(
                    "Restored default LLM endpoint on startup: %s/%s",
                    default_endpoint.provider,
                    config.llm.model,
                )
    except Exception:
        logger.warning("Failed to restore default LLM endpoint", exc_info=True)

    # Initialize WeChat channel if enabled (AFTER database config is loaded)
    wechat_channel = None
    if config.channels.wechat.enabled:
        try:
            from thumbelina.api.websocket import broadcast_chat_message
            from thumbelina.channels.wechat_channel import WeChatChannel

            async def _on_wechat_message(
                cid: str,
                user_text: str,
                response: str,
                source: str = "wechat",
            ) -> None:
                await broadcast_chat_message(
                    {
                        "channel_message": {
                            "channel": "wechat",
                            "conversation_id": cid,
                            "user_message": user_text,
                            "response": response,
                            "source": source,
                        }
                    }
                )

            wechat_channel = WeChatChannel(
                config=config.channels.wechat,
                agent=agent,
                on_message_callback=_on_wechat_message,
            )
            await wechat_channel.start()
            app.state.wechat_channel = wechat_channel
            # Cache the WeChat conversation ID for fast lookup in the WS handler.
            # If the channel needs re-authentication, there is no active
            # conversation yet.
            app.state.wechat_conversation_id = (
                None
                if wechat_channel._needs_authentication
                else wechat_channel._agent.current_conversation_id
            )
            logger.info(
                "WeChat channel initialized (needs_authentication=%s, conversation=%s)",
                wechat_channel._needs_authentication,
                app.state.wechat_conversation_id,
            )
        except Exception:
            logger.warning("WeChat channel not initialized", exc_info=True)

    # Initialize QQ channel if enabled (AFTER database config is loaded)
    qq_channel = None
    if config.channels.qq.enabled:
        try:
            from thumbelina.channels.qq_channel import QQChannel

            qq_channel = QQChannel(
                config=config.channels.qq,
                agent=agent,
            )
            await qq_channel.start()
            app.state.qq_channel = qq_channel
            logger.info("QQ channel initialized")
        except Exception:
            logger.debug("QQ channel not initialized", exc_info=True)

    yield

    if qq_channel:
        await qq_channel.stop()
    if wechat_channel:
        await wechat_channel.stop()
    if scheduler:
        await scheduler.stop()
    if feedback_repo:
        feedback_repo.close()
    if skill_repo:
        skill_repo.close()
    if composition_engine:
        composition_engine.composition_repo.close()
    if user_profiler:
        user_profiler.profile_repo.close()
    if config_repo:
        config_repo.close()

    # Close QR code manager if it was initialized
    from thumbelina.api.routes.wechat import _qrcode_manager

    if _qrcode_manager is not None:
        await _qrcode_manager.close()

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
    config_path: str | None = None
    if config is None:
        from thumbelina.config.loader import resolve_config_path

        config_path = resolve_config_path()
        config = load_config(config_path)

    app = FastAPI(title="Thumbelina API", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.config_path = config_path

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
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
        required_roles = config.auth.required_roles or None
        app.add_middleware(
            _AuthMiddleware,
            auth_service=auth_service,
            required_roles=required_roles,
        )

    # Global exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle uncaught exceptions."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """Handle value errors."""
        logger.warning("Value error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": "Invalid request"})

    # Health check endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        """Detailed health check."""
        checks = {
            "status": "ok",
            "version": "0.1.0",
        }

        # Check database connectivity
        try:
            memory = app.state.memory_manager
            await memory.repository.ping()
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
            checks["status"] = "degraded"

        return checks

    # Include routers
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(config_routes.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(data.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(plugins.router, prefix="/api/v1")
    app.include_router(wechat.router, prefix="/api/v1")
    app.include_router(qq.router, prefix="/api/v1")
    app.include_router(rag.router, prefix="/api/v1")
    app.include_router(ws_router)

    return app
