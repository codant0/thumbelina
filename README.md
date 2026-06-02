# Thumbelina

An AI-powered personal assistant built with [FastAPI](https://fastapi.tiangolo.com/) and [LangGraph](https://langchain-ai.github.io/langgraph/), featuring multi-provider LLM support, conversation memory with skill extraction, sub-agent orchestration, and a React-based chat UI.

[中文文档](README_CN.md)

## Features

- **Multi-Provider LLM** — Pluggable support for OpenAI, Anthropic, and Ollama via a unified abstraction layer
- **Agent Core** — LangGraph-powered agent loop with tool calling and conditional routing
- **Conversation Memory** — Persistent storage (SQLite) with keyword search and LLM-generated summaries
- **Skill Extraction** — Automatically extracts reusable skills from successful conversations
- **Sub-Agent System** — Parallel task execution with inter-agent messaging and shared state
- **Task Scheduler** — Natural language time parsing (Chinese & English) with recurring task support
- **Plugin System** — Register and manage tools, skills, channels, and providers
- **Security** — JWT authentication (HS256) and sliding-window rate limiting
- **Backup & Recovery** — JSON-based backup with metadata envelopes
- **Web UI** — React 19 + TypeScript frontend with real-time WebSocket chat

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

Copy and edit the default config:

```bash
cp thumbelina.yaml my-config.yaml
```

Or use environment variables:

```bash
export OPENAI_API_KEY="sk-..."
# Or for Anthropic:
export ANTHROPIC_API_KEY="sk-ant-..."
```

Configuration priority (highest to lowest):
1. Environment variables (`THUMBELINA_*` with `__` nesting, e.g. `THUMBELINA_LLM__PROVIDER`)
2. YAML config file
3. Defaults in `thumbelina.yaml`

### Running

```bash
# Start the API server (default: http://127.0.0.1:8000)
thumbelina-serve

# Or use the interactive CLI
thumbelina

# Start the frontend dev server
cd frontend && npm run dev
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  React Frontend (Vite)                              │
│  WebSocket /ws/chat · HTTP /api/chat                │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  FastAPI Application (api/app.py)                   │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────┐ │
│  │ Lifespan │ │ Routes       │ │ WebSocket        │ │
│  │ (init)   │ │ /api/chat    │ │ /ws/chat         │ │
│  │          │ │ /api/convos  │ │                  │ │
│  └──────────┘ └──────┬───────┘ └────────┬─────────┘ │
└──────────────────────┼─────────────────┼────────────┘
                       │                 │
┌──────────────────────▼─────────────────▼────────────┐
│  ThumbelinaAgent (agent/graph.py)                   │
│  LangGraph StateGraph: agent ⇄ tools               │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────────┐
  │ LLM      │  │ Memory   │  │ Skills /     │
  │ Providers│  │ Manager  │  │ Subagents /  │
  │ (OpenAI, │  │ (SQLite) │  │ Scheduler    │
  │  Anthr., │  │          │  │              │
  │  Ollama) │  │          │  │              │
  └──────────┘  └──────────┘  └──────────────┘
```

## Project Structure

```
thumbelina/
├── src/thumbelina/
│   ├── main.py              # FastAPI entry point (uvicorn)
│   ├── agent/               # LangGraph agent (graph, nodes, edges, state)
│   ├── api/                 # FastAPI app factory, routes, WebSocket, dependency injection
│   ├── backup/              # JSON backup manager
│   ├── cli/                 # Click CLI with prompt_toolkit chat session
│   ├── config/              # YAML + env var config loader, Pydantic models
│   ├── llm/                 # LLM provider abstraction (OpenAI, Anthropic, Ollama)
│   ├── memory/              # Conversation persistence, search, summarizer, vector store
│   ├── plugins/             # Plugin system (register, list, type filtering)
│   ├── scheduler/           # Task scheduler + natural language time parser
│   ├── security/            # JWT auth + rate limiter
│   ├── skills/              # Skill extraction, matching, persistence
│   └── subagents/           # Sub-agent manager, message queue, shared state
├── tests/                   # Pytest test suite (mirrors src/ structure)
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── components/      # Chat (ChatWindow, InputBox, MessageList), Layout (Header, Sidebar)
│       ├── hooks/           # useWebSocket custom hook
│       └── types/           # TypeScript interfaces
├── docs/plans/              # Design documents (Chinese)
├── thumbelina.yaml          # Default configuration
└── pyproject.toml           # Project metadata, dependencies, tool configs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/chat` | Send a message, get an agent response |
| GET | `/api/conversations` | List all conversations |
| GET | `/api/conversations/{id}` | Get conversation with messages |
| DELETE | `/api/conversations/{id}` | Delete a conversation |
| WS | `/ws/chat` | Real-time chat via WebSocket |

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

`thumbelina.yaml` — all fields optional, shown with defaults:

```yaml
llm:
  provider: openai          # openai | anthropic | ollama
  model: gpt-4o             # Model identifier
  api_key: ${OPENAI_API_KEY} # Supports ${VAR} env substitution

memory:
  database_url: sqlite:///thumbelina.db

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
| Testing | pytest, pytest-asyncio, Vitest |
| Linting | Ruff, ESLint, mypy |
