# Thumbelina

基于 [FastAPI](https://fastapi.tiangolo.com/) 和 [LangGraph](https://langchain-ai.github.io/langgraph/) 构建的 AI 个人助手，支持多 LLM 提供商、对话记忆与技能提取、子代理编排、QQ/微信频道接入，以及 React 实时聊天界面。

[English](README.md)

## 功能特性

- **多 LLM 提供商** — 通过统一抽象层插件式支持 OpenAI、Anthropic、Ollama，支持命名预设快速切换和一键连通性测试
- **LLM 预设管理** — 长期保存多种 LLM 配置（提供商、base URL、API 密钥、模型），支持自定义命名，一键激活任意预设
- **LLM 连接测试** — 三层连通性验证（网络可达 → 鉴权有效 → 服务可用），覆盖任意 provider 端点
- **DeepSeek API 兼容** — 通过 openai provider 接入，/models 端点自动降级处理
- **代理核心** — LangGraph 驱动的代理循环，支持工具调用和条件路由
- **角色提示词** — 角色人设以文件形式存放于 `prompts/roles/`（内置 assistant / coder），作为系统提示词注入；支持全局默认角色，并可在 Web 界面按对话随时切换
- **编码会话与工作区** — 创建会话时可选 `mode: chat | coder`；coder 会话绑定一个绝对工作区目录（文件/Shell 工具在该边界内解析路径，对 LLM 不可见），普通 chat 会话不允许设置工作区。目录浏览见 `GET /api/v1/fs/dirs`，Web 界面提供带工作区选择器的独立 Coder 页
- **思考模式** — 按对话开关推理/思考模式并可设强度档位，随会话持久化，经 `PUT /api/v1/conversations/{id}/thinking` 设置
- **内置工具** — 文件操作、网络请求、网络搜索（Tavily / DuckDuckGo）、Shell 命令、数据处理（JSON/CSV/文本分析/正则搜索）。工具按感知/执行/用户沟通/协作/事件触发五类组织，执行类工具带安全审查与结果自验证
- **RAG（检索增强生成）** — 文档加载、分块、向量化嵌入（llama-index + HuggingFace）、向量检索（ChromaDB）、上下文感知索引流水线
- **对话存储** — 持久化存储（SQLite），支持关键词搜索、LLM 生成摘要和对话自动命名
- **语义搜索** — 基于 ChromaDB 的向量语义搜索，支持关键词 + 语义混合回退
- **技能提取与集成** — 从成功对话中自动提取可复用技能，并在代理循环中应用
- **技能组合** — 将多个技能串联为工作流，支持 LLM 辅助建议
- **Markdown 分层记忆** — 基于 Markdown 文件系统的分层记忆，存于 `MEMORY/` 目录，人类可读、可手工编辑、可 git 审计。三层按需加载（L0 自动生成的索引摘要 / L1 概览 / L2 全文）；`MemoryExtractor` 在每轮用户消息后后台异步抽取/改写/删除记忆（NEW/UPDATE/DELETE/NOOP）；Agent 每轮注入 L0 索引摘要（视为参考数据、绝非指令），并提供 `search_memory` / `read_memory` / `remember` 三个工具；零 embedding/向量依赖；通过 `/api/v1/memory/*` 路由提供浏览、搜索与状态查询
- **子代理系统** — 并行任务执行，支持监控/工作代理、代理间消息传递和共享状态
- **任务调度器** — 自然语言时间解析（中英文），支持条件触发和通知广播
- **待办清单与随手记** — 基于本地 Markdown 文件的待办清单与随手记（`TODO/todolist.md` + `TODO/notes.md`），每项待办支持独立 Markdown 备注（块引用格式），按一级标题分组并提供分组过滤卡片，可在 Web 界面管理
- **轨迹记录** — 每轮 agent 执行轨迹（工具调用、LLM 用量）按会话持久化，Web 界面 Trajectory 页分页浏览；KV 缓存命中率汇总供状态栏展示
- **上下文压缩** — 会话上下文经 LangGraph checkpointer 持久化，可按需手动压缩（`POST /api/v1/conversations/{id}/compress`），压缩策略与 token 触发阈值经 `config.context` 配置（summary_recent / 滑动窗口）
- **插件系统** — 注册和管理工具、技能、渠道、提供商，支持沙箱验证和依赖解析
- **QQ Bot 频道** — 通过 QQ 官方 Bot SDK（`qq-botpy`）接入，支持频道、群聊和私聊
- **微信频道** — 通过 [weixin-bot](https://github.com/epiral/weixin-bot) 协议接入个人微信号，支持扫码登录
- **梦境可视化** — 技能演化时间线、成熟度图表、技能云和分类统计
- **流式 WebSocket** — 通过 WebSocket 连接实现实时逐 token 流式响应
- **安全机制** — JWT 认证（HS256）、滑动窗口限流、基于角色的访问控制、数据导出/删除
- **备份恢复** — 基于 JSON 的备份，支持元数据信封
- **Web 界面** — React 19 + TypeScript 前端，包含聊天、编码（Coder）、任务、待办、记忆、知识库（RAG 文档管理与检索测试）、轨迹、设置（LLM 预设、端点、连接与速度测试、网络搜索）、插件、频道、梦境页面。支持页面内语言切换（中文 / English）、暗色/亮色/暖色主题与按页面差异化的状态栏（含 KV 缓存命中率指示）
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

# （可选）安装 RAG 依赖（llama-index 嵌入模型与 LLM）
pip install -e ".[dev,rag]"

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 配置

启动**无需**任何 LLM 或认证配置，服务开箱即用。`thumbelina.yaml` 仅用于数据库、日志等基础设施项（可选）：

```bash
cp thumbelina.yaml.example thumbelina.yaml
```

LLM（提供商、模型、API Key）与认证在**启动后**配置：

- **LLM**：在 Web 界面「设置」页管理预设与端点（或调用 `/api/v1/config/llm` 系列 API），持久化到配置数据库，重启后自动恢复。
- **认证**：`auth.required_roles` 可在运行时通过配置 API 热更新；`auth.secret_key` 属敏感字段，仅可通过环境变量指定（≥32 字节，重启生效）。

如需在启动期覆盖，仍可使用环境变量：

```bash
# 可选：启动期注入 LLM API Key（非必需）
export THUMBELINA_LLM__API_KEY="sk-..."
# 可选：启用 JWT 认证（非空且 ≥32 字节时生效）
export THUMBELINA_AUTH__SECRET_KEY="..."
```

配置优先级（从高到低）：
1. 数据库覆盖（通过 `POST /api/v1/config` 或 `PUT /api/v1/config/llm` 设置）
2. 环境变量（`THUMBELINA_*`，双下划线嵌套，如 `THUMBELINA_LLM__PROVIDER`）
3. YAML 配置文件（`thumbelina.yaml`）
4. 代码默认值

敏感字段（API 密钥、secret_key 等）不会写入配置数据库——LLM 密钥通过端点/预设 API 管理，`secret_key` 只接受环境变量。

### 运行

```bash
# 同时启动后端和前端开发服务器
python start_dev.py
# 后端：http://localhost:8000（uvicorn，支持热重载）
# 前端：http://localhost:5173（vite）

# 或分别启动：
thumbelina-serve                # 仅启动 API 服务
cd frontend && npm run dev      # 仅启动前端

# 交互式 CLI（thumb 为等效快捷命令）
thumbelina
# 或
thumb
```

### Docker 部署

```bash
# 可选：启动期预置 LLM API Key（非必需，启动后也可在 Web 界面「设置」中配置）
export THUMBELINA_LLM__API_KEY="sk-..."

# 首次构建并启动
docker compose up -d --build
# Web 界面 + API：http://localhost:8000
```

单个容器同时运行 FastAPI 后端与构建后的 React 前端（uvicorn 直接托管静态文件，无需 nginx）。前端使用相对路径（`/api/v1/*`、`/ws/chat`），因此通过 8000 端口即可完整访问。`thumbelina.yaml` 以只读方式挂载进容器；SQLite 数据库（`sqlite:////app/data/thumbelina.db`，同时保存 LangGraph checkpoint 会话上下文）、ChromaDB 数据（`/app/data/chroma`）、HF 模型缓存与待办/随手记 Markdown 都位于 `/app/data`，默认由命名卷 `thumbelina-data` 持久化，重建容器不丢失。如需把数据存到宿主机指定目录，设置 `THUMBELINA_DATA_DIR`（如 `THUMBELINA_DATA_DIR=./data docker compose up -d --build`）即可，详见 [docs/docker-deployment.md](docs/docker-deployment.md)。

修改代码后，重建并重启：

```bash
docker compose up -d --build
```

依赖层已缓存，重建时只会重新安装发生变化的部分。完整部署指南（更新流程、备份恢复、数据迁移、FAQ、生产部署建议）见 [docs/docker-deployment.md](docs/docker-deployment.md)。

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│  React 前端 (Vite)                                           │
│  聊天 · 编码 · 任务 · 待办 · 记忆 · 知识库 · 轨迹 ·          │
│  设置 · 插件 · 频道 · 梦境                                   │
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
│  │          │ │ /api/v1/todo │ │                  │          │
│  │          │ │ /api/v1/config│ │                │          │
│  │          │ │ /api/v1/feedback│ │              │          │
│  │          │ │ /api/v1/plugins│ │               │          │
│  │          │ │ /api/v1/trajectory│ │            │          │
│  │          │ │ /api/v1/qq   │ │                  │          │
│  │          │ │ /api/v1/wechat│ │                 │          │
│  └──────────┘ └──────┬───────┘ └────────┬─────────┘          │
└───────────────────────┼─────────────────┼────────────────────┘
                        │                 │
┌───────────────────────▼─────────────────▼────────────────────┐
│  ThumbelinaAgent (agent/graph.py)                            │
│  LangGraph 状态图：agent ⇄ tools                            │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────────────────┐ │
│  │ 技能    │ │ 子代理  │ │ 调度器    │ │ 工具（五类）     │ │
│  │ 引擎    │ │ 管理器  │ │           │ │ 感知/执行/沟通/  │ │
│  │+组合    │ │+监控    │ │+条件触发  │ │ 协作/事件触发；  │ │
│  │+反馈    │ │+工作    │ │+通知      │ │ 执行类带审查+自 │ │
│  │         │ │         │ │           │ │ 验证+fs/网络/搜 │ │
│  │         │ │         │ │           │ │ 索/Shell/数据   │ │
│  └─────────┘ └─────────┘ └───────────┘ └──────────────────┘ │
│  ┌──────────────┐ ┌──────────────────┐                       │
│  │ 记忆         │ │ 技能上下文       │                       │
│  │ (L0 索引     │ │ (注入为          │                       │
│  │  注入)       │ │  SystemMessage)  │                       │
│  └──────────────┘ └──────────────────┘                       │
└───────────────────────────┬──────────────────────────────────┘
                            │
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
     ┌──────────┐   ┌──────────┐   ┌──────────────┐
     │ LLM      │   │ 存储     │   │ 技能 /       │
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
│   ├── repository/          # 对话持久化、搜索、向量存储、反馈、轨迹
│   ├── analysis/            # LLM 分析服务：标题摘要、对话命名
│   ├── filestore/           # 公共原子文件 I/O + 按 key 异步文件锁（todo/memory 复用）
│   ├── memory/              # Markdown 分层记忆（L0/L1/L2、抽取器、检索、工具）
│   ├── notifications.py     # WebSocket 通知广播
│   ├── plugins/             # 插件系统（注册、沙箱验证、依赖解析）
│   ├── prompts/roles/       # 角色人设 Markdown 文件（assistant、coder）
│   ├── rag/                 # RAG：文档加载、分块、嵌入、检索、索引流水线
│   │   ├── embedding/       # 嵌入模型抽象层（HuggingFace、ChromaDB 向量存储、注册中心）
│   │   ├── ingestion/       # 文档加载器与分块器
│   │   ├── knowledge_base/  # KnowledgeBase、Document、Chunk 模型与仓库
│   │   ├── pipeline/        # 文档索引流水线
│   │   └── retrieval/       # 检索策略与上下文格式化
│   ├── scheduler/           # 任务调度器 + 自然语言时间解析器 + 条件触发
│   ├── security/            # JWT 认证 + 限流器 + RBAC
│   ├── skills/              # 技能提取、匹配、组合、持久化
│   ├── subagents/           # 子代理管理器、监控/工作代理、消息队列、共享状态
│   ├── todo/                # Markdown 待办清单与随手记服务
│   └── tools/               # 内置工具，按五类分类体系组织：base.py（ThumbelinaBaseTool 模板生命周期）+ perception / execution / communication / collaboration / event 模块；执行类工具强制安全审查 + 结果自验证
├── tests/                   # Pytest 测试套件（镜像 src/ 结构）
├── frontend/                # React 19 + TypeScript + Vite
│   └── src/
│       ├── api/             # API 客户端模块（conversations, llmConfig）
│       ├── components/
│       │   ├── Channels/    # ChannelsPage（QQ/微信配置与状态）
│       │   ├── Chat/        # ChatWindow, InputBox, MessageList, KnowledgeBaseSelector
│       │   ├── Coder/       # CoderPage, CoderSidebar, WorkspacePicker（工作区编码会话）
│       │   ├── Dream/       # 技能演化可视化
│       │   ├── KnowledgeBase/ # KnowledgeBasePage（知识库 CRUD、文档管理、检索测试）
│       │   ├── Layout/      # Header, Sidebar, ThemeToggle（暗色/亮色/暖色）
│       │   ├── Memory/      # MemoryViewer（搜索 + 技能浏览）
│       │   ├── Plugins/     # PluginsPage（插件列表 + 沙箱报告）
│       │   ├── Settings/    # LLM 端点/预设管理、连接测试、速度测试、网络搜索配置
│       │   ├── StatusBar/   # 按页面差异化的状态栏组件
│       │   ├── Tasks/       # TaskManager（子代理 + 定时任务）
│       │   ├── Todo/        # TodoPage（待办清单 + 随手记，按标题分组）
│       │   └── Trajectory/  # TrajectoryPage, TrajectoryDetailModal（执行轨迹回放）
│       ├── hooks/           # useWebSocket 自定义 Hook
│       ├── i18n/            # 国际化（en, zh-CN）与 LocaleContext
│       ├── test/            # 测试配置
│       └── types/           # TypeScript 接口定义
├── docs/specs/              # 设计规范文档
├── docs/plans/              # 实施计划文档
├── docs/review/             # 审查记录
├── Dockerfile               # 多阶段镜像：构建前端，后端一并托管
├── docker-compose.yml       # 单容器部署
├── thumbelina.yaml.example  # 示例配置文件
└── pyproject.toml           # 项目元数据、依赖、工具配置
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（返回版本 + 数据库状态） |
| POST | `/api/v1/chat` | 发送消息，获取代理响应 |
| GET | `/api/v1/conversations` | 列出所有对话 |
| POST | `/api/v1/conversations` | 创建新对话（`mode: chat \| coder`；coder 必填 `workspace`） |
| GET | `/api/v1/conversations/search/{query}` | 跨对话搜索消息 |
| GET | `/api/v1/conversations/{id}` | 获取对话详情及消息 |
| PATCH | `/api/v1/conversations/{id}` | 重命名对话 |
| PUT | `/api/v1/conversations/{id}/endpoint` | 设置对话使用的 LLM 端点和模型 |
| PUT | `/api/v1/conversations/{id}/role` | 设置对话使用的角色（`null` = 恢复全局默认） |
| PUT | `/api/v1/conversations/{id}/knowledge-base` | 为对话绑定 RAG 知识库 |
| PUT | `/api/v1/conversations/{id}/thinking` | 设置对话的思考模式（开关 + 强度档位） |
| POST | `/api/v1/conversations/{id}/compress` | 手动压缩对话上下文 |
| DELETE | `/api/v1/conversations/{id}/messages` | 删除对话的全部消息 |
| DELETE | `/api/v1/conversations/{id}` | 删除对话 |
| GET | `/api/v1/fs/dirs` | 列举目录（工作区选择器用） |
| GET | `/api/v1/tasks` | 列出定时任务 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消定时任务 |
| GET | `/api/v1/subagents` | 列出活跃子代理 |
| POST | `/api/v1/subagents/{id}/cancel` | 取消运行中的子代理 |
| GET | `/api/v1/skills` | 列出已提取技能 |
| GET | `/api/v1/skills/stats` | 技能使用统计（梦境可视化） |
| GET | `/api/v1/compositions` | 列出技能组合 |
| GET | `/api/v1/trajectory/{conversation_id}` | 分页获取对话的 agent 执行轨迹 |
| GET | `/api/v1/trajectory/cache-stats` | KV 缓存命中率汇总（状态栏用） |
| POST | `/api/v1/feedback` | 提交用户反馈（评分 1-5） |
| GET | `/api/v1/feedback` | 列出反馈记录 |
| GET | `/api/v1/feedback/stats` | 反馈统计 |
| GET | `/api/v1/data/export` | 导出所有用户数据（对话 + 记忆） |
| DELETE | `/api/v1/data/all` | 删除所有用户数据（对话 + 记忆） |
| GET | `/api/v1/memory/index` | 查看 L0 记忆索引（自动生成的摘要清单） |
| GET | `/api/v1/memory/entries` | 按分类列出全部记忆条目 |
| GET | `/api/v1/memory/search?q=` | 基于字符 n-gram 的记忆摘要检索（L0 triage） |
| GET | `/api/v1/memory/{category}/{slug}?depth=` | 分层读取单条记忆：`overview`（L1）或 `full`（L2） |
| POST | `/api/v1/memory/refresh` | 从磁盘重建记忆索引 |
| GET | `/api/v1/memory/status` | 记忆子系统状态（是否启用、条目数、字节量） |
| GET | `/api/v1/plugins` | 列出已加载插件（含沙箱状态） |
| GET | `/api/v1/plugins/sandbox-report` | 插件沙箱验证报告 |
| GET | `/api/v1/plugins/dependencies` | 插件依赖图 |
| GET | `/api/v1/roles` | 列出可用角色（提示词位于 `prompts/roles/`） |
| GET | `/api/v1/config` | 获取当前配置快照 |
| POST | `/api/v1/config` | 更新运行时配置 |
| PUT | `/api/v1/config/llm` | 热切换 LLM 提供商/模型 |
| GET | `/api/v1/config/llm/presets` | 列出已保存的 LLM 预设 |
| POST | `/api/v1/config/llm/presets` | 创建新的 LLM 预设 |
| GET | `/api/v1/config/llm/presets/{id}` | 获取单个 LLM 预设 |
| PUT | `/api/v1/config/llm/presets/{id}` | 更新 LLM 预设 |
| DELETE | `/api/v1/config/llm/presets/{id}` | 删除 LLM 预设 |
| POST | `/api/v1/config/llm/presets/{id}/activate` | 激活预设（热切换） |
| GET | `/api/v1/config/llm/models` | 从远程端点获取可用模型列表 |
| POST | `/api/v1/config/llm/test-connection` | 测试任意 provider 参数连通性 |
| GET | `/api/v1/config/llm/endpoints` | 列出已保存的 LLM 端点 |
| POST | `/api/v1/config/llm/endpoints` | 创建新的 LLM 端点 |
| PUT | `/api/v1/config/llm/endpoints/{id}` | 更新 LLM 端点 |
| DELETE | `/api/v1/config/llm/endpoints/{id}` | 删除 LLM 端点 |
| POST | `/api/v1/config/llm/endpoints/{id}/speed-test` | 对已保存端点运行速度测试 |
| POST | `/api/v1/config/llm/endpoints/{id}/test-connection` | 对已保存端点运行连通性测试 |
| POST | `/api/v1/config/llm/endpoints/{id}/activate` | 全局激活已保存端点（热切换 LLM） |
| PUT | `/api/v1/config/channels/{name}` | 热切换频道配置 |
| GET | `/api/v1/config/tools` | 当前工具配置（网络搜索提供商、是否已设密钥） |
| PUT | `/api/v1/config/tools/web_search` | 更新网络搜索配置（热生效） |
| GET | `/api/v1/todo/status` | TODO 模块状态（是否启用、文件路径、计数） |
| GET | `/api/v1/todo/items` | 列出待办项（`TodoItemsOut`，条目携带来源标题分组 `group`） |
| POST | `/api/v1/todo/items` | 新增待办项 |
| PATCH | `/api/v1/todo/items/{index}` | 更新待办项（text / done / remark） |
| DELETE | `/api/v1/todo/items/{index}` | 删除待办项 |
| GET | `/api/v1/todo/notes` | 列出随手记 |
| POST | `/api/v1/todo/notes` | 新增随手记 |
| PUT | `/api/v1/todo/notes/{index}` | 更新随手记 |
| DELETE | `/api/v1/todo/notes/{index}` | 删除随手记 |
| GET | `/api/v1/config/export` | 从数据库导出配置 |
| POST | `/api/v1/config/reload` | 从数据库重新加载配置 |
| GET | `/api/v1/qq/status` | 检查 QQ Bot 连接状态 |
| POST | `/api/v1/wechat/incoming` | iLink webhook（接收微信消息） |
| POST | `/api/v1/wechat/send` | 通过 iLink 发送消息 |
| GET | `/api/v1/wechat/status` | 检查 iLink 连接状态 |
| POST | `/api/v1/wechat/qrcode` | 获取微信登录二维码 |
| GET | `/api/v1/wechat/qrcode/status` | 轮询二维码扫描状态 |
| POST | `/api/v1/wechat/qrcode/confirm` | 确认登录并启用频道 |
| GET | `/api/v1/rag/knowledge-bases` | 列出所有 RAG 知识库 |
| POST | `/api/v1/rag/knowledge-bases` | 创建知识库 |
| PUT | `/api/v1/rag/knowledge-bases/{id}` | 更新知识库 |
| DELETE | `/api/v1/rag/knowledge-bases/{id}` | 删除知识库（级联） |
| GET | `/api/v1/rag/knowledge-bases/{id}/documents` | 列出知识库中的文档 |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents` | 上传文档（异步，返回任务 id） |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents/url` | 按 URL 上传网页（异步） |
| POST | `/api/v1/rag/knowledge-bases/{id}/documents/batch` | 批量上传文档（异步） |
| GET | `/api/v1/rag/upload-tasks/{task_id}` | 获取上传任务状态与进度 |
| GET | `/api/v1/rag/knowledge-bases/{id}/upload-tasks` | 列出知识库的上传任务 |
| DELETE | `/api/v1/rag/upload-tasks/{task_id}` | 取消或关闭上传任务 |
| DELETE | `/api/v1/rag/documents/{id}` | 删除文档 |
| GET | `/api/v1/rag/documents/{id}/chunks` | 列出文档的分块 |
| POST | `/api/v1/rag/query` | 检索 top-k 相关分块 |
| POST | `/api/v1/rag/documents/simhash-query` | 跨文档 SimHash 近似重复检索 |
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
rate_limit:
  enabled: false            # 是否启用速率限制
  max_requests: 60          # 每窗口最大请求数
  window_seconds: 60        # 时间窗口秒数

repository:
  database_url: sqlite:///thumbelina.db

logging:
  level: INFO               # DEBUG | INFO | WARNING | ERROR | CRITICAL

todo:
  enabled: true             # 是否启用 TODO 模块（本地 Markdown 待办清单与随手记）
  directory: TODO           # todolist.md / notes.md 所在目录

tools:
  web_search:
    enabled: true           # 向代理暴露 web_search 工具
    provider: tavily        # tavily | duckduckgo
    api_key: ""             # 仅 Tavily 需要；保存到配置数据库
```

> `llm` 与 `auth` 不再是启动配置：
> - **llm.\*** — 启动后在 Web 界面「设置」或经 `/api/v1/config/llm` 系列 API 管理（预设/端点持久化到配置数据库）。
> - **auth.required_roles** — 可通过配置 API 运行时热更新。
> - **auth.secret_key** — 敏感字段，仅接受环境变量 `THUMBELINA_AUTH__SECRET_KEY`（≥32 字节，重启生效）；为空时认证自动禁用。
>
> **网络搜索工具** — `tools.web_search` 选择搜索后端：
> - `tavily`（默认）— 返回对 LLM 友好的答案；需要 API Key，在 Web 界面「设置 → 工具」配置并保存到配置数据库（仅此工具的敏感密钥策略例外）。
> - `duckduckgo` — 无需 API Key；需 `pip install -e ".[web]"`（安装 `ddgs`）。
> `enabled`、`provider` 与 `api_key` 均可经 `PUT /api/v1/config/tools/web_search` 运行时热更新。

以下部分为可选配置——在 `thumbelina.yaml` 中取消注释即可启用：

```yaml
# cors_origins: ["*"]         # CORS 允许的来源；生产环境应限制域名

# plugin_dirs: []             # 插件扫描目录

# channels:
#   qq:
#     enabled: false
#     app_id: ""
#     app_secret: ""
#     allowed_guilds: []
#     allowed_groups: []
#   wechat:
#     enabled: false
#     bot_token: ""             # iLink 机器人令牌
#     ilink_bot_id: ""          # iLink 机器人 ID
#     ilink_user_id: ""         # iLink 用户 ID
#     ilink_base_url: "https://ilinkai.weixin.qq.com"
#     webhook_secret: ""
```

### Markdown 记忆

`thumbelina.yaml` 中的 `memory:` 段配置分层 Markdown 记忆子系统（完整字段注释见 `thumbelina.yaml.example`）。关键字段：

```yaml
memory:
  enabled: true               # 关闭后路由与注入整体禁用（路由返回 503）
  directory: MEMORY           # 记忆目录（相对工作目录）；存放 index.md + <category>/<slug>.md
  categories: [user, project, decision, topic]  # 分类白名单；白名单外目录被忽略
  inject_index: true          # 每轮注入 L0 索引摘要
  inject_top_k: 8             # 索引超过 index_token_cap 时仅注入相关性前 K 条
  index_token_cap: 3000        # 索引摘要全量注入的 token 上限（estimate_tokens 口径）
  max_full_tokens: 4000       # read_full（L2）单条注入上限，超限截断
  max_entries: 200            # 记忆条目总量护栏
  max_total_bytes: 5_000_000  # 记忆目录总字节护栏
  extract:
    enabled: true             # 后台 LLM 抽取/改写（每轮用户消息后异步触发）
    on_user_message: true     # 仅对用户消息触发抽取
    min_message_chars: 5      # 消息低于该字符数不触发抽取（排除"好的/谢谢"等语气词）
    max_input_tokens: 8000    # 单次抽取输入 token 预算
  tools:
    enabled: true             # 向 Agent 暴露 search_memory / read_memory / remember
```

### 角色提示词

角色提示词文件位于 `src/thumbelina/prompts/roles/`，新增角色只需添加 `<role>.md` 文件：

- **全局默认角色**：代码默认 `assistant`，可用环境变量 `THUMBELINA_LLM__ROLE` 覆盖。
- **按对话切换**：对话级角色优先于全局默认，可通过 Web 界面输入框工具栏的角色选择器切换，或调用 `PUT /api/v1/conversations/{id}/role`（传 `null` 恢复全局默认）。
- 内置角色：`assistant`（个人助理）、`coder`（软件工程师）。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI, Uvicorn, httpx |
| 代理框架 | LangGraph, LangChain |
| LLM 提供商 | OpenAI, Anthropic, Ollama（通过 LangChain） |
| RAG | llama-index-core（嵌入模型、向量检索） |
| 数据库 | SQLAlchemy + SQLite |
| 向量存储 | ChromaDB |
| 认证 | PyJWT (HS256) |
| CLI | Click, prompt_toolkit |
| 前端 | React 19, TypeScript, Vite |
| IM 频道 | qq-botpy（QQ）、weixin-bot（微信） |
| 测试 | pytest, pytest-asyncio, Vitest |
| 代码检查 | Ruff, ESLint, mypy |
| 容器 | Docker, docker-compose |
