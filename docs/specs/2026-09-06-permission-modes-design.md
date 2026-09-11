# 权限模式设计：只读 / 工作区写入 / 全区写入 / 完全访问 / 自动（chat 与 coder）

日期：2026-09-06（v3；v2 经四路评审修订，v3 按用户决定新增"全区写入"并调整模式可见性）
状态：待评审
关联：`docs/specs/2026-08-29-tools-taxonomy-design.md`（工具五类分类与 security_review 三态）

> **v2 修订说明**：初稿经四路独立评审（interrupt 回路正确性 / 安全攻击面 / 前端与协议 /
> 完整性与事实核查，含 langgraph 1.2.7 最小复现实验），修正了 2 处设计事实错误
> （无人值守入口调用方式、subagent 工具回路）、1 个 P0 提权链（schedule_task），并补全
> 审批等待期的连接冻结、重连恢复、Windows 分级规则等缺口。代码锚点一律使用**函数名**，
> 不用裸行号（评审期间工作区有并发修改，行号会漂移）。
>
> **v3 修订说明**（用户决定）：① 新增第五种模式**全区写入（global_write）**——文件与
> 命令面放开到全盘，但应用内部保护路径仍需标红确认；完全访问（full_access）相应上移为
> "保护路径亦可直接写"（v2 中 full_access 对保护路径是 confirm，v3 起移到 global_write）。
> ② 普通对话（chat）不显示"工作区写入"选项（无工作区，该模式无意义）；模式选择器按会话
> 类型过滤可见项。

---

## 1. 背景与目标

当前所有 agent 工具调用**一律直接执行**：`run_shell` 的 `CONFIRM_PATTERNS`（git 强推、sudo、
npm publish 等）命中后仅打 WARNING 日志即放行（`tools/base.py` `_arun` 内 Confirm 分支，
注释明言"枚举保留三态为 HITL 留接口"），普通写操作无任何闸门。用户期望在聊天（chat）
与码农（coder）两类会话中引入权限约束，支持五种模式（严格递增的能力阶梯）：

1. **只读（read_only）**——不产生**本地**副作用（网络外呼保留，见 §3.1 残留声明）；
2. **工作区写入（workspace_write）**——本地副作用限制在工作区边界内（shell 缺口见 §4.4）；
   仅 coder 会话可用（chat 无工作区，选择器不显示该选项）；
3. **全区写入（global_write）**——文件与命令面放开到**整个磁盘**，但应用内部保护路径
   （记忆库、数据库、.env 等）仍标红确认；
4. **完全访问（full_access）**——全区写入之上，连应用内部保护路径也可直接写；危险命令
   仍标红确认；
5. **自动（auto）**——完全访问的免确认形态（无人值守受信自动化，研究结论：可行，§5.3）。

目标：
- 后端强制（不是提示词约定）：权限在工具执行前裁决，越权调用被拒绝并反馈给 LLM；
- 危险操作在 Web UI 标红，交互式批准/拒绝；
- chat 与 coder 会话均可设置，会话级持久化，Web UI 可切换；
- 无人值守路径（微信、QQ、调度器、HTTP、CLI 非 TTY）有明确的 fail-closed 语义。

非目标（本期不做）：
- 对抗性沙箱（shell 逃逸、解释器嵌套绕过）——沿用 tools-taxonomy spec §11 定位声明，
  权限层是**行为塑形 + 审批闸门**，不是安全边界；系统级隔离由部署边界承担；
- 按工具/按路径的细粒度白名单配置；全局权限默认值配置（扩展路径见 §12）；
- 插件代码的信任治理（插件加载 = 进程内任意代码执行，见 §9 范围声明）。

---

## 2. 现状盘点（代码事实，设计依据）

