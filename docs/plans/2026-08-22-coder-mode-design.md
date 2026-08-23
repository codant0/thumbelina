# 码农（Coder）模式设计

- 日期：2026-08-22
- 状态：已批准
- 范围：WEB 顶部导航"聊天"右侧新增"码农"入口，提供绑定服务器工作区的 Code Agent 会话

## 背景与目标

现有聊天会话不区分用途，也没有"项目/工作区"概念。码农场景要求：

1. 创建新会话前必须先选择工作区（服务器上的系统目录），工作区信息注入系统提示词；
2. 左侧会话列表按工作区分组，组内才是各个对话；
3. 码农模式的对话与普通对话通过类型区分；
4. 码农模式下默认角色为 `coder`（`prompts/roles/coder.md` 已存在）。

经确认的边界决策：

| 决策点 | 结论 |
|---|---|
| 工作区来源 | 服务器任意目录；服务器端与客户端同机部署，前端用原生目录选择器，不新增目录浏览接口 |
| 能力范围 | 工作区上下文 + 角色闭环；复用现有工具并按有无工作区做边界校验，新增 `search_files` 补齐磁盘搜索 |
| 会话-工作区绑定 | 创建时固定，之后不可变 |
| 页面形态 | 独立"码农"页 + 独立侧栏（按工作区分组）；普通"聊天"页保持扁平列表 |
| 实现路线 | 方案 A：轻量复用——`conversations` 表加 `mode`/`workspace` 字段，复用现有会话/角色/工具/检查点管线 |

## 数据模型与迁移

`repository/models.py` 的 `Conversation` 新增两列，借助 `ensure_schema` 启动时自动 `ALTER TABLE`，无需 Alembic：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `mode` | `String(20)` | `'chat'` | `'chat'`（普通）/ `'coder'`（码农），存量会话默认普通 |
| `workspace` | `String(500)` | `NULL` | 码农会话绑定的工作区绝对路径；普通会话恒为 `NULL` |

不变式：

- `workspace` 创建时 `Path(workspace).resolve()` 规范化（Windows 统一大小写与分隔符），并校验目录存在且可读，否则 422；
- 创建后 `mode` 与 `workspace` 不可变：`PATCH /conversations/{id}` 只接受 `name`；
- 码农会话必须带 `workspace`；普通会话不允许带 `workspace`（后端校验）。

API Schema 同步：`CreateConversationRequest` 增加 `mode`（默认 `'chat'`）与 `workspace`；`ConversationSchema` / `ConversationDetailSchema`（`api/schemas.py`）与前端 `types/chat.ts` 的 `Conversation` 类型补两字段；`GET /api/v1/conversations` 增加可选 `mode` 过滤参数。

## 后端 API

不新增浏览端点。工作区路径由前端输入框获得（同机部署，原生目录选择器仅辅助确认目录存在并回填目录名提示，最终路径以输入为准）；`POST /conversations` 时后端统一校验：`mode=coder` 必须携带 `workspace`，`resolve()` 后校验目录存在且可读，否则 422（附清晰文案）。

- `POST /conversations`：接受 `mode` + `workspace`；`mode=coder` 且未指定角色时默认 `role='coder'`；
- `GET /conversations?mode=chat|coder`：过滤；
- 删除会话照旧清理 LangGraph checkpoint；重命名、压缩等其余端点不变。

运行时注入无新增端点：`apply_conversation_runtime`（`api/routes/chat.py`）扩展，读取会话 `workspace` 写入 agent 克隆（如 `agent.workspace`），供系统提示词拼接与工具校验使用。

## 前端

导航与路由（`App.tsx` / `Header.tsx`）：

- `Page` 联合类型新增 `'coder'`，`navKeys` 紧随 `'chat'`；图标 `Code2`（lucide-react）；
- i18n 新增 `nav.coder`：中文「码农」、英文「Coder」，`en.json` 与 `zh-CN.json` 都加；
- `renderPage()` 新增 `case 'coder'` 渲染 `CoderPage`；
- 复用现有 `/ws/chat` 连接（`App.tsx` 持有，按 `selectedId` 切换），码农会话与普通会话共用同一条聊天管线，切页不断流。

新组件（`components/Coder/`）：

- `CoderPage.tsx`：`CoderSidebar` + 复用 `ChatWindow`；无会话时显示空态引导；
- `CoderSidebar.tsx`：按 `workspace` 分组——组头显示目录名（悬停显示完整路径），组内按 `updated_at` 倒序，组按最近活跃排序，可折叠；顶部「新建会话」按钮；复用现有重命名/删除逻辑；
- `WorkspacePicker.tsx`：新建会话弹窗——路径输入框 + 「选择目录」辅助按钮（原生 `showDirectoryPicker`）；提交 `POST /conversations {mode:'coder', workspace}`，422 在弹窗内提示；成功后自动选中新会话。

数据流：

