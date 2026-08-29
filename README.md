# Thumbelina

An AI-powered personal assistant built with [FastAPI](https://fastapi.tiangolo.com/) and [LangGraph](https://langchain-ai.github.io/langgraph/), featuring multi-provider LLM support, conversation memory with skill extraction, sub-agent orchestration, and a React-based chat UI.

[中文文档](README_CN.md)

## Features

- **Multi-Provider LLM** — Pluggable support for OpenAI, Anthropic, and Ollama via a unified abstraction layer, with named presets for quick switching and one-click connectivity testing
- **LLM Preset Management** — Save multiple LLM configurations (provider, base URL, API key, model) with custom names and activate any preset with one click
- **LLM Connection Test** — Three-level connectivity verification (network reachability → auth validity → service availability) for any provider endpoint
- **DeepSeek API Support** — Compatible via `openai` provider with graceful fallback for `/models` endpoint
- **Agent Core** — LangGraph-powered agent loop with tool calling and conditional routing
- **Role Prompts** — Role personas stored as files under `prompts/roles/` (built-in: assistant / coder), injected as the system prompt; supports a global default role and per-conversation switching in the Web UI
- **Coder Mode & Workspace** — Conversations are created with `mode: chat | coder`; coder conversations bind to an absolute workspace directory (enforced boundary for the file/shell tools, invisible to the LLM), chat conversations may not set a workspace. Browse candidate directories with `GET /api/v1/fs/dirs`; dedicated Coder page with workspace picker in the Web UI. When the workspace is a git repository the status bar shows the current branch and lets you switch branches in one click (server-side validated, refreshed via WebSocket broadcast)
- **Thinking Mode** — Per-conversation reasoning/thinking toggle with effort level, persisted per conversation and set via `PUT /api/v1/conversations/{id}/thinking`
- **Built-in Tools** — File operations, web requests, web search (Tavily / DuckDuckGo), shell commands, and data processing (JSON/CSV/text analysis/regex search). Tools are organized into five categories — perception / execution / user communication / collaboration / event-trigger — and execution tools carry a security review and result self-verification step
- **RAG (Retrieval-Augmented Generation)** — Document ingestion, chunking, embedding (HuggingFace via llama-index), vector retrieval (ChromaDB), and context-aware indexing pipeline
- **Conversation Storage** — Persistent storage (SQLite) with keyword search, LLM-generated summaries, and auto-naming for new conversations
- **Semantic Search** — Vector-based semantic search via ChromaDB, with hybrid keyword + semantic fallback
- **Skill Extraction & Integration** — Automatically extracts reusable skills from conversations and applies them in the agent loop
- **Skill Composition** — Chain multiple skills into workflows, with LLM-assisted suggestion
- **Markdown Layered Memory** — File-system-backed memory stored as human-auditable Markdown under `MEMORY/`. Three-tier on-demand loading (L0 auto-generated index of one-line summaries / L1 overview / L2 full text); `MemoryExtractor` runs in the background after each user turn to extract/rewrite/delete memories (NEW/UPDATE/DELETE/NOOP); the agent injects the L0 index summary every turn (treated as reference data, never instructions) and exposes `search_memory` / `read_memory` / `remember` tools; zero embedding/vector dependency; CRUD + search via `/api/v1/memory/*` routes
- **Sub-Agent System** — Parallel task execution with monitor/worker agents, inter-agent messaging and shared state
- **Task Scheduler** — Natural language time parsing (Chinese & English) with conditional triggers and notification broadcast
- **TODO List & Quick Notes** — Local Markdown-based todo list and quick notes (`TODO/todolist.md` + `TODO/notes.md`), with per-item Markdown remarks (stored as blockquotes), grouping by top-level Markdown heading with group-filter cards, manageable from the Web UI
- **Trajectory Recording** — Per-turn agent execution trajectory (tool calls, LLM usage) persisted per conversation, browsable with pagination in the Web UI Trajectory page; KV cache hit-rate summary exposed for the status bar
- **Context Compression** — Conversation context is checkpointed (LangGraph checkpointer) and can be compacted on demand via `POST /api/v1/conversations/{id}/compress`, with configurable strategies (`summary_recent` / sliding window) and token-budget trigger from `config.context`
- **Plugin System** — Register and manage tools, skills, channels, and providers with sandbox validation and dependency resolution
- **QQ Bot Channel** — Connect via QQ official bot SDK (`qq-botpy`), supports guild, group, and private messages
- **WeChat Channel** — iLink long-polling integration for personal WeChat account via [weixin-bot](https://github.com/epiral/weixin-bot), with QR code login
- **Dream Visualization** — Skill evolution timeline, maturity charts, skill cloud, and category statistics
- **Streaming WebSocket** — Real-time token-by-token responses over WebSocket connections
- **Security** — JWT authentication (HS256), sliding-window rate limiting, role-based access control, and data export/deletion
- **Backup & Recovery** — JSON-based backup with metadata envelopes
- **Web UI** — React 19 + TypeScript frontend with Chat, Coder (workspace-bound coding sessions), Tasks, Todo, Memory, Knowledge Base (RAG document management & retrieval testing), Trajectory (execution replay & cache stats), Settings (LLM presets, endpoints, connection & speed tests, web search), Plugins, Channels, and Dream pages. Supports English and Chinese via in-app language toggle, with dark/light/warm theme switching and a per-page differentiated status bar (including KV cache hit-rate and git branch indicators)
- **Docker** — Containerized deployment with docker-compose

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)

### Installation

```bash
# Clone the repository
git clone https://github.com/codant0/thumbelina.git
cd thumbelina

# Install Python dependencies
pip install -e ".[dev]"

# (Optional) Install RAG dependencies (llama-index embeddings & LLMs)
pip install -e ".[dev,rag]"

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### Configuration

The service starts with **no** LLM or auth configuration required — it works out of the box. `thumbelina.yaml` only covers infrastructure settings such as database and logging (optional):

```bash
cp thumbelina.yaml.example thumbelina.yaml
```

LLM (provider, model, API key) and auth are configured **after startup**:

- **LLM**: manage presets and endpoints in the Web UI "Settings" page (or via the `/api/v1/config/llm` API family); persisted to the config database and restored on restart.
- **Auth**: `auth.required_roles` can be hot-updated at runtime via the config API; `auth.secret_key` is sensitive and can only be supplied via environment variable (≥32 bytes, restart required).

Optional startup overrides via environment variables:

```bash
# Optional: inject an LLM API key at startup (not required)
export THUMBELINA_LLM__API_KEY="sk-..."
# Optional: enable JWT auth (takes effect when non-empty and ≥32 bytes)
export THUMBELINA_AUTH__SECRET_KEY="..."
```

Configuration priority (highest to lowest):
1. Database overrides (via `POST /api/v1/config` or `PUT /api/v1/config/llm`)
2. Environment variables (`THUMBELINA_*` with `__` nesting, e.g. `THUMBELINA_LLM__PROVIDER`)
3. YAML config file (`thumbelina.yaml`)
4. Code defaults

Sensitive fields (API keys, secret_key) are never written to the config database — LLM keys are managed through the endpoint/preset APIs, and `secret_key` is only accepted from the environment.

### Running

```bash
# Start both backend and frontend dev servers simultaneously
python start_dev.py
# Backend:  http://localhost:8000 (uvicorn with --reload)
# Frontend: http://localhost:5173 (vite)

# Or start them separately:
thumbelina-serve                # API server only
cd frontend && npm run dev      # Frontend only

# Interactive CLI (`thumb` is an equivalent shortcut)
thumbelina
# or
thumb
```

### Docker

```bash
# Optional: preset the LLM API key at startup (not required; can also be configured in the Web UI Settings after startup)
export THUMBELINA_LLM__API_KEY="sk-..."

# Build and start (first run)
docker compose up -d --build
# Web UI + API:  http://localhost:8000
```

A single container runs both the FastAPI backend and the built React frontend
(uvicorn serves the static files directly — no nginx). The frontend uses
relative paths (`/api/v1/*`, `/ws/chat`), so everything is reachable through
port 8000. `thumbelina.yaml` is mounted read-only into the container; the
SQLite database (`sqlite:////app/data/thumbelina.db`, which also holds the
LangGraph checkpoint context), ChromaDB data (`/app/data/chroma`), the HF model
cache, and the TODO/notes markdown all live under `/app/data`, backed by the
named volume `thumbelina-data` by default and surviving rebuilds. To store data
in a host directory instead, set `THUMBELINA_DATA_DIR` (e.g.
`THUMBELINA_DATA_DIR=./data docker compose up -d --build`) — see
[docs/docker-deployment.md](docs/docker-deployment.md).

After code changes, rebuild and restart:

```bash
docker compose up -d --build
```

Dependency layers are cached, so rebuilds only reinstall what changed.
For the full deployment guide (updates, backups, data migration, FAQ, production tips), see [docs/docker-deployment.md](docs/docker-deployment.md).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  React Frontend (Vite)                                       │
│  Chat · Coder · Tasks · Todo · Memory · Knowledge Base ·     │
│  Trajectory · Settings · Plugins · Channels · Dream          │
│  WebSocket /ws/chat (streaming) · HTTP /api/v1/*             │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI Application (api/app.py)                            │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────┐          │
│  │ Lifespan │ │ Routes       │ │ WebSocket        │          │
│  │ (init)   │ │ /api/v1/chat │ │ /ws/chat         │          │
│  │          │ │ /api/v1/conv…│ │ (streaming)      │          │
│  │          │ │ /api/v1/tasks│ │                  │          │
│  │          │ │ /api/v1/skills│ │                 │          │
│  │          │ │ /api/v1/data │ │                  │          │
│  │          │ │ /api/v1/config│ │                │          │
│  │          │ │ /api/v1/feedback│ │              │          │
│  │          │ │ /api/v1/plugins│ │               │          │
│  │          │ │ /api/v1/qq   │ │                  │          │
│  │          │ │ /api/v1/wechat│ │                 │          │
│  └──────────┘ └──────┬───────┘ └────────┬─────────┘          │
└───────────────────────┼─────────────────┼────────────────────┘
                        │                 │
┌───────────────────────▼─────────────────▼────────────────────┐
│  ThumbelinaAgent (agent/graph.py)                            │
│  LangGraph StateGraph: agent ⇄ tools                        │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────────────────┐ │
│  │ Skills  │ │Subagents│ │ Scheduler │ │ Tools (5 cats)   │ │
│  │ Engine  │ │ Manager │ │           │ │ perception/exec/ │ │
│  │+Compos. │ │+Monitor │ │+Condition │ │ comm/collab/     │ │
│  │+Feedback│ │+Worker  │ │+Notify    │ │ event; exec has  │ │
│  │         │ │         │ │           │ │ review+verify    │ │
│  │         │ │         │ │           │ │ +fs/web/search/  │ │
│  │         │ │         │ │           │ │ shell/data       │ │
│  └─────────┘ └─────────┘ └───────────┘ └──────────────────┘ │
│  ┌──────────────┐ ┌──────────────────┐                       │
│  │ Memory       │ │ Skill Context    │                       │
│  │ (L0 index    │ │ (injected as     │                       │
│  │  injected)   │ │  SystemMessage)  │                       │
│  └──────────────┘ └──────────────────┘                       │
└───────────────────────────┬──────────────────────────────────┘
                            │
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
     ┌──────────┐   ┌──────────┐   ┌──────────────┐
     │ LLM      │   │ Memory   │   │ Skills /     │
     │ Providers│   │ Manager  │   │ Subagents /  │
     │ (OpenAI, │   │ (SQLite, │   │ Scheduler /  │
     │  Anthr., │   │  Chroma) │   │ Channels     │
     │  Ollama) │   │          │   │ (QQ, WeChat) │
     └──────────┘   └──────────┘   └──────────────┘
```

## Project Structure

```
thumbelina/
├── src/thumbelina/
│   ├── main.py              # FastAPI entry point (uvicorn)
│   ├── agent/               # LangGraph agent (graph, nodes, edges, state)
│   ├── api/                 # FastAPI app factory, routes, WebSocket, dependency injection
│   ├── backup/              # JSON backup manager
│   ├── channels/            # IM channels (QQ Bot, WeChat via weixin-bot)
│   ├── cli/                 # Click CLI with prompt_toolkit chat session
│   ├── config/              # YAML + env var config loader, Pydantic models
│   ├── llm/                 # LLM provider abstraction (OpenAI, Anthropic, Ollama)
│   ├── repository/          # Conversation persistence, search, vector store, feedback, trajectory
│   ├── analysis/            # LLM analysis services: title summarizer, conversation namer
│   ├── filestore/           # Shared atomic file I/O + per-key async file locks (used by todo/memory)
│   ├── memory/              # Markdown layered memory (L0/L1/L2, extractor, search, tools)
│   ├── notifications.py     # WebSocket notification broadcast
│   ├── plugins/             # Plugin system (register, sandbox, dependency resolution)
│   ├── prompts/roles/       # Role persona markdown files (assistant, coder)
│   ├── rag/                 # RAG: document ingestion, chunking, embedding, retrieval, indexing pipeline
│   │   ├── embedding/       # Embedding model abstraction (HuggingFace, ChromaDB vector store, registry)
│   │   ├── ingestion/       # Document loaders and chunkers
│   │   ├── knowledge_base/  # KnowledgeBase, Document, Chunk models + repository
│   │   ├── pipeline/        # Document indexing pipeline
│   │   └── retrieval/       # Retrieval strategies and context formatting
│   ├── scheduler/           # Task scheduler + natural language time parser + conditional triggers
│   ├── security/            # JWT auth + rate limiter + RBAC
│   ├── skills/              # Skill extraction, matching, composition, persistence
│   ├── subagents/           # Sub-agent manager, monitor/worker agents, message queue, shared state
│   ├── todo/                # Markdown todo list & quick notes service
│   └── tools/               # Built-in tools under a five-category taxonomy: base.py (ThumbelinaBaseTool template lifecycle) + perception / execution / communication / collaboration / event_trigger modules; execution tools enforce security review + result self-verification
├── tests/                   # Pytest test suite (mirrors src/ structure)
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── api/             # API client modules (conversations, llmConfig)
│       ├── components/
│       │   ├── Channels/    # ChannelsPage (QQ/WeChat config & status)
│       │   ├── Chat/        # ChatWindow, InputBox, MessageList, KnowledgeBaseSelector
│       │   ├── Coder/       # CoderPage, CoderSidebar, WorkspacePicker (workspace-bound coding)
│       │   ├── Dream/       # Skill evolution visualization
│       │   ├── KnowledgeBase/ # KnowledgeBasePage (KB CRUD, document management, retrieval test)
│       │   ├── Layout/      # Header, Sidebar, ThemeToggle (dark/light/warm)
│       │   ├── Memory/      # MemoryViewer (search + skill browser)
│       │   ├── Plugins/     # PluginsPage (plugin list + sandbox report)
│       │   ├── Settings/    # LLM endpoint/preset management, connection test, speed test, web search config
│       │   ├── StatusBar/   # Per-page differentiated status bar items
│       │   ├── Tasks/       # TaskManager (subagents + scheduled tasks)
│       │   ├── Todo/        # TodoPage (todo list + quick notes, heading groups)
│       │   └── Trajectory/  # TrajectoryPage, TrajectoryDetailModal (execution replay)
│       ├── hooks/           # useWebSocket custom hook
│       ├── i18n/            # Internationalization (en, zh-CN) with LocaleContext
│       ├── test/            # Test setup
│       └── types/           # TypeScript interfaces
├── docs/specs/              # Design specs
├── docs/plans/              # Implementation plans
├── docs/review/             # Review records
├── Dockerfile               # Multi-stage image: builds frontend, backend serves it
├── docker-compose.yml       # Single-container deployment
├── thumbelina.yaml.example  # Example configuration
└── pyproject.toml           # Project metadata, dependencies, tool configs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (returns version + database status) |
| POST | `/api/v1/chat` | Send a message, get an agent response |
| GET | `/api/v1/conversations` | List all conversations |
| POST | `/api/v1/conversations` | Create a new conversation (`mode: chat | coder`; coder requires `workspace`) |
| GET | `/api/v1/conversations/search/{query}` | Search messages across conversations |
| GET | `/api/v1/conversations/{id}` | Get conversation with messages |
| PATCH | `/api/v1/conversations/{id}` | Rename a conversation |
| PUT | `/api/v1/conversations/{id}/endpoint` | Set per-conversation LLM endpoint and model |
| PUT | `/api/v1/conversations/{id}/role` | Set per-conversation role (`null` = restore global default) |
| PUT | `/api/v1/conversations/{id}/knowledge-base` | Bind a RAG knowledge base to a conversation |
| PUT | `/api/v1/conversations/{id}/thinking` | Set per-conversation thinking mode (enabled + effort) |
| POST | `/api/v1/conversations/{id}/compress` | Manually compress the conversation context |
| DELETE | `/api/v1/conversations/{id}/messages` | Delete all messages of a conversation |
| DELETE | `/api/v1/conversations/{id}` | Delete a conversation |
| GET | `/api/v1/fs/dirs` | List directories (for the workspace picker) |
| GET | `/api/v1/fs/git` | Probe workspace git status (is_git + current branch) |
| GET | `/api/v1/fs/git/branches` | List local branches and the current one |
| POST | `/api/v1/fs/git/checkout` | Switch to a local branch (server-side validated; broadcasts via WebSocket) |
| GET | `/api/v1/tasks` | List scheduled tasks |
| POST | `/api/v1/tasks/{id}/cancel` | Cancel a scheduled task |
| GET | `/api/v1/subagents` | List active sub-agents |
| POST | `/api/v1/subagents/{id}/cancel` | Cancel a running sub-agent |
| GET | `/api/v1/skills` | List extracted skills |
| GET | `/api/v1/skills/stats` | Skill usage statistics (for Dream visualization) |
| GET | `/api/v1/compositions` | List skill compositions |
| GET | `/api/v1/trajectory/{conversation_id}` | Paged agent execution trajectory for a conversation |
| GET | `/api/v1/trajectory/cache-stats` | KV cache hit-rate summary (status bar) |
| POST | `/api/v1/feedback` | Submit user feedback (rating 1-5) |
| GET | `/api/v1/feedback` | List feedback records |
| GET | `/api/v1/feedback/stats` | Feedback statistics |
| GET | `/api/v1/data/export` | Export all user data (conversations + memory) |
| DELETE | `/api/v1/data/all` | Delete all user data (conversations + memory) |
| GET | `/api/v1/memory/index` | View the L0 memory index (auto-generated summaries) |
| GET | `/api/v1/memory/entries` | List all memory entries grouped by category |
| GET | `/api/v1/memory/search?q=` | n-gram search over memory summaries (L0 triage) |
| GET | `/api/v1/memory/{category}/{slug}?depth=` | Read a memory entry at `overview` (L1) or `full` (L2) depth |
| POST | `/api/v1/memory/refresh` | Rebuild the memory index from disk |
| GET | `/api/v1/memory/status` | Memory subsystem status (enabled, counts, bytes) |
| GET | `/api/v1/plugins` | List loaded plugins with sandbox status |
| GET | `/api/v1/plugins/sandbox-report` | Plugin sandbox validation report |
| GET | `/api/v1/plugins/dependencies` | Plugin dependency graph |
| GET | `/api/v1/roles` | List available roles (prompts live in `prompts/roles/`) |
| GET | `/api/v1/config` | Current configuration snapshot |
| POST | `/api/v1/config` | Update runtime configuration |
| PUT | `/api/v1/config/llm` | Hot-swap LLM provider/model |
| GET | `/api/v1/config/llm/presets` | List saved LLM presets |
| POST | `/api/v1/config/llm/presets` | Create a new LLM preset |
| GET | `/api/v1/config/llm/presets/{id}` | Get a single LLM preset |
| PUT | `/api/v1/config/llm/presets/{id}` | Update an LLM preset |
| DELETE | `/api/v1/config/llm/presets/{id}` | Delete an LLM preset |
| POST | `/api/v1/config/llm/presets/{id}/activate` | Activate a preset (hot-swap) |
| GET | `/api/v1/config/llm/models` | Fetch available models from a live endpoint |
| POST | `/api/v1/config/llm/test-connection` | Test connectivity to arbitrary provider parameters |
| GET | `/api/v1/config/llm/endpoints` | List saved LLM endpoints |
| POST | `/api/v1/config/llm/endpoints` | Create a new LLM endpoint |
| PUT | `/api/v1/config/llm/endpoints/{id}` | Update an LLM endpoint |
| DELETE | `/api/v1/config/llm/endpoints/{id}` | Delete an LLM endpoint |
| POST | `/api/v1/config/llm/endpoints/{id}/speed-test` | Run a speed test against a saved endpoint |
| POST | `/api/v1/config/llm/endpoints/{id}/test-connection` | Run a connectivity test against a saved endpoint |
| POST | `/api/v1/config/llm/endpoints/{id}/activate` | Globally activate a saved endpoint (hot-swap LLM) |
| PUT | `/api/v1/config/channels/{name}` | Hot-swap channel configuration |
| GET | `/api/v1/config/tools` | Current tools config (web search provider, key-set flag) |
| PUT | `/api/v1/config/tools/web_search` | Update web search config (hot-swappable) |
| GET | `/api/v1/todo/status` | TODO module status (enabled, file paths, counts) |
| GET | `/api/v1/todo/items` | List todo items (`TodoItemsOut`, entries carry their source heading group) |
| POST | `/api/v1/todo/items` | Add a todo item |
| PATCH | `/api/v1/todo/items/{index}` | Update a todo item (text / done / remark) |
| DELETE | `/api/v1/todo/items/{index}` | Delete a todo item |
| GET | `/api/v1/todo/notes` | List quick notes |
| POST | `/api/v1/todo/notes` | Add a quick note |
| PUT | `/api/v1/todo/notes/{index}` | Update a quick note |
| DELETE | `/api/v1/todo/notes/{index}` | Delete a quick note |
| GET | `/api/v1/config/export` | Export config from database |
| POST | `/api/v1/config/reload` | Reload config from database |
| GET | `/api/v1/qq/status` | Check QQ Bot connection status |
| POST | `/api/v1/wechat/incoming` | iLink webhook (incoming WeChat messages) |
| POST | `/api/v1/wechat/send` | Send message via iLink |
| GET | `/api/v1/wechat/status` | Check iLink connectivity |
| POST | `/api/v1/wechat/qrcode` | Fetch QR code for WeChat login |
| GET | `/api/v1/wechat/qrcode/status` | Poll QR code scan status |
| POST | `/api/v1/wechat/qrcode/confirm` | Confirm login and enable channel |
| GET | `/api/v1/rag/knowledge-bases` | List all RAG knowledge bases |
| POST | `/api/v1/rag/knowledge-bases` | Create a knowledge base |
| PUT | `/api/v1/rag/knowledge-bases/{id}` | Update a knowledge base |
| DELETE | `/api/v1/rag/knowledge-bases/{id}` | Delete a knowledge base (cascading) |
| GET | `/api/v1/rag/knowledge-bases/{id}/documents` | List documents in a knowledge base |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents` | Upload a document (async, returns a task id) |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents/url` | Upload a webpage by URL (async) |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents/batch` | Batch upload documents (async) |
| GET | `/api/v1/rag/upload-tasks/{task_id}` | Get upload task status and progress |
| GET | `/api/v1/rag/knowledge-bases/{id}/upload-tasks` | List upload tasks of a knowledge base |
| DELETE | `/api/v1/rag/upload-tasks/{task_id}` | Cancel or dismiss an upload task |
| DELETE | `/api/v1/rag/documents/{id}` | Delete a document |
| GET | `/api/v1/rag/documents/{id}/chunks` | List chunks of a document |
| POST | `/api/v1/rag/query` | Retrieve top-k chunks for a query |
| POST | `/api/v1/rag/documents/simhash-query` | Near-duplicate search across documents via SimHash |
| WS | `/ws/chat` | Real-time streaming chat via WebSocket |

## QQ Bot Setup

1. Register at [q.qq.com](https://q.qq.com) and create a bot application
2. Get your AppID and AppSecret
3. Add to `thumbelina.yaml`:
   ```yaml
   channels:
     qq:
       enabled: true
       app_id: "your_app_id"
       app_secret: "your_app_secret"
   ```
4. Start Thumbelina: `thumbelina-serve`

## WeChat Setup

WeChat integration uses the [weixin-bot](https://github.com/epiral/weixin-bot) protocol for direct iLink API communication — no sidecar process required.

### Option A: QR Code Login (Recommended)

1. Start Thumbelina: `thumbelina-serve`
2. Call `POST /api/v1/wechat/qrcode` to get a QR code
3. Scan the QR code with WeChat
4. Poll `GET /api/v1/wechat/qrcode/status` until status is `confirmed`
5. Call `POST /api/v1/wechat/qrcode/confirm` to save credentials and enable the channel

### Option B: Manual Configuration

Add to `thumbelina.yaml`:
```yaml
channels:
  wechat:
    enabled: true
    bot_token: "your_bot_token"
    ilink_bot_id: "your_bot_id"
    ilink_user_id: "your_user_id"
    ilink_base_url: "https://ilinkai.weixin.qq.com"
```

### Protocol Reference

This implementation follows the [weixin-bot protocol specification](https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md):
- Long-polling via `POST /ilink/bot/getupdates` with ~35s hold
- `context_token` is required for message delivery (managed automatically)
- Session expiration (`errcode=-14`) requires re-authentication via QR code
- `X-WECHAT-UIN` must be base64-encoded (per protocol spec)

## Development

### Running Tests

```bash
# All tests
pytest

# Specific module
pytest tests/test_agent/

# Single file, stop on first failure
pytest tests/test_api/test_chat.py -x -q

# With coverage
pytest --cov=thumbelina
```

### Linting & Type Checking

```bash
ruff check src/ tests/       # Lint
ruff format src/ tests/      # Format
mypy src/                    # Type check (strict mode)
```

### Frontend

```bash
cd frontend
npm run dev          # Dev server
npm run test         # Run tests
npm run lint         # ESLint
npm run build        # Production build
```

## Configuration Reference

`thumbelina.yaml.example` — all fields optional, shown with defaults:

```yaml
rate_limit:
  enabled: false            # Whether rate limiting is enabled
  max_requests: 60          # Max requests per window
  window_seconds: 60        # Time window in seconds

repository:
  database_url: sqlite:///thumbelina.db

logging:
  level: INFO               # DEBUG | INFO | WARNING | ERROR | CRITICAL

todo:
  enabled: true             # Enable the TODO module (local Markdown todo list & quick notes)
  directory: TODO           # Directory holding todolist.md / notes.md

tools:
  web_search:
    enabled: true           # Expose the web_search tool to the agent
    provider: tavily        # tavily | duckduckgo
    api_key: ""             # Tavily only; saved to the config database
```

> `llm` and `auth` are no longer startup configuration:
> - **llm.\*** — managed after startup via the Web UI "Settings" page or the `/api/v1/config/llm` API family (presets/endpoints persisted to the config database).
> - **auth.required_roles** — hot-updatable at runtime via the config API.
> - **auth.secret_key** — sensitive; only accepted from the `THUMBELINA_AUTH__SECRET_KEY` environment variable (≥32 bytes, restart required). Auth is automatically disabled when empty.
>
> **Web search tool** — `tools.web_search` selects the search backend:
> - `tavily` (default) — returns LLM-friendly answers; requires an API key, configured via the Web UI "Settings → Tools" and saved to the config database (a scoped exception to the sensitive-key policy for this tool only).
> - `duckduckgo` — no API key required; requires `pip install -e ".[web]"` (installs `ddgs`).
> `enabled`, `provider` and `api_key` are all hot-updatable at runtime via `PUT /api/v1/config/tools/web_search`.

The following sections are optional — uncomment in `thumbelina.yaml` to enable:

```yaml
# cors_origins: ["*"]         # CORS allowed origins; restrict in production

# plugin_dirs: []             # Directories to scan for plugins

# channels:
#   qq:
#     enabled: false
#     app_id: ""
#     app_secret: ""
#     allowed_guilds: []
#     allowed_groups: []
#   wechat:
#     enabled: false
#     bot_token: ""             # Bot token from iLink
#     ilink_bot_id: ""          # iLink bot ID
#     ilink_user_id: ""         # iLink user ID
#     ilink_base_url: "https://ilinkai.weixin.qq.com"
#     webhook_secret: ""
```

### Markdown Memory

The `memory:` section in `thumbelina.yaml` configures the layered Markdown memory subsystem (see `thumbelina.yaml.example` for full annotations). Key fields:

```yaml
memory:
  enabled: true               # Disable to turn off routes + agent injection entirely (routes return 503)
  directory: MEMORY           # Memory directory (relative to the working dir); holds index.md + <category>/<slug>.md
  categories: [user, project, decision, topic]  # Category whitelist; entries outside are ignored
  inject_index: true          # Inject the L0 index summary every agent turn
  inject_top_k: 8             # When the index exceeds index_token_cap, inject only the top-K relevant entries
  index_token_cap: 3000        # Token budget under which the whole index is injected (estimate_tokens basis)
  max_full_tokens: 4000       # Upper bound for read_full (L2); truncated beyond this
  max_entries: 200            # Total entry count guardrail
  max_total_bytes: 5_000_000  # Total memory directory byte guardrail
  extract:
    enabled: true             # Background LLM extraction/rewrite after each user turn
    on_user_message: true     # Only trigger extraction on user messages
    min_message_chars: 5      # Skip extraction below this message length (filters "ok/thanks"-style filler)
    max_input_tokens: 8000    # Per-extraction input token budget
  tools:
    enabled: true             # Expose search_memory / read_memory / remember to the agent
```

### Role Prompts

Role prompt files live in `src/thumbelina/prompts/roles/` — adding a new role only requires a new `<role>.md` file:

- **Global default role**: `assistant` by default; override with the `THUMBELINA_LLM__ROLE` environment variable.
- **Per-conversation switching**: a conversation-level role overrides the global default. Switch it via the role selector in the Web UI chat input toolbar, or call `PUT /api/v1/conversations/{id}/role` (pass `null` to restore the global default).
- Built-in roles: `assistant` (personal assistant), `coder` (software engineer).

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Uvicorn, httpx |
| Agent Framework | LangGraph, LangChain |
| LLM Providers | OpenAI, Anthropic, Ollama (via LangChain) |
| RAG | llama-index-core (embeddings, vector retrieval) |
| Database | SQLAlchemy + SQLite |
| Vector Store | ChromaDB |
| Auth | PyJWT (HS256) |
| CLI | Click, prompt_toolkit |
| Frontend | React 19, TypeScript, Vite |
| IM Channels | qq-botpy (QQ), weixin-bot (WeChat) |
| Testing | pytest, pytest-asyncio, Vitest |
| Linting | Ruff, ESLint, mypy |
| Container | Docker, docker-compose |
