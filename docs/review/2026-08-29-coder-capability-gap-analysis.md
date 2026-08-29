# 码农（coder mode）能力对标与补齐分析

| 项 | 值 |
|---|---|
| 日期 | 2026-08-29 |
| 分支 | `feat/tools-taxonomy` |
| 代码基线 | `28a66bd`（2026-08-29 00:35）+ 工作区未提交改动 |
| 对标对象 | Claude Code、OpenAI Codex CLI、Cursor、Qoder、CodeBuddy、Aider、Windsurf |
| 方法 | 三路并行：① 码农工具层盘点 ② Agent 运行时/上下文管理测绘 ③ 市面产品官方文档调研；关键论断均由本人逐行复核（见附录 A/B） |

> **基线漂移警告**：本次调研期间 `feat/tools-taxonomy` 正被并发提交（10 分钟内 3 个 commit，`file_ops.py`/`shell.py` 已删除、`execution.py` 新落地）。文中行号以上表基线为准；标注「在途」的条目请以当前代码复核。调研中曾发现的「超时不 kill 子进程」泄漏，已在 `execution.py:139` 修复——该结论已按修复后状态书写。

---

## 摘要

码农当前的形态是：**一个带 ReAct 循环、能读写文件、能跑命令的通用聊天 agent，套了一个 IDE 风格的外壳**。它缺的不是"更多 AI 能力"，而是**编码 agent 的工程底座**：没有精确编辑协议、终端跑不了 install/test、在大仓库里搜一次就卡死、用户看不到它改了些什么、也没有回滚手段。

七条最关键的结论：

1. **数据损坏风险（最高优先）**：`read_file` 无行范围参数且在 1MB 处截断，而 `write_file` 只能整文件覆写且无尺寸上限——模型"读一个大文件再写回"会静默丢弃后半部分。
2. **自我验证能力被剥夺**：`run_shell` 硬编码 30s 超时、无流式、无后台任务——`npm install` / `pytest` / 任何构建都跑不完，等于无法验证自己的产出。
3. **首次探索即卡死**：`search_files` 对 `rglob("*")` 每个文件整体读入内存，不排除 `node_modules`/`.git`/`venv`，无真实二进制判定，且 50 条截断不标注。
4. **已有 UI 资产与被砍能力错配**：码农页做成了 IDE/终端风格，但带 `tool_calls` 的 chunk 在流式路径被显式丢弃、前端 WS 协议无 tool 事件——用户看不到"改了哪个文件、跑了什么命令"。
5. **安全审查缺最后一环**：`security_review` 三态里 `Confirm` 的实现是「记日志 + 放行」（`base.py:81-85`），HITL 被明确排除在本期范围外；同时 `run_shell` 不校验命令内的目标路径（`cd ..`、绝对路径、`> /etc/hosts` 可逃逸），无 workspace 时 `cwd` 兜底为服务端进程目录。
6. **LangGraph 原生能力未被使用**：spec 中"当前 `tool_node` 无暂停/恢复机制"的前提是可解的——LangGraph 的 `interrupt()` + `Command(resume=...)` 正是为此设计，`Confirm` → 真中断的改造成本远低于事后另做一套审批。
7. **独有优势未变现**：项目已有完整的 embedding / 向量库 / 分层记忆 / 技能 / trajectory 基建，但**代码仓库索引没走这条线**、记忆索引只首轮注入、子代理不携带任何工具。这三项补齐的技术债最低、差异化收益最高。

**建议顺序**：先做 P0-1/2/3（消掉数据损坏与"跑不了测试"两个硬伤）→ 顺势借 taxonomy 重构做 P0-5（HITL）→ 再做 P0-4（工具事件打给已有 UI，感知提升最大）。

---

## 一、码农现状

### 1.1 运行时事实

| 维度 | 现状 | 证据 |
|---|---|---|
| 循环形态 | 单图 ReAct：`compress → agent ⇄ tools`，无 planner/executor 分离，无 plan 模式 | `graph.py:574-592` |
| 循环上限 | **无** —— 全库无 `recursion_limit` / `max_iterations` | grep 零命中 |
| 工具错误 | 转为 `Error:` 字符串回喂模型，不重试、不中断 | `nodes.py:88-94`、`base.py:87-89` |
| 并行工具调用 | **严格串行** `for` 循环，全库无 `asyncio.gather` | `nodes.py:71-94` |
| 压缩时机 | 仅在**每轮进 LLM 前**压缩一次；工具循环中途不压缩（`tools → agent` 边不经过 compress） | `graph.py:576,588` |
| 压缩触发 | 估算 token ≥ 窗口 × 0.8（默认），降至 50% 低水位；策略失败回退滑窗 | `config/models.py:161-162` |
| token 估算 | 字符启发式（CJK≈2/字符，其他≈0.25） | `compression/base.py` |
| 交接摘要 | **有**，且质量不错：要求保留事实/路径/错误/决策/**未完成 TODO**/进行中状态 | `compression/summarizer_context.py` |
| 大工具输出 | 源头硬截断（shell 100k 字符、read 1MB、search 50×500），压缩前再截 2k；**无落盘引用** | `execution.py:141-143`、`perception.py:117-120` |
| 流式 | token 级流式 ✅；`reasoning` 独立事件 ✅；tool_calls chunk 被丢弃 ❌；压缩节点事件丢弃 ❌ | `graph.py:1239-1249` |
| 中断 | 有 `{"stop": true}` 取消生成；**无运行中转向（steering）** | `api/websocket.py` |
| 工具事件下行 | **无** —— 前端 `WsIncoming` 类型里没有 tool 事件 | `frontend/src/hooks/useWebSocket.ts:4-26` |
| 可观测性 | trajectory 逐条记录 user/context/tool_call/tool_result/assistant/llm_usage（含 KV-cache 命中），64KB 上限；UI 只读回放，**不可重跑、无评测** | `agent/trajectory.py`、`routes/trajectory.py` |
| 子代理 | 一次裸 `llm_provider.chat()`，固定 system prompt，**无工具、无工作区、不与父上下文共享**，上限 5 并发，父轮询取结果 | `subagents/manager.py:86-100` |
| 技能 | LLM 从对话抽取；匹配为**关键词子串**（无 embedding）；每轮**只注入 top-1** | `skills/application.py`、`graph.py` |
| 记忆 | L0 索引**仅首轮注入**；`remember` 写 `MEMORY/`（非工作区）；后台异步抽取 | `graph.py:886-892` |
| 项目规则文件 | **不读任何** `AGENTS.md`/`CLAUDE.md`/`CODEBUDDY.md`/`.cursorrules`（而仓库自己维护着 `CLAUDE.md`） | grep 零命中 |
| 模型路由 | 无按步路由；压缩摘要与记忆抽取被绑到**主对话同一个 provider**；无 retry/backoff；无 structured output（手解 JSON）；prompt cache 仅靠 append-only 前缀隐式命中 | `graph.py`、`llm/` |
| 系统提示装配 | `ThumbelinaAgent._build_initial_messages`：角色提示（`prompts/roles/coder.md`，仅 10 行）→ L0 记忆索引 → 工作区上下文（深度 1、上限 50 条）→ RAG 分块 → top-1 技能 | `graph.py:961-1019` |
| TODO 模块 | 已实现但**只挂在 HTTP 路由**，agent/tools 从不 import | grep 零命中 |

