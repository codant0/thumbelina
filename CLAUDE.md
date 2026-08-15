# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Thumbelina is a personal AI agent assistant built with **FastAPI** (backend) and **LangGraph** (agent framework), with a **React** frontend. It features a model-agnostic LLM provider layer, conversation memory with skill extraction, skill composition, user profiling, sub-agent orchestration, task scheduling with conditional triggers, a plugin system with sandbox and dependency resolution, QQ Bot and WeChat (via weixin-bot) channels, and built-in tools.

## Common Commands

### Backend (Python)

```bash
pip install -e ".[dev]"          # Install in dev mode
pip install -e ".[dev,rag]"      # Include RAG dependencies (llama-index embeddings/LLMs)
pytest                           # Run all tests
pytest tests/test_agent/         # Run tests for a specific module
pytest tests/test_api/test_chat.py -x -q  # Run single file, stop on first failure
ruff check src/ tests/           # Lint
ruff format src/ tests/          # Format
mypy src/                        # Type check (strict mode)
thumbelina                       # Launch CLI interactive chat
thumbelina-serve                 # Start API server on port 8000
python start_dev.py              # Start both backend (8000) and frontend (5173) together
```

### Frontend (React/TypeScript)

```bash
cd frontend
npm install
npm run dev          # Vite dev server
npm run test         # Vitest (single run)
npm run test:watch   # Vitest (watch mode)
npm run lint         # ESLint
npm run build        # TypeScript check + Vite build
```

## Architecture

### Request Flow

```
Frontend (React/Vite) --WebSocket/HTTP--> FastAPI (api/app.py)
    ├── /api/v1/chat      → api/routes/chat.py → ThumbelinaAgent.run()
    ├── /ws/chat          → api/websocket.py   → ThumbelinaAgent.run() (streaming)
    ├── /api/v1/conversations → CRUD on RepositoryManager
    ├── /api/v1/conversations/search/{query} → RepositoryManager.search()
    ├── /api/v1/tasks     → TaskScheduler.list_tasks()
    ├── /api/v1/tasks/{id}/cancel → TaskScheduler.cancel_task()
    ├── /api/v1/subagents → SubagentManager.list()
    ├── /api/v1/subagents/{id}/cancel → SubagentManager.cancel()
    ├── /api/v1/skills    → SkillRepository.list_all()
    ├── /api/v1/skills/stats → SkillRepository + analytics
    ├── /api/v1/compositions → CompositionRepository.list_all()
    ├── /api/v1/feedback  → FeedbackRepository CRUD + stats
    ├── /api/v1/data/export|delete → RepositoryManager export/delete
    ├── /api/v1/user/profile → UserProfiler.get_user_context()
    ├── /api/v1/plugins   → PluginManager + sandbox report
    ├── /api/v1/config    → RuntimeConfigManager
    ├── /api/v1/config/llm → Hot-swap LLM provider
    ├── /api/v1/config/channels/{name} → Hot-swap channel config
    ├── /api/v1/wechat/*  → WeChatChannel (iLink API)
    ├── /api/v1/qq/*      → QQChannel
    └── /health
```

### Core Agent Loop (`agent/`)

`ThumbelinaAgent` builds a LangGraph `StateGraph` with an "agent" node (calls LLM) and optionally a "tools" node. The `should_continue` edge function checks for tool calls. The agent supports `run()` (single response) and `stream()` (yielding chunks).

Integrated subsystems:
- **Skills**: `_get_skill_context()` injects matching skills as SystemMessage
- **User Profiler**: `_get_user_context()` injects user preferences as SystemMessage
- **Sub-agents**: `_make_subagent_tools()` exposes `create_subagent` and `list_subagents` tools
- **Scheduler**: `_make_scheduler_tools()` exposes `schedule_task` and `list_scheduled_tasks` tools
- **Compositions**: `_make_composition_tools()` exposes `create_skill_composition`, `list_skill_compositions`, `execute_skill_composition` tools

### LLM Provider Abstraction (`llm/`)

`LLMProvider` ABC with `chat()`, `stream()`, `chat_sync()` methods. Concrete providers: `OpenAIProvider`, `AnthropicProvider`, `OllamaProvider` -- all wrapping LangChain chat models. `create_provider(name)` factory with lazy imports.

### Storage Layer (`repository/`)

SQLAlchemy ORM (`Conversation`, `Message`, `SkillRecord`, `CompositionRecord`, `FeedbackRecord`, `UserProfile`, `UserPreference`) with `ConversationRepository` wrapping sync calls via `asyncio.to_thread`. `RepositoryManager` adds validation (100KB content limit) and a `search()` method for hybrid keyword + semantic search. Additional modules:
- `SearchEngine` — keyword, semantic, and hybrid search
- `vector/` — ChromaDB vector store
- `feedback_repo.py` — `FeedbackRepository` for user ratings with skill score adjustment
- `user_profile.py` + `user_profile_repo.py` — `UserProfile` and `UserPreference` models

### Analysis Services (`analysis/`)

- `UserProfiler` — analyzes conversations to build user preference profiles
- `TitleSummarizer` — LLM-based short conversation summarization (naming-style summaries; context compression uses `agent/compression/` instead)
- `ConversationNamer` — auto-generates short conversation titles from early user messages

### Channels (`channels/`)