| 事实 | 位置（函数锚点） | 对设计的意义 |
|---|---|---|
| 工具统一继承 `ThumbelinaBaseTool`，`_arun` 模板强制 `security_review → _execute → self_verify`，`Confirm` 态预留 HITL | `tools/base.py` `_arun` | 审批闸门有现成接缝 |
| `RunShellTool.security_review`：`DANGEROUS_PATTERNS`→Reject、`CONFIRM_PATTERNS`→Confirm(现放行) | `tools/execution.py` | 分级规则已存在，复用；**规则集 POSIX 偏置**（§4.3） |
| `WriteFileTool.security_review`：工作区边界 + 保护路径→Reject | `tools/execution.py` | global_write 下保护路径为标红确认、full_access 起放行（§3.3）；**目录类守卫有锚定盲区**（§4.5） |
| 工作区经 ContextVar 注入（`workspace_context.py` `set_workspace`/`get_workspace`），对 LLM 不可见 | `tools/workspace_context.py` | 权限模式与审批者标志用同一注入模式 |
| **入口调用方式分化**：WS 走 `agent.stream()`；HTTP（`routes/chat.py` HTTP 聊天路由）、微信（`wechat_channel.py`）、QQ（`qq_channel.py`）、调度器（`api/app.py` `_make_prompt_runner._run_prompt`）、CLI（`cli/chat.py`）全部走 `agent.run()` → `graph.ainvoke` | 各文件 | interrupt 在 `ainvoke` 上**不抛异常**而是返回 `__interrupt__`（实验证实）→ run() 入口绝不能触发 interrupt，闸门必须入口感知（§5.3） |
| **`apply_conversation_runtime` 仅三处调用**：HTTP 聊天路由、WS `_run_generation`、微信通道。**调度器 `_run_prompt`、QQ 通道、CLI 均不调用** → 这些入口不设 workspace/权限 ContextVar | `api/routes/chat.py` `apply_conversation_runtime`；`api/app.py` `_run_prompt` | ContextVar **默认值必须是 read_only**（fail-closed）；`_run_prompt`/QQ 需显式接线（§8） |
| 自定义 `tool_node`（`agent/nodes.py`），`asyncio.gather` 并发执行；`_tool_node_node`（`agent/graph.py`）包装并经 custom stream writer 发 `tool_start/tool_end`、写 trajectory | `agent/graph.py`、`agent/nodes.py` | 闸门放在 `_tool_node_node` **函数体第一件事**（在 trajectory 记录与 tool_start 发射之前），防重放重复（§5.2） |
| checkpointer 硬性要求（`AsyncSqliteSaver`，thread_id=会话 id）；uv.lock：langgraph 1.2.7 | `agent/checkpointer.py` | `interrupt()/Command(resume)` 完全可用（实验证实，§5.3） |
| WS 主循环在生成期间持续 `receive_text()`（stop 先例）；**但普通消息帧会触发内联 `await _wait_task_cleared(current_task)`** | `api/websocket.py` `websocket_chat` 主循环 | 审批等待期收到新聊天消息会**冻结主循环**（帧无人读取→心跳判死）→ 必须改语义（§5.4） |
| 会话表已有 `mode`/`workspace`/`thinking_*`；`ensure_schema()` 自动加列 | `repository/models.py` | 新增 `permission` 列零迁移负担 |
| **subagent worker 已有工具回路**（v1 初稿写作后被并发开发引入）：`SubagentManager.set_tools` 注入工具后 `_run_tool_loop` 自行 `bind_tools` 并**直接调用 `agent.nodes.tool_node`**——绕过主图 `_tool_node_node` 闸门；当前装配仅注入感知类工具（`api/app.py`、`cli/chat.py` 的 `set_tools` 调用） | `subagents/manager.py` `_run_tool_loop` | v1 约束：subagent 白名单保持感知类 + `_run_tool_loop` 接入同一裁决函数（§9） |
| 前端工具栏组合 `ThinkingSelector`/`RoleSelector` 等，Chat/Coder 共用 `ChatWindow`；WS 帧分发集中在 `useWebSocket.ts`（自动重连+心跳已有） | `frontend/src/components/Chat/ChatWindow.tsx`、`hooks/useWebSocket.ts` | 权限选择器与审批卡有成熟模式；重连恢复有现成挂点 |
| 插件 TOOL 类型**当前无 agent 桥接**（`Plugin` 是数据类，`list_by_type` 无调用方，agent 工具=内置+派生工厂） | `plugins/manager.py`、`api/app.py` 装配 | 矩阵今日覆盖完备；需前瞻条款（§3.3 未知类别 fail-closed） |

工具清单与类别归属（v2 修正：以代码中 `category` 声明为准）：

- **PERCEPTION**：`read_file` `list_directory` `search_files` `search_text` `parse_json`
  `parse_csv` `analyze_text` `fetch_url` `web_search`
- **EXECUTION**：`run_shell` `write_file` `remember`（`RememberTool` 继承 ExecutionTool，
  唯一合法 MEMORY/ 写路径）`list_skill_compositions` `create_skill_composition`
  `execute_skill_composition`
- **COMMUNICATION**：`notify_user_by_channel`
- **COLLABORATION**：`create_subagent` `list_subagents`
- **EVENT_TRIGGER**：`schedule_task` `list_scheduled_tasks`

> 评审勘误：初稿把 `list_subagents`/`list_scheduled_tasks`/`list_skill_compositions`/
> `remember` 归为"感知"。它们的实际 category 是 COLLABORATION/EVENT_TRIGGER/EXECUTION。
> 因此 **read_only 的放行判定必须按 (工具名, 类别) 双键白名单，不能只按 category**（§3.3）。

---

## 3. 权限模型

### 3.1 五种模式

```python
class PermissionMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    GLOBAL_WRITE = "global_write"
    FULL_ACCESS = "full_access"
    AUTO = "auto"

LADDER: tuple[PermissionMode, ...] = (  # 严格递增，供"无人值守上限降级"取 min
    READ_ONLY, WORKSPACE_WRITE, GLOBAL_WRITE, FULL_ACCESS, AUTO,
)
```

- **read_only**：放行 = 全部感知类工具 + 只读名册（`search_memory` `read_memory`
  `list_subagents` `list_scheduled_tasks` `list_skill_compositions`）+
  `notify_user_by_channel`（收窄后，§4.6）。执行/事件触发/协作写/记忆写一律拒绝。
  **承诺措辞**："无本地副作用"——`fetch_url`/`web_search` 保留（外泄/SSRF 残留见 §12）。
- **workspace_write**：只读集之外，允许 `write_file`（严格工作区边界内）、`run_shell`
  （cwd 锚定 + §4.4 收紧规则）、`remember`/`create_subagent`/技能组合工具；
  **`schedule_task`（prompt 模式）需标红确认**（§3.3 提权链）。
  **仅对 coder 会话有意义**：chat 会话未绑定工作区时实际等效只读（UI 不显示该选项，
  见下方可见性规则；后端保留该等效规则作为兜底）。
- **global_write**：workspace_write 的无边界版——`write_file` 可写**任意路径**（含绝对
  路径、越出工作区）、`run_shell` 同 workspace_write（cwd 锚定 + 收紧规则，常规命令
  放行）。**应用内部保护路径仍标红确认**（§4.5：记忆库、数据库、.env、角色提示词、
  插件目录等——用户文件放开，助手自身的"大脑与配置"不放开）。
- **full_access**：global_write 之上，**保护路径亦可直接写**（应用数据/配置可改；
  DANGEROUS 硬底线仍拒绝）；危险命令（CONFIRM 组）仍标红确认。
- **auto**：full_access 的免确认形态——标红类自动放行（WARNING 日志 + 轨迹 `auto_allowed`
  标记），黑名单仍拒绝。面向无人值守的受信自动化。