### 1.2 工具清单（22 个，五类重构进行中）

| 分类 | 工具 | 读/写 | 护栏 |
|---|---|---|---|
| 感知 (11) | `read_file` | R | 工作区边界；1MB 截断；**无行范围** |
| | `list_directory` | R | 边界；无深度/总量上限 |
| | `search_files` | R | 边界；50 命中 / 500 字符行 / 1MB 文件；跳过符号链接 |
| | `fetch_url` `web_search` `parse_json` `parse_csv` `analyze_text` `search_text` `search_memory` `read_memory` | R | 各自截断；web_search 受配置开关 |
| 执行 (6) | `write_file` | **W** | 边界 + `PROTECTED_PATH_PATTERNS`（`thumbelina.db`/`MEMORY/`/`prompts/roles/`/`plugins/`/`.env`）；写后回读字节数自验证 |
| | `run_shell` | **W** | `DANGEROUS_PATTERNS` 硬拒 + `CONFIRM_PATTERNS`（当前=放行+日志）；30s 超时已 kill；100k 截断；**不校验命令内路径** |
| | `remember` `create_skill_composition` `list_skill_compositions` `execute_skill_composition` | W | 后三者仍在 `graph.py` 内联工厂（`_make_composition_tools`/`_make_channel_tools`，`graph.py:207-319`） |
| 沟通 (1) | `notify_user_by_channel` | — | 同上，未迁入 `communication.py` |
| 协作 (2) | `create_subagent` `list_subagents` | — | `collaboration.py` |
| 事件 (2) | `schedule_task` `list_scheduled_tasks` | — | `event.py` |

---

## 二、市面对标矩阵

`—` = 未发现该能力。

| 能力域 | Claude Code | Codex CLI | Cursor | Qoder | CodeBuddy | Windsurf | **码农** |
|---|---|---|---|---|---|---|---|
| 代码索引 | agentic search + LSP 工具 | `file_search` 模糊匹配 | 向量索引 + Instant Grep | 向量索引(≤10万文件)+Repo Wiki | agentic search | Codemaps/DeepWiki | **❌** |
| 检索工具 | `Glob` `Grep` `WebSearch` `WebFetch` | shell+grep | Instant Grep + `@` 引用 + Explore 子代理 | 语义符号检索 | 同类 | code lens | **⚠️ 自写 rglob** |
| 编辑协议 | `Edit` 精确串替换（强制先读）+ `Write` | `apply_patch` 流式补丁 | 建议+自动应用 + 行内 diff | 定点修改 + Review 面板 | Edit + 可信目录 | diff zones | **❌ 仅整文件覆写** |
| 自验证闭环 | Bash + hooks + `/verify` `/code-review` | Guardian 审查 | Debug mode + browser | `/verify` `/run` QA 证据收集 | hooks + `/goal` 评估轮 | linter 集成 | **⚠️ 仅 exit-code 匹配** |
| 终端 | 后台 Bash / Monitor / `/bashes` | 统一 PTY + shell 快照 | Run Everything | 沙箱终端 + 审批队列 | bash 沙箱 + excludedCommands | Turbo | **⚠️ 30s 同步** |
| 长任务/后台 | `/bg` `TaskOutput` `TaskStop` cron `/loop` | 后台终端 + cloud tasks | Cloud Agents + kanban | 定时任务 `/kanban` Cloud | daemon + Web UI workers | Agent Command Center | **❌（仅调度器）** |
| 上下文压缩 | `/compact` + 自动 + Pre/PostCompact + `/context` | remote compaction v2 + **跨线程共享预算** | `/summarize` `/rewind` | `/compact` `/context` Smart Context | 异步压缩策略 + 用量条 | 实时感知 | **⚠️ 有但仅轮首** |
| 记忆/规则 | `CLAUDE.md` + auto memory | `AGENTS.md` + 抽取/固化 | `.cursor/rules` + Team Rules | `AGENTS.md` + Auto-Memory + Knowledge Card | `CODEBUDDY.md` + `rules/*.md` 层级 | `AGENTS.md` + Memories | **⚠️ 自有记忆但不读规则文件** |
| 子代理/并行 | Agent + agent teams(SendMessage) + Workflow | collab/roles/thread-manager | 前后台子代理 + Explore | Experts Mode（固定专家团） | 子代理 + 团队 + delegate | Arena Mode | **❌ 裸 LLM 调用** |
| 计划/任务 | TodoWrite + TaskCreate + Plan mode | 持久 goal 自动续跑 | Plan Mode `/plan` `/goal` | Spec/Plan/Goal 三驱动 | Plan 文件 + `/goal` | Cascade plans | **❌** |
| 权限/安全 | 6 模式 + 分类器 + 沙箱 | OS 沙箱(Landlock/bwrap/Win) + execpolicy + Guardian | Run Modes + Auto-review + AppArmor | 5 模式 + 文件/终端/网络审批 | 8 模式 + delegate | allow/deny | **❌ Confirm 空转** |
| Hooks | ~30 事件 | hooks.json | `PreToolUse`/`PostToolUse`/`Stop`… | 生命周期 Hooks | Hooks | Cascade Hooks | **⚠️ 基类模板已有，未对外** |
| MCP | ✅ resources/elicitation | ✅ apps + 延迟工具 | ✅ stdio/HTTP | ✅ Connectors | ✅ mcp-apps | ✅ + 管控 | **❌** |
| Git 工作流 | `/review` `/security-review` PR 云会话 | PR watch + `gh` | 多平台 + BugBot + worktree | Review→stage→commit→push | smart-commit + CI | AI commit msg | **❌ 无任何 git 工具** |
| diff 审查 UX | IDE 插件 + 行内 diff | 桌面 app + 应用内浏览器 | 原生编辑器 + side chat | IDE + JetBrains + CLI + ACP | IDE + 插件 + **Web UI** | Previews 选元素 | **⚠️ 有 IDE 页无 diff** |
| 检查点/回滚 | `/rewind`（代码/对话/两者，100 快照） | git rollback + rollout | `/rewind` | `/rewind` + Undo | Checkpointing | checkpoints | **❌** |
| 模型路由/兜底 | `/model` + fallback 链(≤3) + effort | 多 provider + 中途换模型 | Cursor Router | 分层 + BYOK + 每任务选 | `models.json` BYOK | Adaptive router | **❌** |
| 成本可观测 | `/usage` `/cost` `/insights` + OTel | rollout 轨迹 + metrics | 用量面板 + Blame | Credits 分项 + `/insights` | **`/cost` 含 cache-read** + `/context` + 监控 | Analytics API | **⚠️ 已记录未暴露** |
| 多文件重构 | Workflow 编排 | code mode(JS exec) | Cloud Agent | Experts 并行 | 团队 | Arena | **⚠️ 只能逐文件覆写** |
| 浏览器/预览验证 | Chrome + computer use | Browser Use(CDP) | browser tool + Design | 内置浏览器 + Browser Agent | preview + Figma→code | Previews | **❌** |
| Spec 驱动 | Plan + skills 生态 | `AGENTS.md` + 任务简报 | Plan Mode 产物 | **Specs**（需求→设计→任务→验收） | Plan 文件 | Workflows md | **❌** |
| 循环/错误恢复 | PostToolUseFailure + Stop + `/doctor` | 断网续跑 + Guardian V2 | 自动审查审批提示 | Better Harness + 任务监控 | `/goal` 评估元消息 | Quick Review | **❌ 无上限无熔断** |

