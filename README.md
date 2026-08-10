# Thumbelina

An AI-powered personal assistant built with [FastAPI](https://fastapi.tiangolo.com/) and [LangGraph](https://langchain-ai.github.io/langgraph/), featuring multi-provider LLM support, conversation memory with skill extraction, sub-agent orchestration, and a React-based chat UI.

[中文文档](README_CN.md)

## Features

- **Multi-Provider LLM** — Pluggable support for OpenAI, Anthropic, and Ollama via a unified abstraction layer, with named presets for quick switching and one-click connectivity testing
- **LLM Preset Management** — Save multiple LLM configurations (provider, base URL, API key, model) with custom names and activate any preset with one click
- **LLM Connection Test** — Three-level connectivity verification (network reachability → auth validity → service availability) for any provider endpoint
- **DeepSeek API Support** — Compatible via `openai` provider with graceful fallback for `/models` endpoint
- **Agent Core** — LangGraph-powered agent loop with tool calling and conditional routing
- **Built-in Tools** — File operations, web requests, shell commands, and data processing (JSON/CSV/text analysis/regex search)
- **RAG (Retrieval-Augmented Generation)** — Document ingestion, chunking, embedding (HuggingFace via llama-index), vector retrieval (ChromaDB), and context-aware indexing pipeline
- **Conversation Memory** — Persistent storage (SQLite) with keyword search, LLM-generated summaries, and auto-naming for new conversations
- **Semantic Search** — Vector-based semantic search via ChromaDB, with hybrid keyword + semantic fallback
- **Skill Extraction & Integration** — Automatically extracts reusable skills from conversations and applies them in the agent loop
- **Skill Composition** — Chain multiple skills into workflows, with LLM-assisted suggestion
- **User Profiler** — Analyzes conversation patterns to build user preference profiles for personalized responses
- **Sub-Agent System** — Parallel task execution with monitor/worker agents, inter-agent messaging and shared state
- **Task Scheduler** — Natural language time parsing (Chinese & English) with conditional triggers and notification broadcast
- **Plugin System** — Register and manage tools, skills, channels, and providers with sandbox validation and dependency resolution
- **QQ Bot Channel** — Connect via QQ official bot SDK (`qq-botpy`), supports guild, group, and private messages
- **WeChat Channel** — iLink long-polling integration for personal WeChat account via [weixin-bot](https://github.com/epiral/weixin-bot), with QR code login
- **Dream Visualization** — Skill evolution timeline, maturity charts, skill cloud, and category statistics
- **Streaming WebSocket** — Real-time token-by-token responses over WebSocket connections
- **Security** — JWT authentication (HS256), sliding-window rate limiting, role-based access control, and data export/deletion
- **Backup & Recovery** — JSON-based backup with metadata envelopes
- **Web UI** — React 19 + TypeScript frontend with Chat, Tasks, Memory, Knowledge Base (RAG document management & retrieval testing), Settings (LLM presets, endpoints, connection test), Plugins, Channels, and Dream pages. Supports English and Chinese via in-app language toggle, with dark/light/warm theme switching
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

Copy the example config and edit it with your settings:

```bash
cp thumbelina.yaml.example thumbelina.yaml
```

Or use environment variables:

```bash
export OPENAI_API_KEY="sk-..."
# Or for Anthropic:
export ANTHROPIC_API_KEY="sk-ant-..."
```

Configuration priority (highest to lowest):
1. Database overrides (via `POST /api/v1/config` or `PUT /api/v1/config/llm`)
2. Environment variables (`THUMBELINA_*` with `__` nesting, e.g. `THUMBELINA_LLM__PROVIDER`)
3. YAML config file (`thumbelina.yaml`)
4. Defaults in `thumbelina.yaml.example`

Sensitive fields (API keys, tokens) stored in LLM endpoints are managed via the endpoint manager API — prefer environment variables for initial setup.

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
# Set the LLM API key (or write api_key directly into thumbelina.yaml)
export THUMBELINA_LLM__API_KEY="sk-..."

# Build and start (first run)
docker compose up -d --build
# Backend:  http://localhost:8000
# Frontend: http://localhost:3000
```

The frontend container (nginx) proxies `/api` and `/ws` to the backend, so the
web UI works entirely through port 3000. `thumbelina.yaml` is mounted
read-only into the backend container; the SQLite database
(`sqlite:////app/data/thumbelina.db`) and ChromaDB data (`/app/data/chroma`)
live in the named volume `thumbelina-data` and survive rebuilds.

After code changes, rebuild and restart only the affected service:

```bash
docker compose up -d --build backend   # or: frontend
```

Dependency layers are cached, so rebuilds only reinstall what changed.
For the full deployment guide (updates, backups, data migration, FAQ, production tips), see [docs/docker-deployment.md](docs/docker-deployment.md).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  React Frontend (Vite)                                       │
│  Chat · Tasks · Memory · Settings · Plugins · Channels · Dream│
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
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────────┐         │
│  │ Skills  │ │Subagents│ │ Scheduler │ │  Tools   │         │
│  │ Engine  │ │ Manager │ │           │ │ (file,   │         │
│  │+Compos. │ │+Monitor │ │+Condition │ │  web,    │         │
│  │+Feedback│ │+Worker  │ │+Notify    │ │  shell,  │         │
│  │         │ │         │ │           │ │  data)   │         │
│  └─────────┘ └─────────┘ └───────────┘ └──────────┘         │
│  ┌──────────────┐ ┌──────────────────┐                       │
│  │ User Profiler│ │ Skill Context    │                       │
│  │ (preferences)│ │ (injected as     │                       │
│  │              │ │  SystemMessage)  │                       │
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
│   ├── memory/              # Conversation persistence, search, summarizer, vector store, user profiler, feedback
│   ├── notifications.py     # WebSocket notification broadcast
│   ├── plugins/             # Plugin system (register, sandbox, dependency resolution)
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
│   └── tools/               # Built-in tools (file ops, web requests, shell, data processing)
├── tests/                   # Pytest test suite (mirrors src/ structure)
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── api/             # API client modules (conversations, llmConfig)
│       ├── components/
│       │   ├── Channels/    # ChannelsPage (QQ/WeChat config & status)
│       │   ├── Chat/        # ChatWindow, InputBox, MessageList, KnowledgeBaseSelector
│       │   ├── Dream/       # Skill evolution visualization
│       │   ├── KnowledgeBase/ # KnowledgeBasePage (KB CRUD, document management, retrieval test)
│       │   ├── Layout/      # Header, Sidebar, ThemeToggle (dark/light/warm)
│       │   ├── Memory/      # MemoryViewer (search + skill browser)
│       │   ├── Plugins/     # PluginsPage (plugin list + sandbox report)
│       │   ├── Settings/    # LLM endpoint/preset management, connection test, speed test
│       │   └── Tasks/       # TaskManager (subagents + scheduled tasks)
│       ├── hooks/           # useWebSocket custom hook
│       ├── i18n/            # Internationalization (en, zh-CN) with LocaleContext
│       ├── test/            # Test setup
│       └── types/           # TypeScript interfaces
├── docs/plans/              # Design documents (Chinese)
├── Dockerfile               # Backend container
├── Dockerfile.frontend      # Frontend container (nginx)
├── docker-compose.yml       # Multi-container deployment
├── thumbelina.yaml.example  # Example configuration
└── pyproject.toml           # Project metadata, dependencies, tool configs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (returns version + database status) |
| POST | `/api/v1/chat` | Send a message, get an agent response |
| GET | `/api/v1/conversations` | List all conversations |
| POST | `/api/v1/conversations` | Create a new conversation |
| GET | `/api/v1/conversations/search/{query}` | Search messages across conversations |
| GET | `/api/v1/conversations/{id}` | Get conversation with messages |
| PATCH | `/api/v1/conversations/{id}` | Rename a conversation |
| PUT | `/api/v1/conversations/{id}/endpoint` | Set per-conversation LLM endpoint and model |
| PUT | `/api/v1/conversations/{id}/knowledge-base` | Bind a RAG knowledge base to a conversation |
| DELETE | `/api/v1/conversations/{id}` | Delete a conversation |
| GET | `/api/v1/tasks` | List scheduled tasks |
| POST | `/api/v1/tasks/{id}/cancel` | Cancel a scheduled task |
| GET | `/api/v1/subagents` | List active sub-agents |
| POST | `/api/v1/subagents/{id}/cancel` | Cancel a running sub-agent |
| GET | `/api/v1/skills` | List extracted skills |
| GET | `/api/v1/skills/stats` | Skill usage statistics (for Dream visualization) |
| GET | `/api/v1/compositions` | List skill compositions |
| POST | `/api/v1/feedback` | Submit user feedback (rating 1-5) |
| GET | `/api/v1/feedback` | List feedback records |
| GET | `/api/v1/feedback/stats` | Feedback statistics |
| GET | `/api/v1/data/export` | Export all user data |
| DELETE | `/api/v1/data/all` | Delete all user data |
| GET | `/api/v1/user/profile` | Get user profile and preferences |
| GET | `/api/v1/plugins` | List loaded plugins with sandbox status |
| GET | `/api/v1/plugins/sandbox-report` | Plugin sandbox validation report |
| GET | `/api/v1/plugins/dependencies` | Plugin dependency graph |
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
| POST | `/api/v1/rag/query` | Retrieve top-k chunks for a query |
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
auth:
  secret_key: ""            # JWT signing key; Bearer auth enabled when non-empty
  required_roles: []        # Global role list; empty = all authenticated users allowed

rate_limit:
  enabled: false            # Whether rate limiting is enabled
  max_requests: 60          # Max requests per window
  window_seconds: 60        # Time window in seconds

memory:
  database_url: sqlite:///thumbelina.db

logging:
  level: INFO               # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

The following sections are optional — uncomment in `thumbelina.yaml` to enable:

```yaml
# llm:
#   provider: openai          # openai | anthropic | ollama
#   model: gpt-4o             # Model identifier
#   api_key: ${OPENAI_API_KEY} # Supports ${VAR} env substitution
#   base_url: null            # Custom API endpoint URL
#   request_timeout: null     # LLM request timeout in seconds
#   streaming_enabled: true   # Enable WebSocket streaming responses

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