**默认值**：存量会话与新建 **chat** 会话默认 `full_access`（能力等同现状，新增的是危险
操作确认——本需求的预期行为变更）；新建 **coder** 会话默认 `workspace_write`。
**硬性约束**：chat/coder 默认值不同无法用单一列 server_default 表达——coder 默认必须由
创建路由显式传值（`WorkspacePicker` → `createConversation({mode:'coder', workspace,
permission:'workspace_write'})`），`CreateConversationRequest` 增加 `permission` 可选字段。

**选择器可见性（v3 新增）**：模式选择器按会话类型过滤可见项——

- chat 会话：只读 / 全区写入 / 完全访问 / 自动（**不显示工作区写入**——chat 无工作区，
  该模式无意义）；
- coder 会话：五项全显。

兜底规则：若会话记录中的 `permission` 不在可见集内（如历史数据 chat + workspace_write），
选择器仍如实显示当前值并附加"该会话无工作区，实际等效只读"提示；生效裁决按 §3.3 矩阵
的"chat 无工作区"行执行。

### 3.2 三态裁决

```python
@dataclass
class PermissionDecision:
    verdict: Literal["allow", "confirm", "deny"]
    risk: Literal["normal", "dangerous"]   # dangerous → UI 标红
    reason: str                            # 稳定规则键（如 "rule.sudo"），非自由文本
```

- `allow`：直接执行；
- `confirm`：需要用户批准。**有审批者的入口**（WS、CLI-TTY）→ interrupt 等待；无人值守 →
  `auto` 模式放行，其余一律 **deny**（fail-closed，不产生 interrupt，§5.3）；
- `deny`：拒绝执行，向 LLM 返回 `Error: 权限拒绝: <规则键>` 的 ToolMessage（不中断循环）。

`reason` 一律下发**稳定规则键**（`rule.sudo`、`rule.protected_path` 等），前端经 i18n 映射
为本语言文案——后端不下发中文自由串（多语言与测试友好）。

### 3.3 判定矩阵（单一事实源：`evaluate_tool_call`）

| 操作 | read_only | workspace_write | global_write | full_access | auto |
|---|---|---|---|---|---|
| 感知类工具 + 只读名册（§3.1） | allow | allow | allow | allow | allow |
| `notify_user_by_channel`（user_id 收窄后） | allow | allow | allow | allow | allow |
| `write_file` 工作区内（coder） | deny | allow | allow | allow | allow |
| `write_file` 越界/绝对路径 | deny | deny | allow | allow | allow |
| `write_file` 保护路径（§4.5 清单） | deny | deny | **confirm(红)** | allow | allow |
| `run_shell` 常规命令 | deny | allow（cwd=工作区） | allow | allow | allow |
| `run_shell` 命中 CONFIRM 组（含 §4.3 Windows 组、§4.4 写穿收紧） | deny | **confirm(红)** | **confirm(红)** | **confirm(红)** | 放行+WARNING 日志 |
| `run_shell` 命中 DANGEROUS 组（含 §4.3 Windows 组） | deny | deny | deny | **deny（硬底线）** | deny |
| `schedule_task` prompt 模式 | deny | **confirm(红)** | **confirm(红)** | **confirm(红)** | 放行+日志 |
| `schedule_task` notify/纯提醒模式 | deny | allow | allow | allow | allow |
| `remember` / `create_subagent` / 技能组合工具 | deny | allow | allow | allow | allow |
| chat 会话（无工作区）下的 `write_file`/`run_shell` | deny | deny（无边界） | allow | allow | allow |
| **未知类别/未登记工具**（含未来插件工具） | deny | deny | **confirm(红)** | **confirm(红)** | **confirm(红)** |

矩阵要点（评审修订 + v3 调整）：
1. **`schedule_task` prompt 模式在非 auto 模式下一律 confirm**——定时任务到点后会以固化
   的指令文本无人值守跑完整 agent 图（`api/app.py` `_run_prompt` 克隆主 agent 执行
   `isolated.run(task.content)`），workspace_write 下直接放行等于"低权限会话铸造无人值守
   高权限执行体"的提权链。notify/纯提醒模式无此风险，保持 allow。
2. **未知类别 fail-closed**：`evaluate_tool_call` 对未登记 (name, category) 的裁决——
   read_only/workspace_write 下 deny，global_write/full_access/auto 下 confirm（auto 也
   不放行未知类别）。这为未来插件 TOOL 接入预置安全默认：唯一合法接入路径是包装为
   `ThumbelinaBaseTool` 并显式声明类别。
3. read_only 的放行名册按**工具名**枚举（§2 勘误的修正手段），category 仅作兜底分类。
4. **保护路径的档位随 v3 上移**：global_write 下 confirm(红)（用户文件放开、助手内部
   不放开）、full_access 起直接 allow——保证五档严格递增，full_access 的增量恰好是
   "连助手自身的记忆/数据库/配置都可写"。
5. 矩阵由**一个纯函数**实现（`tools/permissions.py::evaluate_tool_call`），
   `RunShellTool`/`WriteFileTool` 的 `security_review` 委托同一分类器，避免规则双写漂移。

---

## 4. 危险操作分级与标红

### 4.1 分级（沿用现有规则表 + 评审补强）

- **confirm 级（标红确认）**：`CONFIRM_PATTERNS`（git 强推、npm publish、docker rm/rmi、
  sudo、写系统路径）+ **Windows 系统路径组**（§4.3）+ **workspace_write 写穿收紧**
  （§4.4）+ **global_write 下的保护路径写入**（full_access 起直接放行，§3.3 要点 4）+
  `schedule_task` prompt 模式。
- **deny 级（硬底线）**：`DANGEROUS_PATTERNS` + workspace_write 下的越界写。

### 4.2 硬底线不因任何模式放开