---

## 三、差距清单

规模：S ≤ 1 人日，M = 2-4，L = 5-10，XL > 10。

### P0 · 阻塞级（不做就不算编码 agent）

#### P0-1　编辑协议：`edit_file` 精确替换 + `read_file` 行范围

- **现状**：`read_file` 参数只有 `path`（`perception.py:59-60`），读入后在 1MB 处截断（`:117-120`）；`write_file` 只能整文件覆写、无尺寸上限、不要求先读、返回 `"Successfully wrote N bytes"`（`execution.py:172-185`），无 diff、无备份、无撤销。
- **影响**：**静默数据损坏**。模型对一个 2MB 文件"读一遍再写回"，尾部内容直接丢失且无告警。同时大文件根本无法增量修改，多文件重构只能整段重写。
- **市面对照**：CC `Edit` 要求 read-before-edit + 精确串替换并返回 diff；Codex `apply_patch` 流式生成补丁并保留行尾；Cursor 逐行 diff + 自动应用；Qoder 定点修改 + per-file Review 面板。
- **建议**：
  1. `ReadFileTool` 增加 `offset`/`limit`（行号语义），返回带 `cat -n` 风格行号前缀，并在尾部明确"共 N 行，已读 a-b"。
  2. 新增 `EditFileTool(ExecutionTool)`：`path` + `old_string` + `new_string` + 可选 `replace_all`；`security_review` 里强制「本会话内该文件已被 `read_file` 过」（用一个 ContextVar 会话级已读集合）+ 边界 + 保护路径；`_execute` 要求 `old_string` 唯一命中，多命中返回结构化错误（附行号），零命中返回错误而非静默成功。
  3. `self_verify` 重写为：**写前备份原内容到会话快照目录 → 写后回读 → 比对字节数 → 返回 unified diff 摘要**（而非现在的 `st_size` 比对）。
  4. 返回给模型的内容包含 diff，让模型知道实际改了什么。
- **规模**：M　**依赖**：无（可直接挂在已落地的 `ExecutionTool` 基类上）
- **验收**：给一个 5000 行文件，让码农改一个函数——(a) 不得出现整文件重写；(b) 未先读的文件编辑被拒；(c) `old_string` 多命中时返回可定位错误；(d) 单测覆盖三态（唯一/多命中/零命中）。

#### P0-2　终端：流式输出 + 可配超时 + 持久 shell + 后台任务

- **现状**：`execution.py:127-145`——30s **硬编码**超时（`_TIMEOUT`，`:30`）、`create_subprocess_shell` + `communicate()` 全缓冲、输出合并、100k 字符头部截断、退出码以 `[exit code: N]` 文本拼接。每次调用都是新进程。超时已 `proc.kill()`（在途修复 ✅）。
- **影响**：**这是码农最致命的能力缺口**。`pip install` / `npm install` / `pytest` / `cargo build` 全部超过 30s → 一律 `Error: Command timed out` → 模型收不到真实反馈 → 只能"盲改"。`cd`、`export`、`source venv/bin/activate` 不跨调用存活，模型必须每条命令自带绝对路径。无法启动 dev server，因此无法验证任何 UI/接口行为。
- **市面对照**：Codex `unified_exec` 单一 PTY 工具 + shell 快照（别名/函数/环境变量跨调用保留）；CC 后台 Bash + `Monitor` + `/bashes` 会话管理 + 输出限额；CodeBuddy Web UI 提供 4 分屏终端 + worker 监控。
- **建议**：
  1. 超时进配置（`tools.shell.timeout_seconds`，默认 120），并允许模型按命令传 `timeout` 参数。
  2. 输出改为增量：`_execute` 逐块读 stdout，通过既有的 trajectory/WS 通道下发（配合 P0-4）。
  3. 引入 `ShellSession`（按 conversation_id 缓存一个持久 PTY 或至少一个 `(cwd, env)` 状态对象），使 `cd`/`export` 跨调用生效；Windows 下无 PTY 时退化为 cwd/env 状态机。
  4. 新增 `run_shell_background` + `shell_output(handle)` + `shell_stop(handle)` 三件套（对标 CC background Bash），用于 dev server / watch。
  5. 输出截断改为「首尾保留 + 中段丢弃 + 明确标注丢弃量」，并提供落盘引用（见 P1-12）。
- **规模**：L　**依赖**：P0-4（否则流式输出用户看不到）
- **验收**：在含 `node_modules` 的真实前端工作区，让码农执行 `npm install && npx tsc --noEmit`，全程无超时误报，且前端终端面板能看到逐行滚动。

#### P0-3　搜索与仓库探索可用性

- **现状**：`perception.py:156-205`——`root.rglob("*")`（`:180`）遍历**所有**条目，逐个 `entry.read_text()` **整体读入内存**（`:190`），仅按 1MB 文件大小过滤（`:187`）；用 `errors="ignore"` 解码，**没有真实二进制判定**（压缩包/图片被解成乱码参与匹配）；**不排除 `node_modules`/`.git`/`venv`/`dist`/`build`/`.next`**；无 glob `include` 过滤、无路径 `exclude`；无上下文行（只回匹配行本身）；命中 `_SEARCH_MAX_HITS=50` 后直接 `break` 且**不标注结果被截断**（`:196-199`；`:203` 只在零命中时给提示）。
- **影响**：码农的第一动作几乎总是"搜一下"。在你们自己的 `frontend/`（含 `node_modules`）上，这会读入数万文件——分钟级卡顿或 OOM。更糟的是静默截断会让模型误判"全项目只有这 50 处引用"，从而做出错误的重构决策。
- **市面对照**：CC 直接嵌 `ripgrep`（尊重 `.gitignore`、二进制自动跳过、`-C` 上下文行、`-l`/`-n`/`glob`）；Cursor Instant Grep + 向量索引双路；Qoder 提供 Codebase/Files/Directory 多工具 + `.qoderignore`。
- **建议**：
  1. 首选**子进程调用 `rg`**（存在时），参数：`--hidden -g '!.git' -g '!node_modules' -g '!venv' --no-heading -n -C <n> --max-count --max-filesize`；不存在时回退 Python 实现。
  2. Python 回退版必须：目录黑名单、`_is_binary` 空字节探测、`include` glob 参数、`context_lines` 参数、默认尊重 `.gitignore`、命中超限时返回显式 `... (truncated, showing 50 of N)`。
  3. 结果统一走 `PerceptionTool._truncate`（`perception.py:35-39`，`_RESULT_TOKEN_LIMIT=4000` 已定义但搜索路径未使用——顺手收口）。
  4. `list_directory` 同样加黑名单 + 深度/条目上限，并输出 git 状态标记（依赖 P1-7）。
