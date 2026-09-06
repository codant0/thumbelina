"""FastAPI application factory for Thumbelina API."""

from __future__ import annotations

# Pre-import torch BEFORE any other modules to avoid DLL loading conflicts
# on Windows. When torch is imported later via sentence_transformers →
# transformers, other C extension modules already loaded interfere with
# DLL resolution, causing WinError 127 on shm.dll.
# ImportError covers deployments without the rag extra (torch absent).
try:
    import torch  # noqa: F401, I001
except (OSError, ImportError):
    pass

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.api.routes import (
    attachments,
    chat,
    conversations,
    data,
    fs,
    memory,
    plugins,
    qq,
    rag,
    roles,
    skills,
    tasks,
    todo,
    tools,
    trajectory,
    wechat,
)
from thumbelina.api.routes import (
    config as config_routes,
)
from thumbelina.api.routes.tasks import serialize_task_event
from thumbelina.api.websocket import broadcast_chat_message
from thumbelina.api.websocket import router as ws_router
from thumbelina.channels.base import Channel
from thumbelina.concurrency import per_conversation_lock
from thumbelina.config import AppConfig, load_config
from thumbelina.llm.endpoint_manager import EndpointManager
from thumbelina.llm.factory import create_provider
from thumbelina.llm.preset_manager import PresetManager
from thumbelina.notifications import NotificationManager
from thumbelina.repository.manager import RepositoryManager
from thumbelina.scheduler.dispatcher import DeliveryDispatcher, PromptRunner
from thumbelina.scheduler.events import EventBus, Hook
from thumbelina.scheduler.heartbeat import Heartbeat
from thumbelina.scheduler.models import ScheduledTask, TaskEvent, TaskEventType
from thumbelina.scheduler.scheduler import TaskScheduler
from thumbelina.scheduler.store import TaskStore
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

    Attached only when ``config.auth.secret_key`` is non-empty and valid.
    An empty or invalid secret disables auth so the service can start
    without any auth configuration.
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


def _make_event_log_hook(store: TaskStore) -> Hook:
    """Build the event-log observer: persist every task event (design §5.3).

    Hook-internal failures are logged and swallowed — the EventBus already
    isolates per-hook exceptions, but the hook guards itself too so a broken
    store can never surface outside the event pipeline.
    """

    async def _event_log_hook(event: TaskEvent) -> None:
        try:
            await store.append_event(event)
        except Exception:
            logger.warning("Task event log write failed for %s", event.type.value, exc_info=True)

    return _event_log_hook


def _make_web_push_hook(
    notification_manager: NotificationManager | None,
    scheduler: TaskScheduler | None = None,
) -> Hook:
    """Build the WebPushHook observer (review ruling T7-R1).

    The web channel's delivery IS the event pipeline: every
    :class:`~thumbelina.scheduler.models.TaskEvent` is broadcast to the
    frontend exactly once as a canonical ``{"task_event": …}`` frame (§8.2).
    For ``task.completed`` events the legacy
    ``{"type": "task_completed", …}`` notification frame is additionally
    sent, preserving the pre-existing ``NotificationManager`` behaviour.
    The legacy frame's ``description`` is the task's own description when
    the scheduler can resolve it (the old ``_on_due_task`` behaviour),
    falling back to the event's content snapshot.
    """

    async def _web_push_hook(event: TaskEvent) -> None:
        try:
            await broadcast_chat_message({"task_event": serialize_task_event(event)})
        except Exception:
            logger.warning("Task event WebSocket broadcast failed", exc_info=True)
        if event.type is TaskEventType.COMPLETED and notification_manager is not None:
            description = event.content
            if scheduler is not None:
                try:
                    task = await scheduler.get_task(event.task_id)
                except Exception:
                    task = None
                if task is not None:
                    description = task.description
            try:
                await notification_manager.broadcast(
                    {
                        "type": "task_completed",
                        "task_id": event.task_id,
                        "description": description,
                    }
                )
            except Exception:
                logger.warning("task_completed notification broadcast failed", exc_info=True)

    return _web_push_hook


