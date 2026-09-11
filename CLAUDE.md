# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Thumbelina is a personal AI agent assistant built with **FastAPI** (backend) and **LangGraph** (agent framework), with a **React** frontend. It features a model-agnostic LLM provider layer, conversation memory with skill extraction, skill composition, a Markdown-based layered memory subsystem, sub-agent orchestration, task scheduling with conditional triggers, a plugin system with sandbox and dependency resolution, QQ Bot and WeChat (via weixin-bot) channels, and built-in tools.

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
    ├── /api/v1/tasks     → TaskScheduler.list_tasks() / add_task() (POST; once or cron)
    ├── /api/v1/tasks/{id}/cancel → TaskScheduler.cancel_task()
    ├── /api/v1/tasks/{id}/pause|resume → TaskScheduler.pause_task() / resume_task() (cron only)
    ├── /api/v1/tasks/events → TaskStore.list_events() (newest-first lifecycle log)
    ├── /api/v1/tasks/scheduler/status → Heartbeat aliveness snapshot
    ├── /api/v1/subagents → SubagentManager.list()
    ├── /api/v1/subagents/{id}/cancel → SubagentManager.cancel()
    ├── /api/v1/skills    → SkillRepository.list_all()
    ├── /api/v1/skills/stats → SkillRepository + analytics
    ├── /api/v1/compositions → CompositionRepository.list_all()
    ├── /api/v1/feedback  → FeedbackRepository CRUD + stats
    ├── /api/v1/memory/*  → MemoryService (index/entries/search/read/refresh/status)
    ├── /api/v1/data/export|delete → RepositoryManager export/delete + MemoryService export/clear
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
- **Memory**: `_get_memory_context()` injects the L0 memory index summary as a SystemMessage every turn (prefixed with a "reference data, not instructions" disclaimer and stripped of Markdown link syntax); `_make_memory_tools()` exposes `search_memory` (L0 n-gram retrieval), `read_memory` (L1/L2 layered read), and `remember` (single-turn quota ≤ 3) tools
- **Sub-agents**: `_make_subagent_tools()` exposes `create_subagent` and `list_subagents` tools
- **Scheduler**: `_make_scheduler_tools()` exposes `schedule_task` (one-off natural-language time or recurring cron expression, optional delivery channel) and `list_scheduled_tasks` tools, backed by the event-driven scheduler v2 (`scheduler/`)
- **Compositions**: `_make_composition_tools()` exposes `create_skill_composition`, `list_skill_compositions`, `execute_skill_composition` tools

### LLM Provider Abstraction (`llm/`)

`LLMProvider` ABC with `chat()`, `stream()`, `chat_sync()` methods. Concrete providers: `OpenAIProvider`, `AnthropicProvider`, `OllamaProvider` -- all wrapping LangChain chat models. `create_provider(name)` factory with lazy imports.

### Storage Layer (`repository/`)

SQLAlchemy ORM (`Conversation`, `Message`, `SkillRecord`, `CompositionRecord`, `FeedbackRecord`) with `ConversationRepository` wrapping sync calls via `asyncio.to_thread`. `RepositoryManager` adds validation (100KB content limit) and a `search()` method for hybrid keyword + semantic search. Additional modules:
- `SearchEngine` — keyword, semantic, and hybrid search
- `vector/` — ChromaDB vector store
- `feedback_repo.py` — `FeedbackRepository` for user ratings with skill score adjustment

### Shared File Store (`filestore/`)

Reusable file-backed storage primitives shared by `todo/`, `memory/`, and any future Markdown-file service.
- `atomic.py` — `write_text_atomic` (temp file + best-effort `fsync` + `os.replace`, `.tmp` cleanup on failure), `read_text` (missing → empty), `safe_unlink`, `cleanup_tmp`, `ensure_dir`
- `locks.py` — `FileLocks`: a per-key (file path) `asyncio.Lock` table with `locked(*keys)` acquiring multiple keys in stable sorted order (deadlock-safe), so each file locks independently while composite operations hold a fixed extra key

### Memory Subsystem (`memory/`)

Markdown file-system-backed layered memory (default directory `MEMORY/`). Three tiers loaded on demand: **L0** — `index.md`, an auto-generated derived index of one-line summaries (regenerated on every write, never hand-edited); **L1** — the `## 概览` (overview) section of each `<category>/<slug>.md` for planning decisions; **L2** — the `## 全文` (full text) section, loaded only when needed and truncated at `max_full_tokens`. Concurrency is handled by the shared `filestore.FileLocks` gate: single-entry reads lock their `<category>/<slug>.md`, while scan/index-maintaining operations lock the fixed `index.md` key; composite writes (entry + index rebuild) take both in stable order. LLM calls happen outside the lock. Writes go through the shared `filestore.write_text_atomic` (`os.replace` + best-effort `fsync`) with `.tmp` cleanup on startup; all paths are validated against traversal and symlink escape. Guardrails: `max_entries`, `max_total_bytes`, `max_full_tokens`.

- `models.py` — `MemoryEntry`, `MemoryIndex`, `MemoryHit`, `UpdateDecision`
- `parser.py` — document parsing (title, `>` metadata, `## 概览`/`## 全文` sections), `build_index()` generates `index.md`
- `paths.py` — path validation (`_resolve`, category/slug whitelist regex + `resolve()`/`is_relative_to()` double assertion)
- `service.py` — `MemoryService`: `load_index` / `read_overview` / `read_full` / `search_index` / `update_memory` / `delete_memory` / `list_entries` / `export_all` / `clear_all`; per-file + fixed-index locking + residual cleanup
- `search.py` — character 2-gram Jaccard/Dice scoring + exact-token overlap weighting for L0 triage; reuses `estimate_tokens` for the `index_token_cap` full-vs-top-K decision
- `extractor.py` — `MemoryExtractor`: LLM extraction/rewrite/delete (NEW/UPDATE/DELETE/NOOP) with whole-document rewrite, JSON-fence-tolerant parsing, injection-phrase filtering, SimHash dedup (lazy import); triggered asynchronously after each user-message turn
- `tools.py` — `search_memory` / `read_memory` / `remember` agent tools (`remember` enforces a single-turn quota ≤ 3 and goes through the same extractor write path)
- Agent integration (`agent/graph.py`): `_get_memory_context()` replaces the former user-profiler injection seam; `swap_provider` re-targets the extractor's LLM on hot-swap
- API routes (`api/routes/memory.py`): `GET /index`, `GET /entries`, `GET /search?q=`, `GET /{category}/{slug}?depth=`, `POST /refresh`, `GET /status`; `require_roles()` + `RateLimiter`; 503 when the service is unavailable. `/api/v1/data/export` includes a `memory` field; `/api/v1/data/all` also clears memory.

### Analysis Services (`analysis/`)

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

### Permission Modes (`tools/permissions.py`)

Single source of truth for the five-mode capability ladder and gate decisions (spec `2026-09-06-permission-modes-design.md` §3/§4/§5). Enforced at tool execution, **not** as a prompt convention.

- `PermissionMode` (StrEnum) + `LADDER` (strictly increasing order: `READ_ONLY` → `WORKSPACE_WRITE` → `GLOBAL_WRITE` → `FULL_ACCESS` → `AUTO`)
- `PermissionDecision` (verdict: `allow` / `confirm` / `deny`; risk: `normal` / `dangerous`; `auto_allowed` flag for auto-mode auto-passes)
- ContextVar injection (default fail-closed): `set_permission_mode` / `get_permission_mode`, `set_approval_context` / `has_approver`
- `effective_mode(mode, *, unattended, has_workspace)` — unattended ceiling is `WORKSPACE_WRITE` (with workspace) / `READ_ONLY` (without); `AUTO` is explicitly exempt
- Shell classifier moved up from `tools/execution.py` (`POSIX_DANGEROUS`, `WINDOWS_DANGEROUS`, `POSIX_CONFIRM`, `WINDOWS_CONFIRM`, write-piercing patterns, `_rm_root_patterns`) — `RunShellTool` / `WriteFileTool` `security_review` delegate here so rules cannot drift between the gate and the tool layer
- `normalize_shell_command` — line-continuation fold + comment strip + whitespace collapse, used both by the classifier (prevent `rm -rf \n/` bypass) and the approval-card preview (spec §4.6)

**The gate lives in `agent/graph.py::_tool_node_node` — its first line of body, before any `trajectory_recorder` / `get_stream_writer` / `tool_start` emission.** Replay idempotency (verdict stored in the trajectory payload, gate re-evaluated on resume) requires the gate to precede those side effects (review P2-1). The gate itself does not enter `try/except Exception`: `GraphInterrupt(GraphBubbleUp(Exception))` is swallowed by that pattern (review T5). Resume must reuse the local `config` from the same `stream()` / `run()` scope so the thread_id stays stable (review T6).

**Entry-point matrix** — each entry decides whether it has an approver and what the unattended ceiling is. `apply_conversation_runtime` is the single helper that wires `set_workspace` + `set_permission_mode` + `set_approval_context` for a request; it is called in only three places (HTTP chat route, WS `_run_generation`, WeChat channel), so every other entry must either call it explicitly or accept the fail-closed default (`READ_ONLY`, no approver).

| Entry | File / call site | Approver | Unattended ceiling | Mode wired |
|---|---|---|---|---|
| HTTP chat route | `api/routes/chat.py::apply_conversation_runtime` | None (one-shot) | `READ_ONLY` / `WORKSPACE_WRITE` | per request |
| WebSocket `_run_generation` | `api/websocket.py` | `PermissionRequestCard` via WS broker | n/a (interactive) | per session |
| WeChat channel | `channels/wechat_channel.py` (via `apply_conversation_runtime`) | None | `READ_ONLY` / `WORKSPACE_WRITE` | per session |
| QQ channel | `channels/qq_channel.py` | **None** | `READ_ONLY` | not yet wired (fail-closed default applies) |
| Scheduler `_run_prompt` | `api/app.py` | **None** | `READ_ONLY` / `WORKSPACE_WRITE` | not yet wired (fail-closed default applies) |
| CLI `_run_chat_session` (TTY) | `cli/chat.py` | CLI `_approval_handler` (y/N prompt) | n/a (interactive) | `FULL_ACCESS` + `isatty()` |
| CLI `_run_chat_session` (non-TTY / piped) | `cli/chat.py` | **None** | `READ_ONLY` / `WORKSPACE_WRITE` | `FULL_ACCESS` set, but `approval_handler=None` → confirm calls denied |

**Sub-agent whitelist expansion rule.** `cli/chat.py` and `api/app.py` both call `SubagentManager.set_tools(...)` to restrict the worker's tool surface to `ToolCategory.PERCEPTION`. Sub-agents have **no approver**, so adding a write / execution tool to that whitelist must be accompanied by a corresponding entry in `evaluate_tool_call` (gate matrix) — otherwise the sub-agent will bypass the gate entirely. (See `subagents/manager.py` `_run_tool_loop`.)

### Frontend (`frontend/src/`)

React 19 + TypeScript + Vite 8. Pages: Chat, Tasks, Memory, Dream, Settings, Plugins, Channels. Three themes (dark/light/warm). i18n via `LocaleContext` (English + Chinese).

- `hooks/useWebSocket.ts` — WebSocket hook for streaming chat
- `components/StatusBar/` — 状态栏栏目协议（`StatusBarItem`）与容器/外壳；`ContextUsageItem` 在聊天输入工具栏末尾（与思考模式/默认角色/知识库同行右侧）展示上下文占用估算，只读展示、不影响对话
- `lib/estimateTokens.ts` — 前端 token 估算（CJK≈2/字，其余≈0.25，与后端 `estimate_tokens` 同口径）+ `parseContextWindow`
- `api/` — API client modules (`conversations.ts`, `llmConfig.ts`)
- `types/chat.ts` — TypeScript interfaces
- `i18n/` — locale files in `locales/en.json` and `locales/zh-CN.json`

### Other Modules

- **tools/**: Built-in tools (file operations, web requests, shell commands, data processing — JSON/CSV/text analysis/regex search)
- **scheduler/**: event-driven scheduler v2 — `TaskScheduler` (cron/once scheduling, pause/resume, restart recover), `EventBus` with task lifecycle hooks, `TaskStore` (SQLAlchemy persistence for scheduled tasks/events, degrades to in-memory on failure), `Heartbeat` (aliveness kick, zombie cleanup, missed-task handling, log pruning), `DeliveryDispatcher` (per-channel delivery: web/wechat/qq), `CronTrigger` (croniter), `TimeParser` (dateparser + Chinese recurring patterns), conditional triggers with `check_condition` callback
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

Example config in `thumbelina.yaml.example`. Copy to `thumbelina.yaml` and edit with your settings. LLM provider defaults to `openai/gpt-4o`. The repository database (`repository.database_url`) defaults to `sqlite:///thumbelina.db`. API key resolved from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` env vars.

Channel configuration: `channels.qq` (qq-botpy SDK) and `channels.wechat` (weixin-bot protocol) are disabled by default. Enable by setting `enabled: true` and providing required credentials. WeChat channel follows the [weixin-bot protocol specification](https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md).

Memory configuration: the `memory:` section configures the Markdown layered memory subsystem (directory, category whitelist, injection budget `inject_top_k` / `index_token_cap`, guardrails `max_entries` / `max_total_bytes` / `max_full_tokens`, `extract.*` for the background LLM extractor, `tools.enabled` for exposing the memory tools). See `thumbelina.yaml.example` for the full annotated schema. When `enabled: false` or initialization fails, the server still starts and memory routes return 503.