- `Channel` ABC — `start()`, `stop()`, `send_message()`, `set_handler()`
- `QQChannel` — wraps `botpy.Client` (qq-botpy SDK), runs in daemon thread, handles guild/group/C2C messages
- `WeChatChannel` — direct iLink long-polling via [weixin-bot](https://github.com/epiral/weixin-bot) protocol, QR code login, `context_token` management
- `config.py` — `QQChannelConfig`, `WeChatChannelConfig`, `ChannelsConfig`

### Skills System (`skills/`)

- `SkillExtractor` — LLM-based extraction from conversations
- `SkillRepository` — SQLAlchemy persistence with CRUD + search
- `SkillApplicationEngine` — keyword + LLM matching, integrated with `FeedbackRepository` for score adjustment
- `CompositionEngine` — skill workflow chaining, LLM-assisted suggestion

### Plugin System (`plugins/`)

- `PluginManager` — register/unregister/list by type (TOOL/SKILL/CHANNEL/PROVIDER)
- `sandbox.py` — `PluginSandbox` with AST-based static analysis, module whitelist/blacklist, resource limits
- `sandboxed_loader.py` — `SandboxedPluginLoader` with advisory/strict modes
- `dependency.py` — `PluginMetadata` parsing (docstring + dict formats), semver version comparison
- `resolver.py` — `DependencyResolver` with Kahn's topological sort, circular/missing dep detection

### Sub-agents (`subagents/`)

- `SubagentManager` — create/list/cancel with concurrency limits
- `MonitorAgent` — interval-based monitoring loop
- `WorkerAgent` — task execution with progress tracking
- `MessageQueue` — async inter-agent messaging
- `SharedState` — lock-protected KV store

### Frontend (`frontend/src/`)

React 19 + TypeScript + Vite 8. Pages: Chat, Tasks, Memory, Dream, Settings, Plugins, Channels. Three themes (dark/light/warm). i18n via `LocaleContext` (English + Chinese).

- `hooks/useWebSocket.ts` — WebSocket hook for streaming chat
- `api/` — API client modules (`conversations.ts`, `llmConfig.ts`)
- `types/chat.ts` — TypeScript interfaces
- `i18n/` — locale files in `locales/en.json` and `locales/zh-CN.json`

### Other Modules

- **tools/**: Built-in tools (file operations, web requests, shell commands, data processing — JSON/CSV/text analysis/regex search)
- **scheduler/**: `TaskScheduler` (in-memory task management), `TimeParser` (dateparser + Chinese recurring patterns), conditional triggers with `check_condition` callback
- **notifications/**: `NotificationManager` — WebSocket broadcast for task completion and system events
- **security/**: `AuthService` (JWT HS256 via PyJWT, min 32-byte key), `RateLimiter` (sliding window with auto-cleanup), role-based access control via `required_roles` config and per-route `require_roles()` helper
- **backup/**: `BackupManager` (JSON file backups with metadata envelope, UUID-validated paths)

## Key Patterns

- **Source layout**: `src/thumbelina/` (PEP 621 with hatchling). Tests mirror source: `tests/test_<module>/`.
- **Async**: All public APIs are async. Sync SQLAlchemy wrapped with `asyncio.to_thread`. Pure-memory modules use async for interface consistency.
- **Testing**: `pytest` + `pytest-asyncio` + `httpx`. API tests use a shared `conftest.py` fixture that creates a `TestClient` with mocked `ThumbelinaAgent` and `RepositoryManager` injected via lifespan.
- **Ruff rules**: E, F, I, N, W, UP. Line length 100. Target Python 3.11.
- **Mypy**: Strict mode enabled.
- **Streaming**: WebSocket responses stream token-by-token via `ThumbelinaAgent.stream()`.
- **Optional dependencies**: `botpy` (QQ SDK) and ChromaDB are imported lazily with `try/except ImportError` guards.
- **Lazy LLM fallback**: `_LazyLLMProvider` allows the server to start without LLM credentials — the agent returns a helpful message until a real provider is configured.
- **Hot-swap**: LLM provider can be replaced at runtime via `ThumbelinaAgent.swap_provider()` without rebuilding the compiled LangGraph graph. Endpoint and preset management via `EndpointManager`/`PresetManager`.
- **Agent isolation**: Each WebSocket connection gets a cloned agent instance with independent conversation state.
- **Config substitution**: YAML config supports `${VAR}` environment variable substitution.
- **Graceful degradation**: All subsystems (skills, compositions, subagents, scheduler, plugins, channels) initialize with try/except guards — the server degrades gracefully if any are unavailable.
- **Config priority** (highest to lowest): Database overrides (via API) > Environment variables (`THUMBELINA_*` with `__` nesting) > YAML file (`thumbelina.yaml`) > Defaults.

## Configuration

Example config in `thumbelina.yaml.example`. Copy to `thumbelina.yaml` and edit with your settings. LLM provider defaults to `openai/gpt-4o`. Memory defaults to `sqlite:///thumbelina.db`. API key resolved from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` env vars.

Channel configuration: `channels.qq` (qq-botpy SDK) and `channels.wechat` (weixin-bot protocol) are disabled by default. Enable by setting `enabled: true` and providing required credentials. WeChat channel follows the [weixin-bot protocol specification](https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md).