`DANGEROUS_PATTERNS` 在包括 full_access/auto 的所有模式下 Reject。该表覆盖的操作在对话
场景中没有正当用例，且黑名单非对抗性边界——放开不换取能力，只增加自伤面。

### 4.3 Windows 分级规则组（评审补强：Windows 是主部署平台）

证据：`tools/execution.py` `_kill_process_tree` 的 nt 分支（`taskkill /F /T`）、
`create_subprocess_shell(shell=True)`、uvicorn --reload 下线程池 `shell=True` 兜底——
生产路径是 Windows cmd.exe/PowerShell。现有规则全部 POSIX 语义（`rm`/`mkfs`/`dd`/
`>/etc/`），在主平台上**几乎不命中**。

新增规则组（并入共享分类器）：
- DANGEROUS（deny）：`rd /s /q`、`Remove-Item -Recurse -Force`（删根/通配）、`format`、
  `cipher /w`、`vssadmin delete shadows`、`bcdedit`、`powershell -enc`（编码执行）。
- CONFIRM（标红）：盘符根重定向 `>\s*[A-Za-z]:\\`、`C:\Windows`/`system32`/`Program Files`/
  `ProgramData` 写入、`reg add`、`schtasks`、`sc` 服务操作、`Set-Service`。
- 已知误报（`sudo` 在 Windows 命中文件名等）并入 spec §11 既有 best-effort 免责声明。

### 4.4 workspace_write 下 run_shell 的写穿收紧（评审补强）

现状：shell 无沙箱（cwd 锚定非边界），`echo x > /etc/x`、`cp y C:\Users\...` 不命中任何
规则即写穿工作区——与 workspace_write 的产品承诺矛盾。收紧规则（一行分支，不阻断日常
编码用例）：

> workspace_write 下，命令**含写重定向（`>`/`>>`）或写命令（cp/mv/copy/move/tee/
> Set-Content/Out-File/mv 等）且目标为绝对路径或盘符路径** → confirm(红)。
> 相对路径（工作区内目标）保持 allow。

残余风险在 §12 明文声明（解释器嵌套、引号变形不可文本判定）。

### 4.5 保护路径清单与锚定盲区修复

清单补充：在 `PROTECTED_PATH_PATTERNS`（thumbelina.db、MEMORY/、prompts/roles/、plugins/、
.env）基础上增加 **`TODO/`**（任务清单被改写可社会工程用户）与 **`attachments/`**
（覆盖后经 WS→WeChat 转发链注入对端内容）。`data/`、`snapshots/` 经查无对应目录，不列入。

**锚定盲区修复**（评审发现）：目录类守卫只锚定"workspace 相对前缀分段"。当会话工作区
≠ 进程 CWD（coder 普遍情况）时，绝对路径 `F:\projects\thumbelina\MEMORY\x.md` 的分段以
盘符开头，目录类守卫全部不命中——global_write 下连 confirm 都没有。修法：启动时把已知
app 目录（MEMORY、prompts/roles、plugins、TODO、attachments——取自 config 实际解析值）
解析为**绝对路径**作为第二锚点做前缀比较。文件名类守卫（thumbelina.db*、.env*）无此盲区，
保持不变。

### 4.6 审批卡展示硬化与通知收窄

- **审批卡展示**：run_shell 展示**归一化后的命令**（分类器实际输入：续行已折、注释已剥，
  `_normalize_command`），等宽字体+固定高度滚动区，超 ~500 字符折叠为首尾摘要+展开，
  命中规则的 call 默认展开；逐行渲染多行命令。
- **`notify_user_by_channel` 收窄**（工具端独立加固，与矩阵解耦）：`user_id` 仅允许该
  channel 的 `last_user_id`，消除"向任意 IM 用户发消息"的滥发/仿冒面。

---

## 5. 后端架构

### 5.1 新模块 `src/thumbelina/tools/permissions.py`

```
PermissionMode(StrEnum)            # 五模式；LADDER 严格递增序（§3.1），供无人值守上限取 min
PermissionDecision                 # 三态 + risk + reason(稳定规则键)
evaluate_tool_call(mode, name, category, args, has_workspace) -> PermissionDecision
classify_shell_command(cmd) -> PermissionDecision   # 从 execution.py 上移，唯一事实源
set_permission_mode(mode) / get_permission_mode()   # ContextVar；默认 READ_ONLY（fail-closed）
set_approval_context(has_approver: bool) / has_approver()   # ContextVar；默认 False（fail-closed）
effective_mode(mode, is_unattended, has_workspace)  # 无人值守上限降级（§8）：min(mode, workspace_write)
```

两个 ContextVar 均由每轮 `apply_conversation_runtime` 设置（`set_permission_mode` +
`set_approval_context`），工具级 `security_review` 与闸门读同一上下文；对 LLM 不可见。

**默认值是安全的关键**（评审 P0）：`get_permission_mode()` 默认 read_only、`has_approver()`
默认 False——任何忘记接线的入口（现状：调度器、QQ、CLI 都不调 apply_conversation_runtime）
自动落入"只读 + 无审批者"，静默 fail-closed 而非 fail-open。§8 给出各入口的显式接线要求。

### 5.2 执行闸门 + 工具绑定过滤

**闸门**：`_tool_node_node`（`agent/graph.py`）**函数体第一件事**（在 trajectory 记录与
tool_start 发射之前——评审实验证实：interrupt 后节点重放，若闸门放在发射之后会产生重复
tool_start 帧与重复 trajectory tool_call 记录）逐 call 评估：

1. 全部 `allow` → 照常执行（现有路径零改动）；
2. 存在 `deny` → 合成拒绝 ToolMessage（**保持 tool_calls/ToolMessage 配对不变量**——
   每个 tool_call 恰好一条 ToolMessage，`should_continue`/LLM API 均依赖），其余照常执行；