- **规模**：M　**依赖**：无
- **验收**：对 `frontend/`（含 node_modules）执行一次 `search_files`，p95 < 2s 且无 OOM；结果含"truncated"标记当超限；对含图片/压缩包目录不产生乱码命中。

#### P0-4　工具事件下行到前端（把 agent 行为暴露给已有的码农 UI）

- **现状**：流式路径显式丢弃带 `tool_calls` 的 chunk（`graph.py:1246-1249`）与 compress 节点事件（`:1239-1241`）；前端 WS 协议 `WsIncoming` 只有 `chunk`/`chunk_type`/`response`/`done`/`stopped`/`error` 等，**没有 tool 事件类型**（`useWebSocket.ts:4-26`）。工具信息只存在于 trajectory（事后查）。
- **影响**：码农页已投入做成 IDE/终端风格（`CoderPage.tsx`/`CoderSidebar.tsx`/`WorkspacePicker.tsx` + 目录树 + 终端弹窗 + 橙色强调），但运行时用户看不到"它在读哪个文件、改了哪几行、跑了什么命令、命令输出是什么"，只能干等最终答案 → **无法审查，体验退回 chatbot**。这是投入产出比最高的可见性修复。
- **市面对照**：所有对标产品的 agent 视图核心都是「工具卡片 + diff + 终端输出」实时流；CodeBuddy 的 Web UI（chat + 4 终端 + logs + monitor 同屏）是与本项目架构最接近的参照。
- **建议**：
  1. 定义 WS 事件：`tool_start{id,name,args_preview}` / `tool_args_delta` / `tool_output_delta`（shell 用）/ `tool_end{id,ok,duration,summary,diff?}`。
  2. 在 `tool_node`（`nodes.py:71-94`）执行前后发事件，经由既有 `notifications.py` 广播到当前 conversation 的 WS 连接；`graph.py` 流式路径不再丢弃 tool_calls chunk，改为转成 `tool_start`。
  3. 前端：工具卡片流（可折叠参数/输出）+ 文件树高亮"本轮被修改的文件" + 点击展开 diff 视图（依赖 P0-1 产出的 diff）。
  4. 这些事件与 trajectory 记录共用同一份数据，避免两套实现。
- **规模**：L　**依赖**：P0-1（diff 内容）、P0-2（终端增量）
- **验收**：一次"改 3 个文件 + 跑一次测试"的任务，前端能实时呈现每个工具卡片、命令滚动输出、文件树变更标记，且点击可看 diff。

#### P0-5　人机确认（HITL）与 shell 路径约束

- **现状**：`security_review` 三态 `Allow/Confirm/Reject` 已建模，但 `Confirm` 的行为是 **`logger.warning` + 放行**（`base.py:81-85`），设计文档明确 HITL 出范围（`docs/specs/2026-08-29-tools-taxonomy-design.md:110-112,214`）。另外：`RunShellTool.security_review` 只做**命令文本**正则匹配，不解析命令内的目标路径（`execution.py:115-125`），因此 `cd ..`、绝对路径、`> ~/.ssh/authorized_keys` 不受工作区约束（`cwd` 只是建议性的）；`cwd = get_workspace() or os.getcwd()`（`:128`）意味着**无工作区会话直接以服务端进程目录为落脚点**；`write_file` 的边界检查在 `resolve_workspace_path` 返回 `None`（未设工作区）时退化为 `Path(path).resolve()` 未校验（`execution.py:174-177`、`perception.py:42-47`）。
- **影响**：所谓"执行类强制安全审查"当前只对硬编码黑名单有效；对用户而言，一次误判的 `rm`、一条被注入的间接命令（提示注入 → `curl x | sh` 之外的变体，如 `bash <(curl ...)`）就可能越界。`DANGEROUS_PATTERNS` 也必然落后于真实攻击面。
- **市面对照**：CC 6 种权限模式（含 `plan`、分类器驱动的 `auto`）+ 沙箱化 Bash；Codex OS 级沙箱（Seatbelt / Landlock / bwrap / windows-sandbox）+ execpolicy + Guardian 自动审批审查；Qoder 5 模式 + 文件/终端/网络分别审批队列；CodeBuddy 8 模式含 `delegate`。
- **建议**（按性价比排序）：
  1. **把工作区边界变成真边界**：`run_shell` 注入平台级约束——Windows 用受限令牌/独立低权账号或至少 `--cwd` + 命令内路径静态解析（`shlex`/`pywin32`），POSIX 用 `bwrap`/`Landlock`；同时把"无工作区时 `os.getcwd()` 兜底"改为**拒绝执行**（要求码农会话必须绑定工作区）。
  2. **用 LangGraph 原生 `interrupt()` 实现 Confirm**：`security_review` 返回 `Confirm` 时 `interrupt(payload)` 挂起图，WS 下发审批请求，用户裁决后经 `Command(resume={"decision": ...})` 恢复。spec 里"`tool_node` 无暂停/恢复机制"的前提在此被 LangGraph 自身能力消解，**且不需要改动 `bind_tools`/`ainvoke` 契约**。这是本清单里最重要的架构洞察。
  3. **权限模式**（而非二选一开关）：`read-only` / `default`（写+执行需确认）/ `accept-edits`（写放行、危险命令确认）/ `yolo`。持久化在会话上（与既有 `mode`/`workspace` 字段同级）。
  4. **审批 UX**：前端弹卡（命令 + 风险说明 + "仅本次允许 / 总是允许该模式 / 拒绝"），并把"总是允许"落成可编辑的规则列表。
  5. **审计日志**：每次 `Reject`/`Confirm`/审批决策落库（现在只有 `logger.warning`）。
  6. 顺带：`api/routes/fs.py:44-60` 目录选择器可枚举**整个服务端文件系统**（含盘符），默认无鉴权（`app.py:752` 仅在配置了 `secret_key` 时挂鉴权中间件）→ 至少加部署告警或 root 白名单。
- **规模**：L（1+2+3）+ M（4+5）　**依赖**：与在途 taxonomy 重构强耦合，**应在收口前一起做**
- **验收**：`rm -rf` 变体（`bash <(curl ...)`、`rm -r --no-preserve-root`）被拒；`git push --force` 触发挂起且用户可在 UI 批准/拒绝且审计可查；无工作区会话无法执行 shell；越界写入被拒且带明确原因。

