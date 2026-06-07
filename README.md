# Thumbelina

An AI-powered personal assistant built with [FastAPI](https://fastapi.tiangolo.com/) and [LangGraph](https://langchain-ai.github.io/langgraph/), featuring multi-provider LLM support, conversation memory with skill extraction, sub-agent orchestration, and a React-based chat UI.

[中文文档](README_CN.md)

## Features

- **Multi-Provider LLM** — Pluggable support for OpenAI, Anthropic, and Ollama via a unified abstraction layer
- **Agent Core** — LangGraph-powered agent loop with tool calling and conditional routing
- **Built-in Tools** — File operations, web requests, shell commands, and data processing (JSON/CSV/text analysis)
- **Conversation Memory** — Persistent storage (SQLite) with keyword search and LLM-generated summaries
- **Semantic Search** — Vector-based semantic search via ChromaDB, with hybrid keyword + semantic fallback
- **Skill Extraction & Integration** — Automatically extracts reusable skills from conversations and applies them in the agent loop
- **Skill Composition** — Chain multiple skills into workflows, with LLM-assisted suggestion
- **User Profiler** — Analyzes conversation patterns to build user preference profiles for personalized responses
- **User Feedback** — Rate skill responses (1-5 stars), scores automatically adjust skill matching priority
- **Sub-Agent System** — Parallel task execution with monitor/worker agents, inter-agent messaging and shared state
- **Task Scheduler** — Natural language time parsing (Chinese & English) with conditional triggers and notification broadcast
- **Plugin System** — Register and manage tools, skills, channels, and providers with sandbox validation and dependency resolution
- **QQ Bot Channel** — Connect via QQ official bot SDK (`qq-botpy`), supports guild, group, and private messages
- **WeChat ClawBot Channel** — Connect via WeClaw HTTP bridge for personal WeChat account integration
- **Dream Visualization** — Skill evolution timeline, maturity charts, skill cloud, and category statistics
- **Streaming WebSocket** — Real-time token-by-token responses over WebSocket connections
- **Security** — JWT authentication (HS256), sliding-window rate limiting, role-based access control, and data export/deletion
- **Backup & Recovery** — JSON-based backup with metadata envelopes
- **Web UI** — React 19 + TypeScript frontend with Chat, Tasks, Memory, Settings, Plugins, Channels, and Dream pages
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
1. Environment variables (`THUMBELINA_*` with `__` nesting, e.g. `THUMBELINA_LLM__PROVIDER`)
2. YAML config file (`thumbelina.yaml`)
3. Defaults in `thumbelina.yaml.example`

### Running

```bash
# Start the API server (default: http://127.0.0.1:8000)
thumbelina-serve

# Or use the interactive CLI (`thumb` is an equivalent shortcut)
thumbelina
# or
thumb

# Start the frontend dev server
cd frontend && npm run dev
```

### Docker

```bash
docker-compose up -d
```

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
│   ├── channels/            # IM channels (QQ Bot, WeChat ClawBot)
│   ├── cli/                 # Click CLI with prompt_toolkit chat session
│   ├── config/              # YAML + env var config loader, Pydantic models
│   ├── llm/                 # LLM provider abstraction (OpenAI, Anthropic, Ollama)
│   ├── memory/              # Conversation persistence, search, summarizer, vector store, user profiler, feedback
│   ├── notifications/       # WebSocket notification broadcast
│   ├── plugins/             # Plugin system (register, sandbox, dependency resolution)
│   ├── scheduler/           # Task scheduler + natural language time parser + conditional triggers
│   ├── security/            # JWT auth + rate limiter + RBAC
│   ├── skills/              # Skill extraction, matching, composition, persistence
│   ├── subagents/           # Sub-agent manager, monitor/worker agents, message queue, shared state
│   └── tools/               # Built-in tools (file ops, web requests, shell, data processing)
├── tests/                   # Pytest test suite (mirrors src/ structure)
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── components/
│       │   ├── Channels/    # ChannelsPage (QQ/WeChat config & status)
│       │   ├── Chat/        # ChatWindow, InputBox, MessageList
│       │   ├── Dream/       # Skill evolution visualization
│       │   ├── Layout/      # Header, Sidebar
│       │   ├── Memory/      # MemoryViewer (search + skill browser)
│       │   ├── Plugins/     # PluginsPage (plugin list + sandbox report)
│       │   ├── Settings/    # SettingsPanel (LLM config, data management)
│       │   └── Tasks/       # TaskManager (subagents + scheduled tasks)
│       ├── hooks/           # useWebSocket custom hook
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
| GET | `/health` | Health check |
| POST | `/api/v1/chat` | Send a message, get an agent response |
| GET | `/api/v1/conversations` | List all conversations |
| GET | `/api/v1/conversations/search/{query}` | Search messages across conversations |
| GET | `/api/v1/conversations/{id}` | Get conversation with messages |
| DELETE | `/api/v1/conversations/{id}` | Delete a conversation |
| GET | `/api/v1/tasks` | List scheduled tasks |
| GET | `/api/v1/subagents` | List active sub-agents |
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
| GET | `/api/v1/qq/status` | Check QQ Bot connection status |
| POST | `/api/v1/wechat/incoming` | WeClaw webhook (incoming WeChat messages) |
| POST | `/api/v1/wechat/send` | Send message via WeClaw |
| GET | `/api/v1/wechat/status` | Check WeClaw connectivity |
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

## WeChat ClawBot Setup

1. Install WeClaw: `curl -sSL https://raw.githubusercontent.com/fastclaw-ai/weclaw/main/install.sh | sh`
2. Configure WeClaw to point to Thumbelina (see `docs/plans/weclaw-config.example.json`)
3. Add to `thumbelina.yaml`:
   ```yaml
   channels:
     wechat:
       enabled: true
       weclaw_api_url: "http://127.0.0.1:18011"
   ```
4. Start WeClaw: `weclaw start`
5. Start Thumbelina: `thumbelina-serve`
6. Scan QR code with WeChat to login

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
llm:
  provider: openai          # openai | anthropic | ollama
  model: gpt-4o             # Model identifier
  api_key: ${OPENAI_API_KEY} # Supports ${VAR} env substitution
  base_url: null            # Custom API endpoint URL
  request_timeout: null     # LLM request timeout in seconds
  streaming_enabled: true   # Enable WebSocket streaming responses

cors_origins: ["*"]         # CORS allowed origins; restrict in production

auth:
  secret_key: ""            # JWT signing key; Bearer auth enabled when non-empty
  required_roles: []        # Global role list; empty = all authenticated users allowed

rate_limit:
  enabled: false            # Whether rate limiting is enabled
  max_requests: 60          # Max requests per window
  window_seconds: 60        # Time window in seconds

memory:
  database_url: sqlite:///thumbelina.db

channels:
  qq:
    enabled: false
    app_id: ""
    app_secret: ""
    allowed_guilds: []
    allowed_groups: []
  wechat:
    enabled: false
    weclaw_api_url: "http://127.0.0.1:18011"
    weclaw_token: ""
    webhook_secret: ""

plugin_dirs: []             # Directories to scan for plugins

logging:
  level: INFO               # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Uvicorn |
| Agent Framework | LangGraph, LangChain |
| LLM Providers | OpenAI, Anthropic, Ollama (via LangChain) |
| Database | SQLAlchemy + SQLite |
| Vector Store | ChromaDB |
| Auth | PyJWT (HS256) |
| CLI | Click, prompt_toolkit |
| Frontend | React 19, TypeScript, Vite |
| IM Channels | qq-botpy (QQ), WeClaw (WeChat) |
| Testing | pytest, pytest-asyncio, Vitest |
| Linting | Ruff, ESLint, mypy |
| Container | Docker, docker-compose |