3. 存在 `confirm` 且 `has_approver()` → **先 `interrupt()`，不执行本批任何 call**；
4. 存在 `confirm` 且无审批者 → 按 §3.2 结算：auto 放行（标记 `auto_allowed`），否则合成
   拒绝 ToolMessage——**绝不调 interrupt**（run() 路径的 fail-closed 就在这里完成）。

闸门代码自身**绝不能包进 `except Exception`**（`GraphInterrupt` 继承自 Exception，实验
证实被吞后 interrupt 静默失效——`nodes.py` `_invoke_one` 的 catch 不在闸门到节点出口
之间的传播路径上，保持现状即可）。

**绑定过滤**：`_call_model_node` 在 `bind_tools` 前按模式过滤工具列表（read_only 剔除
执行/事件触发/协作写/记忆写类）。从源头减少越权尝试；闸门仍保留，防历史重放与注入式
tool_calls。

**trajectory**：verdict/reason 记在 `record_tool_call` 的 payload（被 deny 的 call 不产生
tool_result）；payload 为自由 dict 序列化，加字段向后兼容（`agent/trajectory.py`）。

### 5.3 审批回路：LangGraph interrupt/resume（自动模式研究结论）

**结论：支持。** langgraph 1.2.7 + 硬性 checkpointer（thread_id=会话 id）。评审以最小
复现脚本实验证实了全部关键语义：

- 对含 interrupt 的图 `astream(...)` **正常结束迭代、不抛异常**，interrupted 态经
  `graph.aget_state(config)` 的 `StateSnapshot.tasks[].interrupts` 读取（astream 不投递
  `__interrupt__` chunk）；
- 对 interrupted 线程 `astream(Command(resume=decisions), stream_mode=["messages","custom"])`
  合法且事件流自然衔接（仅被中断的 tools 节点重放，compress 不重跑）；
- `interrupt()` 把 resume 值**整体原样返回**——单 interrupt + 一次批量决策 payload 匹配；
- resume 后节点从头重放，闸门确定性重评估到同一 confirm 集合，`interrupt()` 返回决策值，
  幂等成立；
- interrupt 前无任何工具副作用 → checkpoint 无半执行状态；
- **run()（ainvoke）路径遇 interrupt 不抛异常**：返回值含 `__interrupt__`、最后一条消息是
  空串 AIMessage——这正是无人值守入口绝不能触发 interrupt 的原因（§5.2 第 4 条）。

回路设计（仅 WS 与 CLI-TTY 入口）：

```
工具批含 confirm 且有审批者
  → 闸门 interrupt(payload)               # 检查点落盘，astream 以 interrupted 态结束
  → stream() 经 aget_state 检测 interrupts
  → yield {"type":"permission_request", "request_id": Interrupt.id, ...} 后 await broker
  → WS 广播 permission_request 帧到所有连接（broadcast_chat_message 既有设施）
  → 任一连接发 permission_response → WS 主循环解析 → broker 结算
  → stream() 内 graph.astream(Command(resume=decisions), config) 继续（复用同一 config）
  → 批准项执行、拒绝项合成拒绝 ToolMessage，后续事件照常透传
```

硬约束（评审 P2，违反则静默产生垃圾轮次）：
- **resume 必须复用本轮 `stream()` 内的同一 `config` 对象**（thread_id 一致性；无会话路径
  的临时 uuid4 thread 也因此成立）。禁止把 resume 实现为独立的下一轮调用——对无 pending
  interrupt 的线程 `astream(Command(resume))` **不报错**，会把 resume 当普通输入跑一轮空
  上下文。`_run_config` 处加注释固化。
- **request_id 直接采用 `Interrupt.id`**（langgraph 生成，稳定，免自造映射）。
- `stream()` 的收尾段（llm_usage 记录、auto-name、记忆抽取）必须放进"检测 interrupt →
  yield 请求 → await broker → resume astream"的**循环**包裹内，确保只在真正终局执行一次。
- 等待审批时 stop/断线照常 `task.cancel()`（CancelledError 传播路径干净，实验证实）；
  检查点停留 interrupted 态，下一轮新输入时 langgraph **直接丢弃 pending interrupt 任务**，
  悬空 tool_calls 由 compress 节点 `ensure_tool_pairing` 修复——自愈机制成立（实验证实）。

### 5.4 WS 协议变更（增量，向后兼容）

下行帧（服务端→所有连接广播，**顶层带 conversation_id** 与既有帧同构）：

```json
{"permission_request": {"request_id": "<Interrupt.id>", "calls": [
    {"call_id": "...", "name": "run_shell", "args": {"command": "..."},
     "risk": "dangerous", "reason": "rule.sudo"}]},
 "conversation_id": "..."}
```

上行帧（客户端→服务端，与 stop/ping 同层特判，**必须**在 `_wait_task_cleared` 阻塞点
之前处理——这是它能唤醒 broker 的唯一正确位置；不特判会落入 `WebSocketMessage` 校验
变 error 帧）：

```json
{"permission_response": {"request_id": "...", "decisions": [{"call_id": "...", "approved": true}]}}
```

语义修订（评审 P0/P1）：
1. **审批等待期收到普通聊天消息 → 回 error 帧（`code: "busy_pending_approval"`）**，
   不再内联阻塞等待——否则主循环冻结、后续 permission_response/stop/ping 全部无人读取，
   前端心跳判死掉线、审批丢失（死锁链已实验还原）。前端同时把"审批等待中"置为等效流式
   态走既有排队（`InputBox` `onQueueSend` / `pendingByConv`），双保险。
2. **广播 + 任一连接可响应**：request 广播到所有连接（`broadcast_chat_message`），
   broker 按 request_id 结算，接受任意连接的 response——解决多标签页盲区（另一端至少
   能看到卡片）。旧前端收到不识别帧会清掉 90s 超时定时器导致打字指示器长挂——发布顺序
   前端先行（既有约定），文档注明。