---

### P1 · 平权级（对标主流能力）

#### P1-6　自验证闭环：编辑后自动 lint / typecheck / 相关测试

- **现状**：`ExecutionTool.self_verify` 是**工具内部**的轻量检查（写后字节数比对、exit code 非零 → `Suspect`）。`RunShellTool.self_verify` 里 `_ERROR_HINTS` 实为死代码（`execution.py:146-151`：内层 `if` 的 `or m.group(1) not in ("",)` 恒真）。没有任何机制在"改了 `.py` 文件"后自动跑 `ruff`/`mypy`/对应测试。
- **影响**：模型改完就认为完事，交付物未经受任何机器验证——这正是"AI 写的代码看着对、跑不起来"的根因。
- **市面对照**：CC Hooks `PostToolUse`/`PostToolUseFailure`/`Stop`（把 lint/format 挂成硬门禁）+ `/verify` `/code-review`（多 agent 找问题 + **对真实代码行为做验证 pass** + 按严重度排序）；Qoder `/verify` `/run` `/simplify` 且 QA 专家负责收集验证证据；CodeBuddy `/goal` 评估轮把达成度作为元消息回注。
- **建议**：
  1. 引入 `PostToolUse` 型钩子点（你们已有 `security_review`/`self_verify` 模板方法，天然是挂载位置），按被改文件后缀映射到检查命令：`.py → ruff check + mypy`、`.ts/.tsx → tsc --noEmit + eslint`、测试文件 → 相关测试。
  2. 检查失败以结构化 `Suspect` 回喂模型，并设**重试上限 + 退避**（防"改-错-改"死循环）。
  3. 用户可见的 `/verify` 与 `/simplify` 指令（复用 P0-4 的工具事件通道展示证据）。
  4. 开放 hooks 给用户自定义（对齐 CC/Cursor 语义）——你们已有 `hook` 概念的话，把它接到工具生命周期上。
- **规模**：M-L　**依赖**：P0-2（能跑完命令）、P0-5（自动执行命令需权限模式）
- **验收**：故意让码农写入一个语法错误文件，它必须自己发现并修复后才宣告完成，且过程在前端可见。

#### P1-7　Git 工具 + 快照/回滚

- **现状**：**完全空缺**（grep 无 git 工具）。码农要提交只能 `run_shell git ...`，因此绕过了所有审查与展示，也没有回滚能力。`graph.py` 里唯一的"checkpoint"是 LangGraph 对话状态检查点，与代码无关。
- **市面对照**：`/rewind` 全员标配；CC 的 100 快照 + **可分别恢复「仅代码 / 仅对话 / 两者」** 是参考实现；Qoder 走 Review→stage→commit→push 一条链；Codex 直接依赖 git。
- **建议**：
  1. `GitTool(ExecutionTool)` 最小集：`git_status` / `git_diff` / `git_add` / `git_commit`（+ 只返回摘要的 `git_log`）；`security_review` 里把 push / force / reset --hard 归 `Confirm`。
  2. **快照/回滚**：每轮执行工具前对**将被修改的文件**做影子备份（shadow git，独立于用户仓库的 `--git-dir`，或用轻量文件快照），提供 `/rewind` 到任意轮次；语义上区分"退代码 / 退对话 / 都退"。
  3. commit message 生成 + 变更摘要复用 P0-1 的 diff。
- **规模**：M（git 工具）+ L（rewind）　**依赖**：P0-1（diff 是共同底座）
- **验收**：让码农连续改 5 个文件后 `/rewind` 到第 2 轮，工作区与对话同时回到该点；无 git 仓库的工作区也能回滚。

#### P1-8　项目规则文件 + 记忆注入修正

- **现状**：不读 `AGENTS.md`/`CLAUDE.md`/`CODEBUDDY.md`/`.cursorrules`（grep 零命中）。同时记忆 L0 索引**只在工作线程首轮注入**（`graph.py:886-892` 的 `first_turn` 门），长会话+压缩后记忆实际淡出；而 `MEMORY/` 还是 `write_file` 的保护路径（`execution.py:51-56`），即码农无法把项目约定落到工作区里。
- **影响**：跨厂商已经形成的 `AGENTS.md` 事实标准意味着"你的码农不认识任何项目的约定"，而别的 agent 认识。用户手工维护的规则被无视 → 每次会话都要重述技术栈/风格/目录约定。
- **市面对照**：CC `CLAUDE.md`（含嵌套目录级 + auto memory）；Codex `AGENTS.md`（启动抽取 + 固化 + 可从其他 agent 导入）；Cursor `.cursor/rules` 四类 + Team Rules；Qoder `AGENTS.md` + Auto-Memory + Knowledge Card；CodeBuddy `CODEBUDDY.md` + `rules/*.md` 层级。
- **建议**：
  1. `PerceptionTool` 新增 `read_project_rules`，或直接在工作区根及各级目录查找 `AGENTS.md` > `CLAUDE.md` > `CODEBUDDY.md` > `.cursor/rules`，**每轮注入**（append-only 前缀，顺带提升 prompt cache 命中）。
  2. 记忆索引改为每轮按需注入（用现有 n-gram triage，超预算走 top-K），别再绑 `first_turn`。
  3. 提供"把本轮约定写入 `AGENTS.md`"的能力（写工作区，与 `MEMORY/` 分离），让码农能沉淀项目规范。
- **规模**：S-M　**依赖**：无 —— **本清单中性价比最高的一条**
- **验收**：在目标仓库放一份 `AGENTS.md`（声明"用 pnpm 不用 npm，组件放 `src/components/ui`"），码农在后续轮次无需提醒即遵守。

#### P1-9　仓库结构索引（repo map）

- **现状**：无 AST / 符号 / LSP 能力（`plugins/sandbox.py` 里的 `ast` 用法与码农无关）。工作区上下文注入只有**深度 1、上限 50 条**的目录列表（`graph.py:63-88`），模型对中大仓库没有全局观。
- **市面对照**：Aider repo map（graph 排序的标识符摘要，按 `--map-tokens` 预算，聊天里没有已引用文件时自动扩大）是**最便宜且最可移植**的定位原语；Cursor 用向量索引 + Instant Grep；Qoder 用向量索引 + Repo Wiki 结构索引；CC 用 LSP 工具。
- **建议**（两条路，第一条性价比更高）：
  1. **轻量 repo map**：tree-sitter（或 ctags）抽取符号与签名 → PageRank 式排序 → 按 token 预算裁剪 → 每轮注入。零 embedding、零外部服务。
  2. **复用既有 RAG 基建**：`rag/` 已有 loader/chunker/embedding/ChromaDB 全套，加一条"代码知识库"通道（按函数/类切块、路径+符号入 metadata），使 `search_memory` 式的语义检索可用于代码。注意这条会引入模型依赖与索引新鲜度问题，建议 1 先行。
  3. MCP + 社区 `lsp` server 是第三条低成本路径（见 P1-11）。
