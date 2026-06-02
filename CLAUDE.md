# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Thumbelina is a personal AI agent assistant built with **FastAPI** (backend) and **LangGraph** (agent framework), with a **React** frontend. It features a model-agnostic LLM provider layer, conversation memory with skill extraction, sub-agent orchestration, task scheduling, and a plugin system.

## Common Commands

### Backend (Python)

```bash
pip install -e ".[dev]"          # Install in dev mode
pytest                           # Run all tests
pytest tests/test_agent/         # Run tests for a specific module
pytest tests/test_api/test_chat.py -x -q  # Run single file, stop on first failure
ruff check src/ tests/           # Lint
ruff format src/ tests/          # Format
mypy src/                        # Type check (strict mode)
thumbelina                       # Launch CLI interactive chat
thumbelina-serve                 # Start API server on port 8000
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
Frontend (React/Vite) ──WebSocket/HTTP──> FastAPI (api/app.py)
    ├── /api/chat      → api/routes/chat.py → ThumbelinaAgent.run()
    ├── /ws/chat       → api/websocket.py   → ThumbelinaAgent.run()
    ├── /api/conversations → CRUD on MemoryManager
    └── /health
```

### Core Agent Loop (`agent/`)

`ThumbelinaAgent` builds a LangGraph `StateGraph` with an "agent" node (calls LLM) and optionally a "tools" node. The `should_continue` edge function checks for tool calls. The agent supports `run()` (single response) and `stream()` (yielding chunks).

### LLM Provider Abstraction (`llm/`)

`LLMProvider` ABC with `chat()`, `stream()`, `chat_sync()` methods. Concrete providers: `OpenAIProvider`, `AnthropicProvider`, `OllamaProvider` — all wrapping LangChain chat models. `create_provider(name)` factory with lazy imports.

### Memory System (`memory/`)

SQLAlchemy ORM (`Conversation`, `Message`) with `ConversationRepository` wrapping sync calls via `asyncio.to_thread`. `MemoryManager` adds validation (100KB content limit). Additional: `SearchEngine` (keyword search), `Summarizer` (LLM-based), `vector/` (ChromaDB).

### Dependency Injection (`api/deps.py`)

FastAPI `Depends()` pattern reading from `app.state`. `get_memory_manager(request)` and `get_agent(request)` pull instances initialized during the lifespan in `api/app.py`.

### Configuration (`config/`)

Layered merge: defaults → YAML file → `THUMBELINA_*` env vars (double-underscore nesting). Supports `${VAR}` substitution in YAML. Pydantic models validate the final config (`AppConfig`).

### Other Modules

- **skills/**: `SkillExtractor` (LLM-based extraction from conversations), `SkillApplicationEngine` (keyword + LLM matching), `SkillRepository` (SQLAlchemy persistence)
- **subagents/**: `SubagentManager` (create/list/cancel), `MessageQueue` (async inter-agent messaging), `SharedState` (lock-protected KV store)
- **scheduler/**: `TaskScheduler` (in-memory task management), `TimeParser` (dateparser + Chinese recurring patterns)
- **security/**: `AuthService` (JWT HS256 via PyJWT, min 32-byte key), `RateLimiter` (sliding window with auto-cleanup)
- **plugins/**: `PluginManager` (register/unregister/list by type)
- **backup/**: `BackupManager` (JSON file backups with metadata envelope, UUID-validated paths)

## Key Patterns

- **Source layout**: `src/thumbelina/` (PEP 621 with hatchling). Tests mirror source: `tests/test_<module>/`.
- **Async**: All public APIs are async. Sync SQLAlchemy wrapped with `asyncio.to_thread`. Pure-memory modules use async for interface consistency.
- **Testing**: `pytest` + `pytest-asyncio` + `httpx`. API tests use a shared `conftest.py` fixture that creates a `TestClient` with mocked `ThumbelinaAgent` and `MemoryManager` injected via lifespan.
- **Ruff rules**: E, F, I, N, W, UP. Line length 100. Target Python 3.11.
- **Mypy**: Strict mode enabled.

## Configuration

Default config in `thumbelina.yaml`. LLM provider defaults to `openai/gpt-4o`. Memory defaults to `sqlite:///thumbelina.db`. API key resolved from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` env vars.