3. **error 帧增加机器可读 `code`**：`permission_unknown_request`（重复/过期响应）等
   协议类错误**不得**触发前端"终结当前轮次"的既有 error 处理（会掐死正在 resume 的轮次）；
   前端按 code 分流，协议类错误只清审批卡。
4. **连接建立与会话切换时下发未决审批快照**（broker 注册表查询）：解决重连丢卡与多标签页
   补显；重连 `onopen` 清理本端 stale 审批状态。
5. `tool_event` 帧增加 `verdict`（`allowed|confirmed|denied|auto_allowed`）：**由闸门/
   resume 合成路径负责发射**——denied call 发 `tool_start(verdict=denied)` +
   `tool_end(is_error=true, verdict=denied)`（否则前端红样式落空，工具面板显示绿色 ✓）。
   `--danger`/红色样式改用既有 `--error` token（`--danger` 从未定义，现状 10 余处引用
   本就是坏的；Phase 3 顺带在 themes.css 定义 `--danger: var(--error)` 别名）。

### 5.5 API 与持久化

- `Conversation.permission` 列（String(20)，server_default `full_access`）；
  `ensure_schema()` 自动加列。
- repository：`set_conversation_permission()`。
  （v3 实施简化：调度任务不再增加 `ScheduledTask.source_permission` 固化列——
  `_run_prompt` 在执行时对任务绑定的会话调 `apply_conversation_runtime(..., unattended=True)`
  **运行时继承**会话权限与工作区；用户改会话权限即改定时任务权限，语义一致且少一列。）
- 路由：`PUT /api/v1/conversations/{id}/permission`（body `{mode}`，枚举校验），
  仿 thinking 设置路由。
- `CreateConversationRequest` 增加可选 `permission`；coder 创建显式传 `workspace_write`
  （§3.1 硬性约束）。

---

## 6. 前端设计

### 6.1 组件与接线

- **`PermissionSelector`**：工具栏选择器（`ThinkingSelector` 同构），挂入 `ChatWindow`
  工具栏，Chat/Coder 共用。**可见项按会话类型过滤（§3.1）**：chat 只显
  只读/全区写入/完全访问/自动，coder 五项全显；历史数据中不在可见集的当前值仍如实
  展示并附等效只读提示。配色：只读（蓝）、工作区写入（绿）、全区写入（黄）、完全访问
  （橙+警示）、自动（红+警示）；chat 会话选中"全区写入/完全访问/自动"不提示、选中
  不可见的 workspace_write（历史值）时提示等效只读。切换即
  `PUT /conversations/{id}/permission`。与既有选择器一致加
  `if (!conversationId) return null` 守卫（会话创建前不显示，默认值在创建时决定）。
  prop 穿线触点（评审列明）：`ChatWindowProps` → `ChatRouteProps`（App）
  → `CoderPageProps` → App 处理器；coder 默认值落点 `WorkspacePicker` 的
  `createConversation`。
- **`PermissionRequestCard`**：作为 `MessageList` 新 prop 渲染（消息之后、typing 指示器
  之前，参照 subagent 卡先例）；出现时触发一次 snap-to-bottom。红色主题用 `--error`
  token（§5.4 第 5 条）。按钮点击即禁用（防双击重复 response）。生命周期：结算/断线/
  切换会话/清空消息时清除。等待期视觉态：关闭打字点、状态点进入"等待审批"，InputBox 的
  stop 按钮保持可用（取消=拒绝并终止轮次；"立即发送"排队消息会取消未决审批——UI 提示）。
- **`useWebSocket`**：`permission_request` 登记 pending 并把会话置为等效流式态（发送走
  排队）；`sendPermissionResponse()`；error 帧按 `code` 分流（协议类只清卡不终结轮次）；
  重连 `onopen` 清 stale 审批状态 + 处理服务端快照帧。
- **状态栏**：权限徽标**常显**（不进 `useStatusBarConfig` 开关——承载安全语义），复用
  `StatusBarItem` 的 `state` 三态映射五模式配色。
- **i18n**：新增 `permission.*` 命名空间，en/zh-CN 叶子键严格成对（`locales.test.ts`
  约束）。键清单：`selector.label/title/hiddenModeHint`（历史值等效只读提示）、
  `mode.{readOnly|workspaceWrite|globalWrite|fullAccess|auto}{,Desc}`、
  `card.{title,callsCount,riskBadge,ruleLabel,commandPreview,
  approveAll,denyAll,approveOne,waitingHint,resolvedApproved,resolvedDenied,expiredHint}`、
  `badge.title.*`、`toolCalls.verdict.{denied|confirmed|autoAllowed}`；`reason` 规则键
  （`rule.*`）由前端映射本语言。

---

## 7. 数据流总览

```
用户切换权限 → PUT /conversations/{id}/permission → conversations.permission
每轮开始 → apply_conversation_runtime → set_permission_mode + set_approval_context
LLM 产出 tool_calls → _tool_node_node 首行闸门（evaluate_tool_call × N）
  ├─ 全 allow → tool_node 执行
  ├─ 含 deny → 合成拒绝 ToolMessage（配对不变量保持）+ trajectory verdict
  ├─ 含 confirm + 有审批者 → interrupt(Interrupt.id) → 广播请求帧 → broker
  │     ├─ 批准 → Command(resume) → 执行
  │     └─ 拒绝/超时 → 合成拒绝 ToolMessage
  └─ 含 confirm + 无审批者 → auto 放行(标记) 或 合成拒绝（绝不 interrupt）
trajectory 全程记录 verdict（deny/confirm/auto_allowed + reason 规则键）
```

---

## 8. 入口矩阵与无人值守规则（v2 重写）