- **规模**：M（1）/ L（2）　**依赖**：无
- **验收**：在一个 3000 文件仓库里问"X 功能在哪实现，改它会影响哪些调用方"，码农应给出正确文件与调用点，而不是全库 grep 试探。

#### P1-10　计划/任务清单进 agent + 循环熔断

- **现状**：单图 ReAct，无 plan 模式；`src/thumbelina/todo/` 已实现但**未被 agent import**（grep 零命中）；**无迭代上限、无重复工具调用检测**（`nodes.py` 只顺序执行；`graph.py` 无条件终止）。工具错误仅回喂，无重试策略。
- **影响**：长任务上模型会漂移、绕圈、重复同一失败调用；用户看不见进度（而市场把任务清单做成了 UI 一等公民）。无上限 = **一个坏循环可无限烧 token**。
- **市面对照**：CC TodoWrite + `TaskCreate/Get/List/Update` + Plan mode + `/goal`（完成条件）；Codex 持久 goal 自动续跑；Cursor/Qoder/CodeBuddy 均有 Plan/Goal 原语，Qoder 更进一步做 Spec 驱动（需求澄清 → spec → tasks → 验收标准）。
- **建议**：
  1. 把 todo 模块接成一个执行类工具（`todo_write`/`todo_update`/`todo_list`），状态注入到系统提示，前端侧栏渲染进度卡。
  2. 新增 **plan 模式**：只允许感知工具（`read`/`search`/`list`）+ `todo_write`，产出计划 → 用户批准 → 切执行模式。这是 CC/Cursor/Qoder 都有的"审批闸门"，也与 P0-5 的权限模式天然合并实现。
  3. **熔断**：`recursion_limit`、同一工具+同参数连续重复 ≥N 次即中断并上报、每轮 token/成本预算上限（超阈值即停）。
- **规模**：M　**依赖**：P0-5（plan 模式即权限模式的一种）
- **验收**：多步骤任务可见任务清单且状态推进；人为构造必然失败的调用循环，agent 在 N 次内自动停下并给出诊断而不是无限跑。

#### P1-11　子代理改造 + 并行工具调用

- **现状**：`create_subagent` → `SubagentManager._execute` 只发**一次裸 `llm.chat()`**（`subagents/manager.py:86-100`），固定 system prompt，**无工具、无工作区、无父上下文**，父代理靠 `list_subagents` 轮询，无增量回传。`MonitorAgent`/`WorkerAgent` 未注册为 agent 工具。工具调用侧严格串行（`nodes.py:71-94`）。
- **影响**：现在的"子代理"实质是"多问模型一句话"，与市面语义无关。而子代理最实用的价值——**把冗长检索/大文件扫描隔离到另一个上下文里，只把结论带回主上下文**——恰好是你们最需要的（配合 P0-3/P1-9 直接降 token）。
- **市面对照**：CC 有 4 种并行形态（subagents / agent view / agent teams 带 `SendMessage` + 共享任务清单 / 脚本化 Workflow）；Cursor 的 Explore 子代理专门跑检索、用更快的模型、**独立上下文**；Qoder Experts Mode 给每个角色限定工具集并由 QA 收集证据。
- **建议**：
  1. 子代理支持**工具白名单 + 独立消息上下文 + 轮次/成本预算**；先做 `explore` 型（只给感知工具，禁 `write_file`/`run_shell`），返回结论 + 证据路径。
  2. 结果流式回传主会话（经 P0-4 通道），父代理不再轮询。
  3. `tool_node` 换 `asyncio.gather(..., return_exceptions=True)`，只读工具并行、写类工具串行（保序 + 避免竞态），并保持 `tool_call_id` 配对正确（你们已有配对修复逻辑可复用）。
  4. 无共享语义的多 agent fan-out **不要做**（见「非目标」）。
- **规模**：M-L　**依赖**：P0-4、P1-10（任务清单可作为协调底座）
- **验收**：一次探索任务里，子代理扫全仓但主上下文只增加 <2k token，且主代理能引用子代理给出的文件证据。

---

### P2 · 差异化与工程化

#### P2-12　turn 内压缩 + 大输出落盘引用

- **现状**：压缩只在**每轮进 LLM 前**发生一次（`graph.py:576,588` 的边结构决定），`agent ⇄ tools` 循环中途不压缩；工具输出走"源头硬截断"，无落盘引用机制。长工具链的一轮（20 次 shell）可在轮内把窗口打满。
- **建议**：把 compress 节点接入工具循环（`tools → compress → agent`，或每 N 次工具调用触发）；超阈值工具输出写入工作区外临时文件，上下文里只留"路径 + 摘要 + 取回方式"。Qoder 官方也承认压缩是有损的（其 context-compaction 文档），因此**验收条件驱动的循环**比"更强的压缩"更可靠——别把宝押在压缩上。
- **规模**：M-L

#### P2-13　模型路由 / 重试 / structured output

- **现状**：压缩摘要器与记忆抽取器被绑到**与主对话同一个 provider**；无 retry/backoff（仅 `asyncio.wait_for` 超时）；无 `with_structured_output`/`response_format`（手解 JSON）；无按步路由；prompt cache 仅靠 append-only 前缀隐式命中（但你们已经在 `trajectory.py` 记 KV-cache 命中/未命中）。
- **建议**：配置里加 `roles: {main, fast, cheap}` 三档路由（摘要/检索/记忆抽取走 fast）；provider 错误加指数退避 + 兜底链（CC 支持 ≤3 段 fallback 链）；所有内部抽取器改 structured output；用 `trajectory.py` 的 cache 数据反向优化前缀稳定性。
- **规模**：M　**收益**：直接降本 + 提可靠性（P0-1/P1-8 的前缀注入也依赖此项）

#### P2-14　技能：embedding 匹配、多条注入、兼容 SKILL.md

- **现状**：匹配为关键词子串（完全命中 1.0、≥3 字词全含 0.8）+ LLM 名称兜底，无 embedding；每轮**只注入 top-1**；不可分发。
- **建议**：接入既有 embedding 层做语义匹配；注入 top-K 并让模型自选；**格式对齐 `SKILL.md`** 以直接复用市面技能生态（含你们本会话可用的那些技能）。
- **规模**：M

#### P2-15　MCP 客户端

- **现状**：无。插件系统已有骨架，但 taxonomy spec 明确「范围外：插件 `PluginType.TOOL` 产出真实工具实例」（`:216`）。
- **影响**：MCP 已是全员标配（6/6），缺它意味着生态割裂——而**很多 P0/P1 能力可以用 MCP 白拿**：filesystem（更严格的沙箱）、git、github、lsp、browser、sentry、postgres。这是"用一天工作量换五个能力域"的一条。
- **建议**：先做 MCP **客户端** + 工具注册进 `get_all_tools`，并让 MCP 工具继承 `ExecutionTool` 以复用 `security_review`（外部工具默认 `Confirm`，即 P0-5 的挂点）。
- **规模**：M　**依赖**：P0-5（外部工具必须先有审批闸门，否则等于开后门）

