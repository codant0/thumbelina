# Thumbelina

基于 [FastAPI](https://fastapi.tiangolo.com/) 和 [LangGraph](https://langchain-ai.github.io/langgraph/) 构建的 AI 个人助手，支持多 LLM 提供商、对话记忆与技能提取、子代理编排，以及 React 实时聊天界面。

[English](README.md)

## 功能特性

- **多 LLM 提供商** — 通过统一抽象层插件式支持 OpenAI、Anthropic、Ollama
- **代理核心** — LangGraph 驱动的代理循环，支持工具调用和条件路由
- **对话记忆** — 持久化存储（SQLite），支持关键词搜索和 LLM 生成摘要
- **技能提取** — 从成功对话中自动提取可复用技能
- **子代理系统** — 并行任务执行，支持代理间消息传递和共享状态
- **任务调度器** — 自然语言时间解析（中英文），支持周期性任务
- **插件系统** — 注册和管理工具、技能、渠道、提供商
- **安全机制** — JWT 认证（HS256）和滑动窗口限流
- **备份恢复** — 基于 JSON 的备份，支持元数据信封
- **Web 界面** — React 19 + TypeScript 前端，WebSocket 实时聊天

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（前端）

### 安装

```bash
# 克隆仓库
git clone https://github.com/codant0/thumbelina.git
cd thumbelina

# 安装 Python 依赖
pip install -e ".[dev]"

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 配置

复制并编辑默认配置：

```bash
cp thumbelina.yaml my-config.yaml
```

或使用环境变量：

```bash
export OPENAI_API_KEY="sk-..."
# 或使用 Anthropic：
export ANTHROPIC_API_KEY="sk-ant-..."
```

配置优先级（从高到低）：
1. 环境变量（`THUMBELINA_*`，双下划线嵌套，如 `THUMBELINA_LLM__PROVIDER`）
2. YAML 配置文件
3. `thumbelina.yaml` 中的默认值

### 运行

```bash
# 启动 API 服务（默认：http://127.0.0.1:8000）
thumbelina-serve

# 或使用交互式 CLI（thumb 为等效快捷命令）
thumbelina
# 或
thumb

# 启动前端开发服务器
cd frontend && npm run dev
```

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│  React 前端 (Vite)                                  │
│  WebSocket /ws/chat · HTTP /api/v1/chat             │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  FastAPI 应用 (api/app.py)                          │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────┐ │
│  │ Lifespan │ │ 路由         │ │ WebSocket        │ │
│  │ (初始化) │ │ /api/v1/chat │ │ /ws/chat         │ │
│  │          │ │ /api/v1/conv…│ │                  │ │
│  └──────────┘ └──────┬───────┘ └────────┬─────────┘ │
└──────────────────────┼─────────────────┼────────────┘
                       │                 │
┌──────────────────────▼─────────────────▼────────────┐
│  ThumbelinaAgent (agent/graph.py)                   │
│  LangGraph 状态图：agent ⇄ tools                   │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────────┐
  │ LLM      │  │ 记忆     │  │ 技能 /       │
  │ 提供商   │  │ 管理器   │  │ 子代理 /     │
  │ (OpenAI, │  │ (SQLite) │  │ 调度器       │
  │  Anthr., │  │          │  │              │
  │  Ollama) │  │          │  │              │
  └──────────┘  └──────────┘  └──────────────┘
```

## 项目结构

```
thumbelina/
├── src/thumbelina/
│   ├── main.py              # FastAPI 入口（uvicorn）
│   ├── agent/               # LangGraph 代理（graph, nodes, edges, state）
│   ├── api/                 # FastAPI 应用工厂、路由、WebSocket、依赖注入
│   ├── backup/              # JSON 备份管理器
│   ├── cli/                 # Click CLI + prompt_toolkit 聊天会话
│   ├── config/              # YAML + 环境变量配置加载、Pydantic 模型
│   ├── llm/                 # LLM 提供商抽象层（OpenAI, Anthropic, Ollama）
│   ├── memory/              # 对话持久化、搜索、摘要、向量存储
│   ├── plugins/             # 插件系统（注册、列表、类型过滤）
│   ├── scheduler/           # 任务调度器 + 自然语言时间解析器
│   ├── security/            # JWT 认证 + 限流器
│   ├── skills/              # 技能提取、匹配、持久化
│   └── subagents/           # 子代理管理器、消息队列、共享状态
├── tests/                   # Pytest 测试套件（镜像 src/ 结构）
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── components/      # Chat（ChatWindow, InputBox, MessageList）、Layout（Header, Sidebar）
│       ├── hooks/           # useWebSocket 自定义 Hook
│       └── types/           # TypeScript 接口定义
├── docs/plans/              # 设计文档
├── thumbelina.yaml          # 默认配置文件
└── pyproject.toml           # 项目元数据、依赖、工具配置
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/chat` | 发送消息，获取代理响应 |
| GET | `/api/v1/conversations` | 列出所有对话 |
| GET | `/api/v1/conversations/{id}` | 获取对话详情及消息 |
| DELETE | `/api/v1/conversations/{id}` | 删除对话 |
| WS | `/ws/chat` | WebSocket 实时聊天 |

## 开发指南

### 运行测试

```bash
# 全部测试
pytest

# 指定模块
pytest tests/test_agent/

# 单个文件，首次失败即停止
pytest tests/test_api/test_chat.py -x -q

# 含覆盖率
pytest --cov=thumbelina
```

### 代码检查与类型检查

```bash
ruff check src/ tests/       # 代码检查
ruff format src/ tests/      # 代码格式化
mypy src/                    # 类型检查（严格模式）
```

### 前端开发

```bash
cd frontend
npm run dev          # 开发服务器
npm run test         # 运行测试
npm run lint         # ESLint 检查
npm run build        # 生产构建
```

## 配置参考

`thumbelina.yaml` — 所有字段可选，以下为默认值：

```yaml
llm:
  provider: openai          # openai | anthropic | ollama
  model: gpt-4o             # 模型标识
  api_key: ${OPENAI_API_KEY} # 支持 ${VAR} 环境变量替换
  request_timeout: null     # LLM 请求超时秒数，null = 不限制

auth:
  secret_key: ""            # JWT 签名密钥，非空时启用 Bearer 认证

rate_limit:
  enabled: false            # 是否启用速率限制
  max_requests: 60          # 每窗口最大请求数
  window_seconds: 60        # 时间窗口秒数

memory:
  database_url: sqlite:///thumbelina.db

logging:
  level: INFO               # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI, Uvicorn |
| 代理框架 | LangGraph, LangChain |
| LLM 提供商 | OpenAI, Anthropic, Ollama（通过 LangChain） |
| 数据库 | SQLAlchemy + SQLite |
| 向量存储 | ChromaDB |
| 认证 | PyJWT (HS256) |
| CLI | Click, prompt_toolkit |
| 前端 | React 19, TypeScript, Vite |
| 测试 | pytest, pytest-asyncio, Vitest |
| 代码检查 | Ruff, ESLint, mypy |