| 入口 | 调用方式 | 审批者 | 必须的接线（评审修正） | confirm 级行为 |
|---|---|---|---|---|
| Web WebSocket（chat/coder） | `stream()` | 有 | 既有 `apply_conversation_runtime` + `set_approval_context(True)` | 标红交互确认（广播+任一连接可响应） |
| HTTP `POST /api/v1/chat` | `run()` | 无 | 既有 runtime 接线 | deny（合成拒绝，随响应返回说明） |
| 微信通道 | `run()` | 无 | 既有 runtime 接线 | deny |
| **QQ 通道** | `run()` | 无 | **补**：调 `apply_conversation_runtime`（现状不调） | deny |
| 调度器 prompt 任务 | `run()`（`_run_prompt`） | 无 | **补**：读会话 permission + `set_permission_mode`（现状不设任何 ContextVar；同时补 `set_workspace` 修复工作区缺位） | deny（继承源会话 `source_permission`；auto 则放行） |
| CLI（TTY） | `run()` | 终端 | **补**：TTY 检测 + `set_approval_context(True)`；run() 返回含 `__interrupt__` 时终端 `[y/N]` → `graph.ainvoke(Command(resume=...), 同 config)` 续跑（同一 thread_id） | 终端确认 |
| CLI（非 TTY/管道） | `run()` | 无 | `set_approval_context(False)` | deny |

规则只有两条：
1. **没有审批者的入口不产生 interrupt**（闸门在 interrupt 之前结算），confirm 一律拒绝，
   除非会话显式为 auto；
2. **无人值守入口的有效上限 = workspace_write**（v3 表述）：按 §3.1 阶梯取
   `effective_mode = min(mode, workspace_write)`——global_write/full_access 在无审批者
   入口降级为 workspace_write 语义（会话绑定工作区时：工作区内写 + 锚定 shell；chat 无
   工作区时进一步降为 read_only）；confirm 级仍按规则 1 fail-closed。`auto` 是唯一完整
   豁免。存量默认 full_access 的微信/QQ 会话（均无工作区）由此从"无人值守全工具"收窄为
   "无人值守只读 + 拒绝说明"——这是有意的安全收紧，§12 声明。

---

## 9. 错误处理与边界情况

- **审批超时**（评审补充，必选非可选）：broker 带超时（config，默认 10 分钟）——超时按
  全部拒绝结算并下发帧。没有它，旧前端/无人在场场景会无限占用会话锁。
- **pending 期间 delete/clear/compress 阻塞**（评审补充）：这三个路由先抢
  `per_conversation_lock` 再动检查点——审批等待期会无限阻塞。以审批超时为兜底（最长等
  一个超时周期），文档明确该语义；不做路由侧强制取消（Phase 2 可选优化）。
- **手动压缩不毁 resume**（评审实验证实）：interrupted 线程上 `compress_conversation`
  的 `aupdate_state` 之后 `Command(resume)` 仍成功。新一轮输入会静默丢弃 pending
  interrupt——broker 须在每轮开始清理 stale request（旧卡点击命中
  `permission_unknown_request`，只清卡不伤轮次）。
- **resume 前会话被删**：broker 结算时校验 request_id 存活性；检查点线程已删则按 stop
  结算（下轮自愈）。
- **权限模式中途切换**：模式在每轮开始应用；已 interrupt 的轮次以 interrupt 时的模式
  裁决（resume 只回决策，不重评估模式）。
- **subagent 工具回路**（评审修正——该回路已存在且绕过主图闸门）：v1 约束两层：
  (a) 装配端白名单**只注入感知类工具**不变（`api/app.py`/`cli/chat.py` 的 `set_tools`
  调用点，写注释声明约束）；(b) `_run_tool_loop` 内每次 `tool_node` 调用前过
  `evaluate_tool_call`（subagent 继承创建时会话的模式，无审批者 → deny/按 auto）。
  白名单扩类必须同时过闸门——写成代码注释 + 测试。
- **范围与非范围声明**（评审补充）：权限闸门 = `_tool_node_node` 与 `_run_tool_loop`
  两个工具执行点。HTTP 管理路由（fs 目录浏览、attachments 上传、todo CRUD、git checkout）
  是**用户手动手面**，不在权限模型内，依赖部署边界（服务默认 loopback 绑定；`fs.py`
  的全盘枚举在非 loopback 绑定时是信息泄露面——部署文档既有假设）。插件加载
  （`exec_module`，advisory 模式有 violation 仍加载）= 进程内任意代码执行，权限模型
  不覆盖。
- **多标签页**：广播 + 任一连接可响应（§5.4）；排队生成在锁上等审批结算或超时。

---

## 10. 测试计划

- **单测（后端）**：
  - `test_permissions.py`：判定矩阵 mode × 操作全组合（含 chat 无工作区、global_write
    保护路径 confirm、full_access 保护路径放行、未知类别 fail-closed、Windows 规则组、
    schedule_task prompt/notify 分行、read_only 按名册放行、`effective_mode` 无人值守
    降级链）；
  - shell 分类器搬移后 `tests/test_tools/test_execution_review.py` 迁移直通（已核对存在）；
  - 闸门：deny 合成配对不变量；confirm 触发 interrupt 的 payload；resume 决策映射；
    **闸门位于节点首行**（重放不重复发射 tool_start/trajectory）；
  - 入口矩阵：run() 路径 confirm → deny 且**不**产生 interrupt（HTTP/微信/QQ/调度器）；
    `_run_prompt` 权限/工作区接线；QQ runtime 接线；
  - broker：超时 deny 结算、stale request 清理、任一连接响应、重复 response → error code；
  - ContextVar 默认值 fail-closed（未接线入口 = read_only + 无审批者）；
  - 迁移：`ensure_schema` 加列；`ScheduledTask.source_permission`。