#### P2-16　成本与上下文可视化 + 预算熔断

- **现状**：trajectory 已记录 `llm_usage` 含 KV-cache 命中/未命中（`trajectory.py:38-45`），`/trajectory/cache-stats` 已存在，但**没有**面向用户的 context 用量条、每任务成本、预算上限。
- **市面对照**：CodeBuddy `/cost` 打印分模型的 input/output/**cache-read** token + `/context` 分块用量条；CC 有 `/usage` `/cost` `/stats` `/insights` + 完整 OpenTelemetry；Codex 有跨 agent 线程的**共享 token 预算**（首个产品化的跨代理预算原语）；Qoder 在选择模型层就显示 credit 费率。
- **建议**：把已有数据变成四样东西——(a) 每任务成本卡；(b) 上下文用量条（按角色提示/记忆/技能/历史/工具输出分块归因）；(c) 可设的硬预算（触发即停并汇报）；(d) trajectory 导出。**这四项恰好是领先产品有、而开源 agent 普遍缺的分水岭。**
- **规模**：S-M（数据已有，纯暴露层工作）

#### P2-17　trajectory → 回归评测集

- **现状**：trajectory 记录 seq 有序、payload 64KB 上限、UI 只读回放，**不可重执行、无评测框架**。
- **建议**：把历史成功轨迹沉淀为可重跑用例（固定工作区快照 + 输入 + 期望断言），每次改 prompt/工具/模型就跑一遍——这是唯一能让"改 prompt 不敢上线"变简单的办法。参考 CC Code Review 的三段式误报控制：Qoder Ultra Review 要求 finding 同时满足「已确认 ∧ 本次变更新引入 ∧ 证据锚定」，是很值得抄的判定门。
- **规模**：L　**收益**：把本文所有其他项变成可度量工程

---

## 四、与在途 tools-taxonomy 重构的衔接

**结论：重构后的基座正是上述多项能力的天然插入点，建议不要等收口后再返工。**

| 重构已给的 | 可顺势做的 |
|---|---|
| `security_review`/`self_verify` 抽象方法（`ExecutionTool` 强制子类实现） | P1-6 自验证闭环挂这里；P0-1 的 read-before-edit 断言挂这里 |
| `Allow/Confirm/Reject` 三态 + `base.py:77-93` 模板方法 | P0-5 把 `Confirm` 从「日志+放行」换成 `interrupt()`，**`_arun` 签名与 `bind_tools` 契约不变** |
| `category` 元数据 | P0-5 权限模式按 category 批量放行/收紧；P1-11 子代理工具白名单直接按 category 表达；spec 列为范围外的"分类在 UI/API 暴露"其实正是 P0-4 需要的 |
| `PerceptionTool._truncate` 收口截断 | P0-3 搜索、P1-12 落盘引用都走这一处 |
| Task 5 尚未做（composition/channel 工具仍在 `graph.py:207-319` 内联工厂） | 迁移时**顺手**让 MCP 工具与 git 工具走同一装配路径，避免再造一套工厂 |

一个提醒：`Confirm` 目前是「静默放行」，而 UI 上没有任何提示。**在 HITL 落地前，README / 码农页应当明确写"危险命令会被记录但仍会执行"**，否则用户会误以为已有保护。

---

## 五、非目标（明确不建议投入）

| 项 | 不建议的理由 |
|---|---|
| Repo Wiki 式自动文档生成 | 调研判断：多数此类"AI 理解代码库"是给人看的产物，agent 侧仍在 grep；真正索引代码的只有 Cursor（向量）和 Qoder（向量+Wiki）。做 P1-9 的 repo map 更划算 |
| 多 agent "团队" fan-out | 无消息传递/共享任务论语义的并行只是同上下文复制，负收益。只有 CC（`SendMessage`+共享清单）、Codex（task-path 路由+共享预算）、Qoder Experts（角色工具集+QA 证据）具备真协调语义 |
| 浏览器 / computer use | 先用 MCP browser server 顶替；个人助理定位下不是主干 |
| 插件 marketplace / 分发 | 生态未成，先保证工具契约稳定 |
| IDE 插件（VS Code/JetBrains） | 你们已有 Web UI 且架构自洽，投入产出差 |
| 一键部署 | 参照 CodeBuddy Deploy / Windsurf→Netlify：演示价值高、留存低 |
| 无人监督长时自治（宣称数小时） | 压缩有损是厂商自己承认的；用 P1-10 的验收条件闭环 + P0-5 审批达成"可信"，比追"自治时长"指标更实 |
| Persona / 语音 / 输出风格 | 真实但不是竞争轴 |

---

## 六、建议路线图

**第 1 批 · 让它真能干活的（P0，约 3-4 周）**

```
P0-1 编辑协议 ─┬─→ P0-4 工具事件下行 ──→ (UI: diff 面板 / 文件树高亮)
P0-2 终端重做 ─┘
P0-3 搜索可用性      （独立，可并行）
P0-5 HITL + 边界     （绑定 taxonomy 收口一起做）
```

- 并行建议：P0-1 + P0-3 一人，P0-2 一人，P0-5 由做重构的人顺手带走，P0-4 待 1/2 出接口后接上。

**第 2 批 · 平权（P1，约 3-4 周）**

- 先做 **P1-8（规则文件 + 每轮记忆注入，S-M，立竿见影）** 与 **P1-7a（git 工具，M）**。
- 再 **P1-6 自验证闭环**（依赖 P0-2/P0-5）、**P1-10 计划/熔断**（依赖 P0-5）、**P1-9 repo map**。
- **P1-11 子代理 + 并行工具**放本批末尾（依赖 P0-4/P1-10）。

**第 3 批 · 差异化（P2）**

- **P2-15 MCP**（用外部生态补长尾，但必须在 P0-5 之后）
- **P2-16 成本/上下文可视化**（数据已备，纯暴露层）→ **P2-13 模型路由** → **P2-12 轮内压缩** → **P2-17 回归评测**

**贯穿原则**：每一项都优先复用你们已有的资产——`ExecutionTool` 模板方法、`notifications` 广播、ChromaDB/embedding、trajectory 的 usage 记录、todo 模块。**先接线，再造轮子。**

---

## 附录 A　证据索引

`✅` = 本次逐行亲自复核；`◻` = 子代理读取，方向一致但未二次逐行验证。

| 论断 | 位置 | 核对 |
|---|---|---|
| 图结构 `compress → agent ⇄ tools`，无轮内压缩 | `src/thumbelina/agent/graph.py:574-592` | ✅ |
| 压缩阈值默认 0.8 | `src/thumbelina/config/models.py:161-162` | ✅ |
| 工具串行执行 | `src/thumbelina/agent/nodes.py:71-94` | ✅ |
| 工具错误转字符串回喂 | `src/thumbelina/agent/nodes.py:88-94`、`tools/base.py:87-89` | ✅ |
| 无 `recursion_limit`/`max_iterations` | `grep` 于 `src/` 全库零命中 | ✅ |
| 流式丢弃 tool_calls chunk | `src/thumbelina/agent/graph.py:1246-1249` | ✅ |
| 流式丢弃 compress 节点事件 | `src/thumbelina/agent/graph.py:1239-1241` | ✅ |
| 前端 WS 无 tool 事件类型 | `frontend/src/hooks/useWebSocket.ts:4-26` | ✅ |
| `Confirm` = 记日志后放行 | `src/thumbelina/tools/base.py:81-85` | ✅ |
| HITL 列为范围外 | `docs/specs/2026-08-29-tools-taxonomy-design.md:110-112, 214` | ✅ |
| shell 30s 硬编码 / 无流式 / 无持久 cwd / 已 kill | `src/thumbelina/tools/execution.py:30,127-145` | ✅ |
| shell 仅匹配命令文本，不校验路径；无工作区兜底 `os.getcwd()` | `src/thumbelina/tools/execution.py:115-125,128` | ✅ |
| 危险/确认/保护路径三张表 | `src/thumbelina/tools/execution.py:32-56` | ✅ |
| `write_file` 整文件覆写、无 diff/备份、`resolve` 为 None 时未校验 | `src/thumbelina/tools/execution.py:172-185` | ✅ |
| `read_file` 无行范围、1MB 截断 | `src/thumbelina/tools/perception.py:59-60,117-120` | ✅ |
| `search_files` rglob 全量读入、无目录黑名单、无二进制判定、截断不标注 | `src/thumbelina/tools/perception.py:156-205` | ✅ |
| `_truncate` 已定义但搜索未走 | `src/thumbelina/tools/perception.py:35-39` vs `:195-199` | ✅ |
| 无工作区时 `_resolve_target` 返回未校验绝对路径 | `src/thumbelina/tools/perception.py:42-47` | ✅ |
| 子代理为一次裸 LLM 调用，无工具/上下文 | `src/thumbelina/subagents/manager.py:86-100` | ✅ |
| 记忆 L0 仅首轮注入 | `src/thumbelina/agent/graph.py:886-892` | ✅ |
| 不读任何项目规则文件 | `grep -i "AGENTS.md\|CLAUDE.md\|\.cursorrules"` 于 `src/` 零命中 | ✅ |
| 无 git / 无 LSP/AST 代码检索 / 无 edit 工具 | 上述 grep 零命中（`plugins/sandbox.py` 的 `ast` 与此无关） | ✅ |
| `todo` 模块未接入 agent | `grep` 于 `agent/`、`tools/` 零命中 | ✅ |
| composition/channel 工具仍是内联工厂 | `src/thumbelina/agent/graph.py:207-319,454-459` | ✅ |
| 工具装配入口 | `src/thumbelina/api/app.py:473-477`、`cli/chat.py:248-252` | ✅ |
| `fs` 路由可枚举全盘 + 鉴权仅在有 secret_key 时启用 | `src/thumbelina/api/routes/fs.py:44-60`、`api/app.py:752` | ✅ |
| `self_verify` 中 `_ERROR_HINTS` 为死代码 | `src/thumbelina/tools/execution.py:146-151` | ✅ |
| trajectory 记录内容 / KV-cache 命中 | `src/thumbelina/agent/trajectory.py`、`api/routes/trajectory.py` | ◻ |
| 技能匹配为关键词子串、只注入 top-1 | `src/thumbelina/skills/application.py`、`graph.py` | ◻ |
| 摘要 prompt 要求保留未完成 TODO | `src/thumbelina/agent/compression/summarizer_context.py` | ◻ |
| 无按步模型路由、无 structured output、无 retry | `graph.py`、`llm/` | ◻ |
| coder 角色提示仅 10 行 | `src/thumbelina/prompts/roles/coder.md` | ✅ |

## 附录 B　复核命令

```bash
cd F:/projects/thumbelina
git rev-parse --short HEAD                                   # 基线锚点
sed -n '574,592p' src/thumbelina/agent/graph.py               # 图结构：无轮内压缩
sed -n '1239,1249p' src/thumbelina/agent/graph.py             # tool_calls chunk 被丢弃
sed -n '81,85p' src/thumbelina/tools/base.py                  # Confirm = 放行
sed -n '127,146p' src/thumbelina/tools/execution.py           # shell：30s/缓冲/已 kill
sed -n '176,205p' src/thumbelina/tools/perception.py          # search：rglob 全量读入
grep -rn "recursion_limit\|max_iterations" src/               # 空 = 无循环上限
grep -rni "AGENTS.md\|CLAUDE.md\|\.cursorrules" src/          # 空 = 不读规则文件
grep -rn "from thumbelina.todo" src/thumbelina/agent/         # 空 = TODO 未接入
```

## 附录 C　参考资料

**Claude Code**
- Checkpointing / rewind：https://code.claude.com/docs/en/checkpointing
- 子代理与并行（subagents / agent teams / workflow）：https://code.claude.com/docs/en/agents
- 权限模式与沙箱：https://code.claude.com/docs/en/permissions
- Hooks 事件清单：https://code.claude.com/docs/en/hooks
- 记忆与 `CLAUDE.md`：https://code.claude.com/docs/en/memory
- Code Review（多 agent + 验证 pass）：https://code.claude.com/docs/en/code-review
- 可观测性（OTel）：https://code.claude.com/docs/en/monitoring-usage

**OpenAI Codex CLI**（`codex-rs`：unified_exec / execpolicy / landlock / bwrap / windows-sandbox / rollout / features）
- https://github.com/openai/codex/tree/main/codex-rs

**Cursor**
- 检索工具与 Explore 子代理：https://cursor.com/docs/agent/tools/search
- Agent Review / `BUGBOT.md`：https://cursor.com/docs/agent/agent-review

**Qoder**
- 知识引擎总览（Repo Wiki + Knowledge Card + Memory）：https://docs.qoder.com/user-guide/knowledge-engine/overview
- Repo Wiki：https://docs.qoder.com/user-guide/repo-wiki
- Experts Mode：https://docs.qoder.com/user-guide/quest/experts-mode
- Ultra Review 三段式判定门：https://docs.qoder.com/user-guide/chat/ultra-review
- 上下文压缩（官方承认有损）：https://docs.qoder.com/qoder/context-compaction

**CodeBuddy**
- `/cost`（含 cache-read）与 `/context`：https://www.codebuddy.ai/docs/cli/costs
- Web UI（chat + 多终端 + logs + monitor，与本项目架构最接近）：https://www.codebuddy.ai/docs/cli/web-ui
- 监控与 HTTP API：https://www.codebuddy.ai/docs/cli/monitoring

**Aider**
- Repo map（token 预算化的符号摘要，最省的定位原语）：https://aider.chat/docs/repomap.html