- 普通聊天页拉 `GET /conversations?mode=chat`，码农页拉 `mode=coder`，互相不可见；
- 新建码农会话默认 `role='coder'`，之后可用现有 `RoleSelector` 手动改角色；
- 选中会话沿用 `App.tsx` 的 `selectedId` 单一事实源。

## 工作区上下文注入与工具改造

系统提示词注入：

- `agent/graph.py::_build_initial_messages` 首轮追加一条工作区 SystemMessage（沿用"仅首轮注入、检查点持久化"模式），内容：工作区绝对路径、顶层目录快照（深度 1、最多约 50 条，生成失败则退化为仅路径）、约束说明"文件类工具的相对路径以该工作区为根，禁止越界"；
- 注入内容写入轨迹（沿用 `record_context`）。

工具改造（复用原函数，按有无工作区分支）：

- `tools/file_ops.py` 与 `tools/shell.py` 的原函数增加可选 `workspace` 参数（默认 `None` = 现状行为）：
  - 有 `workspace`：相对路径按其解析，`resolve()` 后校验 `is_relative_to`，越界返回错误文本；`run_shell` 附加 `cwd=workspace`；
  - 无 `workspace`：行为完全不变，普通会话零影响；
- `search_files(pattern, path=".")` 作为新函数加入 `file_ops.py` 并进全局工具集（所有会话可用；有工作区时受边界校验），返回 `文件:行号:内容`，跳过二进制、限制条数与单文件大小；
- 不按会话替换 `self.tools`，`clone()` 不动。

`workspace` 传递采用上下文变量（contextvar）：`apply_conversation_runtime` 时设置，工具内部读取；每个会话独立 asyncio 任务，天然隔离。对 LLM 不可见、不污染工具 schema。

顺带微调 `prompts/roles/coder.md`：提示优先使用相对路径、先用 `search_files`/`list_directory` 了解项目再动手。

## 错误处理

| 场景 | 行为 |
|---|---|
| 创建会话时 `workspace` 不存在/非目录/不可读 | 422 + 明确文案，前端弹窗内提示，不创建会话 |
| 会话创建后工作区目录被删除 | 不阻断对话：提示词注入退化为仅路径；工具调用返回"目录不存在"类错误文本 |
| 工具越界访问（文件类） | 返回错误文本（非异常中断），如"路径超出工作区 X"；对话流程继续 |
| 路径含 `..`/符号链接 | `resolve()` 后统一按规范路径判定，无法绕过 |
| 普通会话误传 `workspace` / 码农会话缺 `workspace` | 创建时 422 拒绝 |

## 测试策略

后端（`python -m pytest`）：

- 工具边界：有/无 `workspace` 时 `read_file`/`write_file`/`list_directory`/`search_files` 的路径解析与越界拦截；`run_shell` 的 `cwd` 生效；
- contextvar 在并发会话间互不串扰；
- 会话创建校验（422 分支）、`mode` 过滤、`mode`/`workspace` 不可变；
- 首轮提示词注入内容与轨迹记录。

前端（`cd frontend && npm test`）：

- Header 出现 `nav-coder`；`CoderSidebar` 按工作区分组渲染；`WorkspacePicker` 提交与错误展示；
- 测试用 `data-testid`，不依赖译文；新 i18n 键必须同时进 `en.json` 与 `zh-CN.json`。

手工验收：新建码农会话 → 选工作区 → 首轮系统提示词含工作区信息 → 工具越界被拦 → 普通聊天页不显示码农会话，反之亦然。

## 安全说明

本应用属本地/私有部署信任模型（现有 `run_shell` 工具本就无限制），工作区边界校验是行为约束而非安全沙箱；`run_shell` 仅做 `cwd` 约束。目录选择由前端输入 + 后端校验存在性完成，不暴露新的枚举接口。

## 修订记录（2026-08-24）：工作区来源改为服务器目录浏览

原方案（上文"工作区来源"/"无浏览端点"）已被替代：浏览器原生目录选择器（`showDirectoryPicker`）出于隐私只返回目录 **name**、不返回绝对路径，与后端绝对路径校验（`_validate_workspace`）冲突；首用新目录必须手输完整路径，且 NAS 部署下浏览器与后端异机，原生选择器选的是浏览器机器目录，而 agent 操作的是服务器文件系统，语义错误。

替代方案：新增只读端点 `GET /api/v1/fs/dirs`（`src/thumbelina/api/routes/fs.py`）——服务器侧目录列举（根/盘符、仅子目录、跳过符号链接、排序、截断、422 校验）。前端 `WorkspacePicker` 改为服务器目录树导航（点击进入/上级返回），输入框与最近工作区保留为兜底；移除原生选择器与 localStorage name→path 映射。绝对路径由后端得出，跨浏览器可用，NAS 场景浏览的正是 agent 工作的文件系统。`POST /conversations` 仍是工作区路径的唯一权威校验。