- **集成测试**：AsyncSqliteSaver（内存 sqlite）+ TestClient WS：interrupt → 广播帧 →
  response → resume → done；stop-while-pending → 取消 + 下轮自愈；压缩不毁 resume；
  审批等待期发消息 → `busy_pending_approval` error 帧（主循环不冻结）。
- **前端（Vitest）**：Selector 四态与保存；PermissionRequestCard 交互/防双击/生命周期；
  useWebSocket 新帧分发 + error code 分流 + 重连恢复；i18n 键完整性。

---

## 11. 实施切分（供 writing-plans 阶段展开）

1. **Phase 1 策略层**（先行，行为兼容）：`permissions.py`（五模式枚举与 LADDER/判定矩阵/
   分类器上移/双 ContextVar 及默认值/`effective_mode` 无人值守降级）+ **Windows 规则组与
   写穿收紧** + **保护路径第二锚点 + 清单补充**
   + **notify user_id 收窄** + 列/API/创建路由 + `apply_conversation_runtime` 接线 +
   `_run_prompt`/QQ 显式接线 + 矩阵单测。
2. **Phase 2 闸门与审批回路**（风险核心）：绑定过滤 + 闸门（deny 合成/入口感知）+
   interrupt 检测（aget_state）+ stream() resume 循环 + broker（超时/广播/快照）+ WS 帧
   与 error code + denied tool_event 发射 + subagent `_run_tool_loop` 接入裁决 + 集成测试。
3. **Phase 3 前端**：Selector/审批卡/WS 接线/error 分流/状态栏/`--danger` token/i18n +
   组件测试。协议在 Phase 2 冻结后与后端并行。
4. **Phase 4 收尾**：CLI 终端确认回路、trajectory verdict 回放（Trajectory 页）、
   README/CLAUDE.md 更新。

---

## 12. 风险与开放问题

- **行为变更**：(a) 存量会话 confirm 类从自动放行变为需确认（web 端）；(b) 无人值守入口
  （微信/QQ/调度器）从"全工具免审"收窄为"只读 + 拒绝说明"（除非 auto）；(c) **v3**：
  full_access 起保护路径（记忆库/数据库/.env/角色提示词/插件/TODO/attachments）直接
  可写——应用自身数据与配置的修改在该档位无需确认（global_write 档仍需标红确认）；
  (d) chat 会话选择器隐藏工作区写入（无工作区，无意义）。依赖旧行为的自动化须显式设
  auto。**默认值不做全局配置**；扩展路径已备案——仿 `LLMConfig.role`
  先例（config 默认 + 会话列回退链），未来如需再加。
- **全区写入的风险知情（v3）**：chat 会话选 global_write 即等于"无任何路径边界的任意
  文件写入 + 锚定 shell"——这是该档位的产品语义（用户文件面放开），配合 §4.5 保护路径
  confirm 与 §4.2 硬底线兜底；无人值守入口按 §8 降级上限，不放大该风险。
- **read_only 残留（知情声明）**：`fetch_url`/`web_search` 可外泄上下文数据（query/URL
  即信道）、可 SSRF 本机未鉴权 API；read_only 可读任意本地文件（保护清单只管写）。
  read_only 的承诺措辞为"无本地副作用"。后续可选项：域名策略/内网段默认拒绝。
- **workspace_write 残留（知情声明）**：shell 写穿已按 §4.4 收紧至 confirm，但解释器
  嵌套/引号变形不可文本判定（spec §11 同源声明）。
- **插件加载 = 任意代码执行**：advisory 模式有 violation 仍加载；权限模型不覆盖，
  治理属插件信任体系。
- **审批卡社会工程**：命令文本可能含诱导内容——§4.6 展示硬化（归一化命令/折叠/等宽）
  缓解，不消除。
- **`create_subagent` 资源面**：任务文本任意 → LLM 消耗无上限（并发上限 5 已有），
  属成本面非安全面。
- **auto 滥用面**：HTTP API 无鉴权（单用户本地部署信任模型），能改权限的主体本就能做
  任何事——入口约束无增益，维持现状；缓解：auto 轮次 trajectory 记 `auto_allowed`，
  微信会话设 auto 后下次 reply 附带一次性提示。

---

## 附录 A：与既有 spec 的关系

- tools-taxonomy（2026-08-29）§9"范围外"首条「confirm 回路 HITL」：本设计是其落地。
- 工具可见性（2026-09-05）`tool_event` 协议：增量加 `verdict` 字段，透传链路零改动。
- 工作区边界（workspace_context.py）：复用 ContextVar 注入模式与边界函数。

## 附录 B：评审记录（2026-09-06）

四路独立评审（每路含代码取证，interrupt 路另有 langgraph 1.2.7 最小复现实验）：
1. **interrupt 回路正确性**：核心假设全部实验证实（astream 正常结束/Command(resume)
   续流/重放幂等/stop 自愈/thread_id 复用约束）。修正项：入口感知 fail-closed（run()
   不触发 interrupt）、闸门置于节点首行、resume 复用同 config、broker 超时。
2. **安全攻击面**：P0 = schedule_task 提权链（已入 §3.3/§8）；P1 = read_only 外泄残留、
   插件未知类别条款、Windows 规则缺口、保护路径锚定盲区、无人值守 full_access 上限
   （均已入 §3/§4/§8/§9/§12）。
3. **前端与协议**：P0 = 审批等待期发消息冻结链（已入 §5.4 第 1 条）；P1 = 重连恢复、
   多标签页广播、error code 分流、denied 事件发射责任、`--danger` token 缺失、i18n
   reason 策略（均已入 §5.4/§6）。
4. **完整性与事实核查**：A 部分引用基本精确（并发修改致行号漂移 → v2 改函数名锚点）；
   工具类别勘误 4 项（§2）；修正 run()/stream() 事实、subagent 工具回路、QQ 遗漏、
   pending 锁阻塞 delete/compress（均已入文）。