def _make_prompt_runner(app: FastAPI, repository: RepositoryManager) -> PromptRunner:
    """Build the prompt runner for ``mode="prompt"`` tasks (design §5.4).

    Wired as the ``DeliveryDispatcher(prompt_runner=…)`` callback and, through
    it, as the scheduler's ``on_prompt_task``.  Implements the §5.4 execution
    chain steps 1-5:

    1. 会话归属: ``task.conversation_id`` non-empty and naming an existing
       conversation → run in that conversation; otherwise (missing, blank, or
       deleted) use the dedicated 定时任务 conversation — created lazily once
       per process and cached on ``app.state.scheduler_conversation_id``.
    2. ``per_conversation_lock(cid)`` serializes the turn against HTTP /
       WebSocket / channel rounds on the same conversation (checkpoint safety).
    3. A **clone** of the shared main agent runs the task content with
       ``current_conversation_id`` pinned to ``cid`` — mirroring the
       per-connection clone in the WebSocket handler, so a prompt turn neither
       pollutes the main agent's state nor shares checkpoint state with other
       conversations.  ``agent.run`` persists the user message + reply itself
       (graph.py ``_persist_message``) — nothing is persisted here.
    4. The reply is broadcast as a realtime 对话框 frame: ``channel_message``
       with ``channel="scheduler"`` and ``source="scheduler"`` — the frontend
       appends it to an open conversation or updates the conversation list
       otherwise (same frame the WeChat sync uses).
    5. The reply is returned; the dispatcher additionally sends it through the
       task's IM channel as a channel copy.

    Failures (``agent.run``, repository, …) propagate to the scheduler, which
    settles the FAILED verdict — except the realtime broadcast, which is
    best-effort: the reply already lives in the conversation history, so a
    dead WebSocket client must not fail the whole task.

    Review minor-1 fix: the lazy dedicated-conversation check-and-create is
    guarded by an ``asyncio.Lock`` cached on ``app.state``
    (``scheduler_conversation_lock``).  Without it, several prompt tasks
    firing concurrently in the same poll round would all pass the ``is None``
    check and each call ``create_conversation`` — two "定时任务" conversations
    with the messages split between them.
    """

    async def _run_prompt(task: ScheduledTask) -> str:
        cid: str | None = task.conversation_id or None
        if cid is not None:
            try:
                conversation = await repository.get_conversation(cid)
            except Exception:
                conversation = None
            if conversation is None:
                # Names a deleted / unknown conversation → treat as absent.
                cid = None
        if cid is None:
            # Guard the check-and-create: concurrent fires must agree on one
            # dedicated conversation.  The lock is created once per process
            # (``asyncio.Lock`` is cheap and bound to the event loop).
            lock = getattr(app.state, "scheduler_conversation_lock", None)
            if lock is None:
                lock = asyncio.Lock()
                app.state.scheduler_conversation_lock = lock
            async with lock:
                dedicated = getattr(app.state, "scheduler_conversation_id", None)
                if dedicated is None:
                    dedicated = await repository.create_conversation()
                    app.state.scheduler_conversation_id = dedicated
                cid = dedicated

        async with per_conversation_lock(cid):
            # Clone like the WebSocket/HTTP per-request pattern: isolated
            # conversation state, shared provider/repository/checkpointer.
            isolated = app.state.agent.clone()
            isolated.current_conversation_id = cid
            reply: str = await isolated.run(task.content)

        try:
            await broadcast_chat_message(
                {
                    "channel_message": {
                        "channel": "scheduler",
                        "conversation_id": cid,
                        "user_message": task.content,
                        "response": reply,
                        "source": "scheduler",
                    }
                }
            )
        except Exception:
            logger.warning("Scheduler channel_message broadcast failed", exc_info=True)
        return reply

    return _run_prompt


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""
    config: AppConfig = app.state.config

    repository = RepositoryManager(config.repository.database_url)
    app.state.repository_manager = repository

    # 初始化 LangGraph 检查点存储器（在轮次之间持久化 agent 图状态 /
    # 可变的 LLM 上下文，以会话 id 为键）。检查点是硬性运行时要求：
    # 失败（非 sqlite URL、缺包、打开错误）直接中止启动而不是降级。
    checkpointer_stack = AsyncExitStack()
    from thumbelina.agent.checkpointer import async_checkpointer_from_url

    checkpointer = await checkpointer_stack.enter_async_context(
        async_checkpointer_from_url(config.repository.database_url)
    )
    app.state.checkpointer = checkpointer

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
        from thumbelina.repository.feedback_repo import FeedbackRepository

        feedback_repo = FeedbackRepository(db_url=config.repository.database_url)
        app.state.feedback_repo = feedback_repo
    except Exception:
        logger.warning("Feedback repository not initialized", exc_info=True)

    # Initialize TODO module (independent and pluggable)
    todo_service = None
    if config.todo.enabled:
        try:
            from thumbelina.todo.service import TodoService

            todo_service = TodoService(config.todo.directory)
            await todo_service.init()
        except Exception:
            logger.warning("TODO module not initialized", exc_info=True)
    app.state.todo_service = todo_service

    # Initialize optional subsystems
    skill_engine = None
    skill_repo = None
    try:
        from thumbelina.skills.application import SkillApplicationEngine
        from thumbelina.skills.repository import SkillRepository

        skill_repo = SkillRepository(db_url=config.repository.database_url)
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

            skill_repo = SkillRepository(db_url=config.repository.database_url)
        comp_repo = CompositionRepository(db_url=config.repository.database_url)
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

        subagent_manager = SubagentManager(
            llm_provider=llm_provider,
            tool_timeout=config.tools.tool_timeout,
        )
    except Exception:
        logger.debug("Subagent manager not initialized", exc_info=True)

    # Initialize RAG components
    rag_kb_repo = None
    rag_doc_repo = None
    rag_store_manager = None
    rag_embedding_registry = None
    rag_preload_task: asyncio.Task[None] | None = None
    try:
        # Pre-import torch to avoid DLL loading conflicts on Windows.
        # When torch is imported later (via sentence_transformers → transformers),
        # other C extension modules already loaded can interfere with DLL resolution.
        try:
            import torch  # noqa: F401
        except OSError:
            logger.warning("torch pre-import failed, embedding may not work", exc_info=True)

        from thumbelina.rag.common.db import init_rag_db
        from thumbelina.rag.common.repository import (
            DocumentRepository,
            KnowledgeBaseRepository,
        )
        from thumbelina.rag.embedding.registry import EmbeddingRegistry
        from thumbelina.rag.embedding.store_manager import ChromaStoreManager
        from thumbelina.rag.pipeline.upload_tasks import UploadTaskManager

        # 复用主数据库引擎初始化 RAG 表
        rag_session_factory = init_rag_db(repository.conversation_repository.engine)
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
        app.state.engine = repository.conversation_repository.engine
        app.state.rag_kb_repo = rag_kb_repo
        app.state.rag_doc_repo = rag_doc_repo
        app.state.rag_store_manager = rag_store_manager
        app.state.rag_embedding_registry = rag_embedding_registry
        app.state.rag_upload_tasks = UploadTaskManager()

        logger.info("RAG components initialized")

        # 后台预加载 Embedding 模型：不阻塞启动流程，启动完成后立即在
        # 工作线程中加载本地模型，避免首次上传文件时等待加载。
        async def _preload_embedding_model(registry: EmbeddingRegistry) -> None:
            try:
                await asyncio.to_thread(registry.preload)
                logger.info("Embedding model preloaded in background")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Embedding model preload failed; will load on first use",
                    exc_info=True,
                )

        rag_preload_task = asyncio.create_task(_preload_embedding_model(rag_embedding_registry))
    except Exception:
        logger.debug("RAG not initialized (missing dependencies)", exc_info=True)

    # 通知管理器
    notification_manager = NotificationManager()
    app.state.notification_manager = notification_manager

    # ------------------------------------------------------------------
    # 事件管线装配（设计 §5.3）：TaskStore → EventBus → TaskScheduler →
    # 观察者 hooks（event_log + web_push，订阅全部 TaskEventType）→
    # recover()。hooks 必须在任何事件产生之前订阅完毕；web_push 需要
    # scheduler 引用解析存量兼容帧的 description，故构造先于订阅。
    # config.scheduler.enabled=False 或任一步失败时整体降级：相关对象置
    # None，任务路由判空返回 503/空列表，服务器照常启动（§11）。
    # 调度循环的启动（DeliveryDispatcher 接线 + Heartbeat）在本文件下方
    # 渠道初始化之后执行——Dispatcher 的渠道表需要 app.state.wechat_channel
    # / qq_channel，而渠道对象要等 agent 构造完成后才可用。
    # ------------------------------------------------------------------
    task_store: TaskStore | None = None
    task_event_bus: EventBus | None = None
    task_scheduler: TaskScheduler | None = None
    if config.scheduler.enabled:
        try:
            task_store = TaskStore(repository.conversation_repository.engine)
            task_event_bus = EventBus()

            task_scheduler = TaskScheduler(
                store=task_store,
                bus=task_event_bus,
                check_condition=None,
                config=config.scheduler,
            )

            event_log_hook = _make_event_log_hook(task_store)
            web_push_hook = _make_web_push_hook(notification_manager, task_scheduler)
            for event_type in TaskEventType:
                task_event_bus.subscribe(event_type, event_log_hook)
                task_event_bus.subscribe(event_type, web_push_hook)

            await task_scheduler.recover()
            logger.info("Task scheduler initialized (store + event pipeline)")
        except Exception:
            logger.warning("Task scheduler not initialized", exc_info=True)
            task_store = None
            task_event_bus = None
            task_scheduler = None

    app.state.task_store = task_store
    app.state.task_event_bus = task_event_bus
    app.state.task_scheduler = task_scheduler

    # Initialize Markdown分层记忆子系统(阶段三 §9.3 优雅降级)。
    # 失败或 disabled 时 app.state.memory_service = None,路由 503,
    # Agent 注入/抽取整体禁用,服务照常启动。
    memory_service = None
    if config.memory.enabled:
        try:
            from pathlib import Path

            from thumbelina.memory.service import MemoryService

            memory_directory = Path(config.memory.directory)
            memory_service = MemoryService(
                directory=memory_directory,
                categories=config.memory.categories,
                max_full_tokens=config.memory.max_full_tokens,
                max_entries=config.memory.max_entries,
                max_total_bytes=config.memory.max_total_bytes,
            )
            await memory_service.init()
            app.state.memory_service = memory_service
            logger.info(
                "Memory module initialized at %s (categories=%s)",
                memory_directory,
                config.memory.categories,
            )
        except Exception:
            logger.warning("Memory module not initialized", exc_info=True)
            app.state.memory_service = None
    else:
        app.state.memory_service = None

    # Initialize conversation auto-namer (shares the active LLM provider)
    from thumbelina.analysis.namer import ConversationNamer

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
        tools=get_all_tools(search_config=config.tools),
        repository_manager=repository,
        request_timeout=config.llm.request_timeout,
        tool_timeout=config.tools.tool_timeout,
        skill_engine=skill_engine,
        subagent_manager=subagent_manager,
        scheduler=task_scheduler,
        composition_engine=composition_engine,
        conversation_namer=conversation_namer,
        role=config.llm.role,
        checkpointer=checkpointer,
        context_config=config.context,
        context_window_tokens=config.llm.context_window_tokens,
        memory_service=getattr(app.state, "memory_service", None),
        memory_config=config.memory,
    )
    app.state.agent = agent

    # 子 agent 只读工具集:仅感知类(读/搜/取/记忆读),避免嵌套派发
    # (collaboration)、写/执行副作用与通信通道;空集时 manager 自动退回
    # 无工具单轮模式。工具在会话 ContextVar 继承下与主 agent 同工作区。
    if subagent_manager is not None:
        from thumbelina.tools.base import ToolCategory

        subagent_manager.set_tools(
            [
                t
                for t in agent.tools
                if getattr(t, "category", None) == ToolCategory.PERCEPTION
            ]
        )
    # 暴露 memory_extractor 引用给热切换路径(§9.3);agent 自身的
    # memory_extractor 由 swap_provider 同步,此处仅作冗余入口。
    app.state.memory_extractor = getattr(agent, "memory_extractor", None)

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

    config_repo = ConfigRepository(db_url=config.repository.database_url)
    app.state.config_repo = config_repo

    # Initialize LLM endpoint manager backed by the config repository
    endpoint_manager = EndpointManager(config_repo=config_repo)
    app.state.endpoint_manager = endpoint_manager

    # Import YAML config to database on first startup (if DB is empty)
    from thumbelina.config.loader import import_yaml_to_db

    config_path = getattr(app.state, "config_path", None)
    try:
        if await config_repo.is_empty():
            imported = import_yaml_to_db(config_path, config.repository.database_url)
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
        memory_extractor=getattr(app.state, "memory_extractor", None),
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
                attachments: list[dict[str, Any]] | None = None,
            ) -> None:
                # attachments:入站微信图片的附件 refs(设计 §2),前端并入
                # 乐观用户消息;纯文本轮为 None。
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

            wechat_channel = WeChatChannel(
                config=config.channels.wechat,
                agent=agent,
                on_message_callback=_on_wechat_message,
                # 惰性引用 app.state：让微信消息路径能像 HTTP/WebSocket
                # 一样解析会话端点与上下文窗口（#8）。
                runtime=SimpleNamespace(app=app),
            )
            await wechat_channel.start()
            app.state.wechat_channel = wechat_channel
            agent.register_channel("wechat", wechat_channel)
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
            agent.register_channel("qq", qq_channel)
            logger.info("QQ channel initialized")
        except Exception:
            logger.debug("QQ channel not initialized", exc_info=True)

    # ------------------------------------------------------------------
    # 启动调度循环（设计 §5.3 后半段）：DeliveryDispatcher 作为唯一交付
    # 入口挂到 on_due_task 回调上（绝不 bus.subscribe，防双触发），
    # Heartbeat 开始周期巡检。渠道表从 app.state 取，缺失的渠道不进
    # dict——未启用渠道的任务交付期产出 task.failed，服务不降级（§5.3）。
    # ------------------------------------------------------------------
    task_dispatcher: DeliveryDispatcher | None = None
    task_heartbeat: Heartbeat | None = None
    if task_scheduler is not None:
        try:
            channels: dict[str, Channel] = {}
            wechat_channel_ref = getattr(app.state, "wechat_channel", None)
            if wechat_channel_ref is not None:
                channels["wechat"] = wechat_channel_ref
            qq_channel_ref = getattr(app.state, "qq_channel", None)
            if qq_channel_ref is not None:
                channels["qq"] = qq_channel_ref

            # §5.4 prompt 模式：run_prompt 闭包（会话归属 → per-conversation 锁
            # → agent.clone().run → 对话框实时广播），dispatcher 负责频道副本。
            prompt_runner = _make_prompt_runner(app, repository)
            task_dispatcher = DeliveryDispatcher(
                channels=channels,
                bus=task_event_bus,
                prompt_runner=prompt_runner,
            )
            await task_scheduler.start(
                on_due_task=task_dispatcher.on_due_task,
                on_prompt_task=task_dispatcher.on_prompt_task,
            )
            task_heartbeat = Heartbeat(task_scheduler, task_event_bus, config.scheduler)
            await task_heartbeat.start()
            logger.info("Task scheduler loop and heartbeat started")
        except Exception:
            logger.warning("Task scheduler loop not started", exc_info=True)
            task_dispatcher = None
            task_heartbeat = None

    app.state.task_dispatcher = task_dispatcher
    app.state.task_heartbeat = task_heartbeat

    yield

    # 取消尚未完成的 Embedding 预加载任务（底层工作线程会继续完成加载，
    # 但不再阻塞关闭流程之后的清理逻辑）
    if rag_preload_task is not None and not rag_preload_task.done():
        rag_preload_task.cancel()

    if qq_channel:
        await qq_channel.stop()
    if wechat_channel:
        await wechat_channel.stop()
    if task_heartbeat:
        await task_heartbeat.stop()
    if task_scheduler:
        await task_scheduler.stop()
    if feedback_repo:
        feedback_repo.close()
    if skill_repo:
        skill_repo.close()
    if composition_engine:
        composition_engine.composition_repo.close()
    if config_repo:
        config_repo.close()

    # Close QR code manager if it was initialized
    from thumbelina.api.routes.wechat import _qrcode_manager

    if _qrcode_manager is not None:
        await _qrcode_manager.close()

    # 关闭 LangGraph 检查点存储器的连接（aiosqlite）
    await checkpointer_stack.aclose()

    repository.close()


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
    # 初始化日志系统（必须在其他模块导入之前）
    from thumbelina.logging_config import setup_logging

    setup_logging()

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
        # 同时暴露给路由层,供 search/read 等端点做路由级限流
        # (与全局 middleware 同一实例,按客户端 IP 计数)。
        app.state.rate_limiter = limiter

    # Add auth middleware when a secret key is configured.
    # An invalid secret (e.g. too short) degrades gracefully: the service
    # still starts, with auth disabled and a warning logged.
    if config.auth.secret_key:
        try:
            auth_service = AuthService(secret_key=config.auth.secret_key)
        except ValueError as exc:
            logger.warning("Auth disabled at startup: %s", exc)
        else:
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
            repository = app.state.repository_manager
            await repository.conversation_repository.ping()
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
            checks["status"] = "degraded"

        return checks

    # Include routers
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(config_routes.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(fs.router, prefix="/api/v1")
    app.include_router(roles.router, prefix="/api/v1")
    app.include_router(data.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(plugins.router, prefix="/api/v1")
    app.include_router(wechat.router, prefix="/api/v1")
    app.include_router(qq.router, prefix="/api/v1")
    app.include_router(rag.router, prefix="/api/v1")
    app.include_router(todo.router, prefix="/api/v1")
    app.include_router(memory.router, prefix="/api/v1")
    app.include_router(tools.router, prefix="/api/v1")
    app.include_router(trajectory.router, prefix="/api/v1")
    app.include_router(attachments.router, prefix="/api/v1")
    app.include_router(ws_router)

    return app
