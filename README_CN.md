# Thumbelina

基于 [FastAPI](https://fastapi.tiangolo.com/) 和 [LangGraph](https://langchain-ai.github.io/langgraph/) 构建的 AI 个人助手，支持多 LLM 提供商、对话记忆与技能提取、子代理编排、QQ/微信频道接入，以及 React 实时聊天界面。

[English](README.md)

## 功能特性

- **多 LLM 提供商** — 通过统一抽象层插件式支持 OpenAI、Anthropic、Ollama
- **代理核心** — LangGraph 驱动的代理循环，支持工具调用和条件路由
- **内置工具** — 文件操作、网络请求、Shell 命令、数据处理（JSON/CSV/文本分析）
- **对话记忆** — 持久化存储（SQLite），支持关键词搜索和 LLM 生成摘要
- **语义搜索** — 基于 ChromaDB 的向量语义搜索，支持关键词 + 语义混合回退
- **技能提取与集成** — 从成功对话中自动提取可复用技能，并在代理循环中应用
- **技能组合** — 将多个技能串联为工作流，支持 LLM 辅助建议
- **用户建模** — 分析对话模式，构建用户偏好画像，实现个性化响应
- **用户反馈** — 对技能响应评分（1-5 星），分数自动调整技能匹配优先级
- **子代理系统** — 并行任务执行，支持监控/工作代理、代理间消息传递和共享状态
- **任务调度器** — 自然语言时间解析（中英文），支持条件触发和通知广播
- **插件系统** — 注册和管理工具、技能、渠道、提供商，支持沙箱验证和依赖解析
- **QQ Bot 频道** — 通过 QQ 官方 Bot SDK（`qq-botpy`）接入，支持频道、群聊和私聊
- **微信频道** — 通过 [weixin-bot](https://github.com/epiral/weixin-bot) 协议接入个人微信号，支持扫码登录
- **梦境可视化** — 技能演化时间线、成熟度图表、技能云和分类统计
- **流式 WebSocket** — 通过 WebSocket 连接实现实时逐 token 流式响应
- **安全机制** — JWT 认证（HS256）、滑动窗口限流、基于角色的访问控制、数据导出/删除
- **备份恢复** — 基于 JSON 的备份，支持元数据信封
- **Web 界面** — React 19 + TypeScript 前端，包含聊天、任务、记忆、设置、插件、频道、梦境七个页面
- **Docker** — 容器化部署，支持 docker-compose

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

复制示例配置文件并编辑：

```bash
cp thumbelina.yaml.example thumbelina.yaml
```

或使用环境变量：

```bash
export OPENAI_API_KEY="sk-..."
# 或使用 Anthropic：
export ANTHROPIC_API_KEY="sk-ant-..."
```

配置优先级（从高到低）：
1. 数据库覆盖（通过 `POST /api/v1/config` 或 `PUT /api/v1/config/llm` 设置）
2. 环境变量（`THUMBELINA_*`，双下划线嵌套，如 `THUMBELINA_LLM__PROVIDER`）
3. YAML 配置文件（`thumbelina.yaml`）
4. `thumbelina.yaml.example` 中的默认值

敏感字段（API 密钥、Token 等）不存储在数据库中，请使用环境变量。

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

### Docker 部署

```bash
docker-compose up -d
```

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│  React 前端 (Vite)                                           │
│  聊天 · 任务 · 记忆 · 设置 · 插件 · 频道 · 梦境              │
│  WebSocket /ws/chat (流式) · HTTP /api/v1/*                  │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI 应用 (api/app.py)                                   │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────┐          │
│  │ Lifespan │ │ 路由         │ │ WebSocket        │          │
│  │ (初始化) │ │ /api/v1/chat │ │ /ws/chat         │          │
│  │          │ │ /api/v1/conv…│ │ (流式)           │          │
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
│  LangGraph 状态图：agent ⇄ tools                            │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────────┐         │
│  │ 技能    │ │ 子代理  │ │ 调度器    │ │ 工具     │         │
│  │ 引擎    │ │ 管理器  │ │           │ │ (文件,   │         │
│  │+组合    │ │+监控    │ │+条件触发  │ │  网络,   │         │
│  │+反馈    │ │+工作    │ │+通知      │ │  Shell,  │         │
│  │         │ │         │ │           │ │  数据)   │         │
│  └─────────┘ └─────────┘ └───────────┘ └──────────┘         │
│  ┌──────────────┐ ┌──────────────────┐                       │
│  │ 用户建模器   │ │ 技能上下文       │                       │
│  │ (偏好画像)   │ │ (注入为          │                       │
│  │              │ │  SystemMessage)  │                       │
│  └──────────────┘ └──────────────────┘                       │
└───────────────────────────┬──────────────────────────────────┘
                            │
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
     ┌──────────┐   ┌──────────┐   ┌──────────────┐
     │ LLM      │   │ 记忆     │   │ 技能 /       │
     │ 提供商   │   │ 管理器   │   │ 子代理 /     │
     │ (OpenAI, │   │ (SQLite, │   │ 调度器 /     │
     │  Anthr., │   │  Chroma) │   │ 频道         │
     │  Ollama) │   │          │   │ (QQ, 微信)   │
     └──────────┘   └──────────┘   └──────────────┘
```

## 项目结构

```
thumbelina/
├── src/thumbelina/
│   ├── main.py              # FastAPI 入口（uvicorn）
│   ├── agent/               # LangGraph 代理（graph, nodes, edges, state）
│   ├── api/                 # FastAPI 应用工厂、路由、WebSocket、依赖注入
│   ├── backup/              # JSON 备份管理器
│   ├── channels/            # IM 频道（QQ Bot、微信 via weixin-bot）
│   ├── cli/                 # Click CLI + prompt_toolkit 聊天会话
│   ├── config/              # YAML + 环境变量配置加载、Pydantic 模型
│   ├── llm/                 # LLM 提供商抽象层（OpenAI, Anthropic, Ollama）
│   ├── memory/              # 对话持久化、搜索、摘要、向量存储、用户建模、反馈
│   ├── notifications/       # WebSocket 通知广播
│   ├── plugins/             # 插件系统（注册、沙箱验证、依赖解析）
│   ├── scheduler/           # 任务调度器 + 自然语言时间解析器 + 条件触发
│   ├── security/            # JWT 认证 + 限流器 + RBAC
│   ├── skills/              # 技能提取、匹配、组合、持久化
│   ├── subagents/           # 子代理管理器、监控/工作代理、消息队列、共享状态
│   └── tools/               # 内置工具（文件操作、网络请求、Shell、数据处理）
├── tests/                   # Pytest 测试套件（镜像 src/ 结构）
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── components/
│       │   ├── Channels/    # ChannelsPage（QQ/微信配置与状态）
│       │   ├── Chat/        # ChatWindow, InputBox, MessageList
│       │   ├── Dream/       # 技能演化可视化
│       │   ├── Layout/      # Header, Sidebar
│       │   ├── Memory/      # MemoryViewer（搜索 + 技能浏览）
│       │   ├── Plugins/     # PluginsPage（插件列表 + 沙箱报告）
│       │   ├── Settings/    # SettingsPanel（LLM 配置、数据管理）
│       │   └── Tasks/       # TaskManager（子代理 + 定时任务）
│       ├── hooks/           # useWebSocket 自定义 Hook
│       └── types/           # TypeScript 接口定义
├── docs/plans/              # 设计文档
├── Dockerfile               # 后端容器
├── Dockerfile.frontend      # 前端容器（nginx）
├── docker-compose.yml       # 多容器部署
├── thumbelina.yaml.example  # 示例配置文件
└── pyproject.toml           # 项目元数据、依赖、工具配置
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（返回版本 + 数据库状态） |
| POST | `/api/v1/chat` | 发送消息，获取代理响应 |
| GET | `/api/v1/conversations` | 列出所有对话 |
| POST | `/api/v1/conversations` | 创建新对话 |
| GET | `/api/v1/conversations/search/{query}` | 跨对话搜索消息 |
| GET | `/api/v1/conversations/{id}` | 获取对话详情及消息 |
| DELETE | `/api/v1/conversations/{id}` | 删除对话 |
| GET | `/api/v1/tasks` | 列出定时任务 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消定时任务 |
| GET | `/api/v1/subagents` | 列出活跃子代理 |
| POST | `/api/v1/subagents/{id}/cancel` | 取消运行中的子代理 |
| GET | `/api/v1/skills` | 列出已提取技能 |
| GET | `/api/v1/skills/stats` | 技能使用统计（梦境可视化） |
| GET | `/api/v1/compositions` | 列出技能组合 |
| POST | `/api/v1/feedback` | 提交用户反馈（评分 1-5） |
| GET | `/api/v1/feedback` | 列出反馈记录 |
| GET | `/api/v1/feedback/stats` | 反馈统计 |
| GET | `/api/v1/data/export` | 导出所有用户数据 |
| DELETE | `/api/v1/data/all` | 删除所有用户数据 |
| GET | `/api/v1/user/profile` | 获取用户画像和偏好 |
| GET | `/api/v1/plugins` | 列出已加载插件（含沙箱状态） |
| GET | `/api/v1/plugins/sandbox-report` | 插件沙箱验证报告 |
| GET | `/api/v1/plugins/dependencies` | 插件依赖图 |
| GET | `/api/v1/config` | 获取当前配置快照 |
| POST | `/api/v1/config` | 更新运行时配置 |
| PUT | `/api/v1/config/llm` | 热切换 LLM 提供商/模型 |
| PUT | `/api/v1/config/channels/{name}` | 热切换频道配置 |
| GET | `/api/v1/config/export` | 从数据库导出配置 |
| POST | `/api/v1/config/reload` | 从数据库重新加载配置 |
| GET | `/api/v1/qq/status` | 检查 QQ Bot 连接状态 |
| POST | `/api/v1/wechat/incoming` | iLink webhook（接收微信消息） |
| POST | `/api/v1/wechat/send` | 通过 iLink 发送消息 |
| GET | `/api/v1/wechat/status` | 检查 iLink 连接状态 |
| POST | `/api/v1/wechat/qrcode` | 获取微信登录二维码 |
| GET | `/api/v1/wechat/qrcode/status` | 轮询二维码扫描状态 |
| POST | `/api/v1/wechat/qrcode/confirm` | 确认登录并启用频道 |
| WS | `/ws/chat` | WebSocket 流式实时聊天 |

## QQ Bot 接入

1. 访问 [q.qq.com](https://q.qq.com) 注册开发者并创建机器人应用
2. 获取 AppID 和 AppSecret
3. 在 `thumbelina.yaml` 中添加：
   ```yaml
   channels:
     qq:
       enabled: true
       app_id: "your_app_id"
       app_secret: "your_app_secret"
   ```
4. 启动 Thumbelina：`thumbelina-serve`

## 微信接入

微信集成使用 [weixin-bot](https://github.com/epiral/weixin-bot) 协议直接调用 iLink API，无需额外的 sidecar 进程。

### 方式 A：扫码登录（推荐）

1. 启动 Thumbelina：`thumbelina-serve`
2. 调用 `POST /api/v1/wechat/qrcode` 获取二维码
3. 微信扫码
4. 轮询 `GET /api/v1/wechat/qrcode/status` 直到状态为 `confirmed`
5. 调用 `POST /api/v1/wechat/qrcode/confirm` 保存凭据并启用频道

### 方式 B：手动配置

在 `thumbelina.yaml` 中添加：
```yaml
channels:
  wechat:
    enabled: true
    bot_token: "your_bot_token"
    ilink_bot_id: "your_bot_id"
    ilink_user_id: "your_user_id"
    ilink_base_url: "https://ilinkai.weixin.qq.com"
```

### 协议参考

本实现遵循 [weixin-bot 协议规范](https://github.com/epiral/weixin-bot/blob/main/docs/protocol-spec.md)：
- 通过 `POST /ilink/bot/getupdates` 进行长轮询（约 35 秒）
- `context_token` 是消息投递的必要条件（自动管理）
- 会话过期（`errcode=-14`）需要重新扫码认证
- `X-WECHAT-UIN` 必须是 base64 编码（按协议规范）

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

`thumbelina.yaml.example` — 所有字段可选，以下为默认值：

```yaml
llm:
  provider: openai          # openai | anthropic | ollama
  model: gpt-4o             # 模型标识
  api_key: ${OPENAI_API_KEY} # 支持 ${VAR} 环境变量替换
  base_url: null            # 自定义 API 端点 URL
  request_timeout: null     # LLM 请求超时秒数
  streaming_enabled: true   # 启用 WebSocket 流式响应

cors_origins: ["*"]         # CORS 允许的来源；生产环境应限制域名

auth:
  secret_key: ""            # JWT 签名密钥，非空时启用 Bearer 认证
  required_roles: []        # 全局角色列表，空 = 允许所有已认证用户

rate_limit:
  enabled: false            # 是否启用速率限制
  max_requests: 60          # 每窗口最大请求数
  window_seconds: 60        # 时间窗口秒数

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
    bot_token: ""             # iLink 机器人令牌
    ilink_bot_id: ""          # iLink 机器人 ID
    ilink_user_id: ""         # iLink 用户 ID
    ilink_base_url: "https://ilinkai.weixin.qq.com"
    webhook_secret: ""

plugin_dirs: []             # 插件扫描目录

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
| IM 频道 | qq-botpy（QQ）、weixin-bot（微信） |
| 测试 | pytest, pytest-asyncio, Vitest |
| 代码检查 | Ruff, ESLint, mypy |
| 容器 | Docker, docker-compose |
