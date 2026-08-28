# Tools 分类体系重构设计（BaseTool 继承层级 + 模板方法）

- 日期：2026-08-29
- 状态：已与用户逐节确认
- 方案：A（继承体系 + 模板方法），含安全审查与结果自验证的真实实现

## 1. 背景与目标

当前项目的 agent 工具共 22 个，以三种互不相干的形式定义：

- `tools/` 包内 `@tool` 函数装饰器：`read_file` `write_file` `list_directory`
  `search_files` `run_shell` `fetch_url` `web_search` `parse_json` `parse_csv`
  `analyze_text` `search_text`（11 个）
- `agent/graph.py` 内联工厂 `_make_subagent_tools` / `_make_scheduler_tools` /
  `_make_composition_tools` / `_make_channel_tools`：`create_subagent`
  `list_subagents` `schedule_task` `list_scheduled_tasks`
  `create_skill_composition` `list_skill_compositions`
  `execute_skill_composition` `notify_user_by_channel`（8 个）
- `memory/tools.py` `BaseTool` 子类：`search_memory` `read_memory` `remember`（3 个）

执行路径为 `model.bind_tools(self.tools)` + `agent/nodes.py:tool_node` 直接
`ainvoke`，**没有任何安全审查或结果验证环节**（`run_shell` 拿到任意命令直接
执行）；`security/` 模块只有 JWT 与限流，与工具无关。

目标：

1. 所有工具按五类划分：**感知、执行、用户沟通、协作、事件触发**。
2. 所有工具继承统一基类 `ThumbelinaBaseTool`（公共方法在基类定义），
   各分类中间基类定义自身契约方法。
3. 执行工具的「安全审查」「结果自验证」为强制抽象方法，关键工具
   （`run_shell`、`write_file`）给出真实防护实现，重构即产生安全价值。

硬约束：`ThumbelinaBaseTool` 必须继承 `langchain_core.tools.BaseTool`，
否则 `bind_tools` / `ainvoke` / `tool_node` 全部失效。

## 2. 分类划分（22 个工具）

分类判据：**工具作用的对象与副作用性质**。

| 分类 | 判据 | 工具 |
|---|---|---|
| 感知 (11) | 只读获取/加工信息，不改外部状态 | `read_file` `list_directory` `search_files` `fetch_url` `web_search` `parse_json` `parse_csv` `analyze_text` `search_text` `search_memory` `read_memory` |
| 执行 (6) | 对外部状态产生副作用 | `write_file` `run_shell` `remember` `create_skill_composition` `list_skill_compositions` `execute_skill_composition` |
| 用户沟通 (1) | 向人主动发消息 | `notify_user_by_channel` |
| 协作 (2) | 委托/查询其他 agent | `create_subagent` `list_subagents` |
| 事件触发 (2) | 注册/查询未来时间与条件 | `schedule_task` `list_scheduled_tasks` |

有争议归类的决策：

- **data_tools 四个解析/分析工具 → 感知**：纯函数式加工输入文本，无副作用。
- **技能组合三件套 → 执行**：`execute_skill_composition` 真实运行技能链、
  产生副作用，三件套整体归执行类，享受安全审查链路。
- **`remember` → 执行**：写记忆库，有副作用；其实现走抽取器同一写路径。

## 3. 目录结构

```
tools/
  base.py              # ToolCategory 枚举 + ThumbelinaBaseTool + 模板方法
  perception.py        # PerceptionTool + 11 个感知工具
  execution.py         # ExecutionTool + write_file / run_shell / remember
  execution_skill.py   # 技能编组三工具（依赖 CompositionEngine，单独文件）
  communication.py     # CommunicationTool + notify_user_by_channel
  collaboration.py     # CollaborationTool + subagent 工具
  event.py             # EventTriggerTool + scheduler 工具
  workspace_context.py # 不变
```

旧文件 `file_ops.py` `shell.py` `web_tools.py` `web_search_tools.py`
`data_tools.py` 与 `memory/tools.py` 中检索两类的实现迁入 `perception.py` /
`execution.py`。记忆三类的**类定义**迁入 tools 包（`SearchMemoryTool` /
`ReadMemoryTool` → `perception.py`，`RememberTool` → `execution.py`，均
import `memory.service` / `memory.extractor`，方向为 tools → memory，无循环）；
`memory/tools.py` 保留 `make_memory_tools` 组装出口，改为从 tools 包 import
这三个类。`agent/graph.py` 删除 4 个 `_make_*_tools` 工厂。

## 4. 基类契约与执行生命周期

### 4.1 ThumbelinaBaseTool

```python
class ToolCategory(StrEnum):
    PERCEPTION = "perception"
    EXECUTION = "execution"
    COMMUNICATION = "communication"
    COLLABORATION = "collaboration"
    EVENT_TRIGGER = "event_trigger"

class ThumbelinaBaseTool(BaseTool):
    category: ToolCategory  # 公共元数据，为将来 UI/API 暴露分类留口

    async def _arun(self, **kwargs):
        verdict = await self.security_review(kwargs)
        if isinstance(verdict, Reject):
            return f"Error: {self.name}: 安全审查拒绝: {verdict.reason}"
        try:
            result = await self._execute(**kwargs)
        except Exception as exc:
            return f"Error: {self.name}: {exc}"
        verify = await self.self_verify(kwargs, result)
        if isinstance(verify, Suspect):
            result += f"\n[warn] {verify.reason}"
        return result

    async def security_review(self, args) -> SecurityVerdict: ...   # 默认 Allow
    async def self_verify(self, args, result) -> VerifyResult: ...  # 默认 Ok
    async def _execute(self, **kwargs) -> str: ...  # 子类唯一必写方法
```

- `SecurityVerdict` 三态：`Allow` / `Reject(reason)` / `Confirm(reason)`。
  `Confirm` 本期实现为**放行 + 记日志**（当前 `tool_node` 无暂停/恢复机制，
  不引入人机交互回路；枚举保留三态为后续 HITL 留接口）。
- `VerifyResult` 两态：`Ok` / `Suspect(reason)`。`Suspect` 不推翻已发生的
  副作用，只在结果末尾追加 `[warn]` 提醒。
- 覆写 `_arun` 意味着 LangChain 回调/流式日志照常工作；`tool_node` 与
  `bind_tools` **零改动**。
- 同步 `_run` 统一返回「仅支持异步调用」提示串（与 memory 工具现状一致）。

### 4.2 错误约定（全分类共享）

工具失败一律返回 `str`（`"Error: ..."` 前缀），不向 `tool_node` 抛异常。
与现有内置工具风格保持一致，基类模板统一兜底。

### 4.3 五个分类基类的自身契约

- `PerceptionTool`：显式声明只读（默认 pass 审查）；公共截断助手
  `_truncate`（收拢现状散落在 5 个文件里的 1MB / 50KB 截断逻辑）。
- `ExecutionTool`：把 `security_review` / `self_verify` **重新声明为抽象**，
  具体工具必须实现（核心要求）。
- `CommunicationTool`：`resolve_target() -> tuple[str|None, str|None]`
  （解析收件人，含「最近用户」回退）、`format_receipt(delivered) -> str`
  （投递回执统一文案）。
- `CollaborationTool`：定义任务委托契约——`TaskTool` 抽象子类用强类型
  `task: str` 字段声明 args_schema（取代现在依赖 pydantic 私有
  `_turn_count` 风格的做法）；`report_status(agent) -> str` 统一状态行
  格式化（`list_subagents` 用）。
- `EventTriggerTool`：`parse_trigger(text) -> datetime|None`——`TimeParser`
  以类字段注入（`time_parser: Any = None`，装配函数传入），可测可替换。

## 5. 安全审查与结果自验证的真实实现

### 5.1 run_shell.security_review

命令文本先归一化（折叠空白、剥注释），再走两级规则：

- **硬拒绝（Reject）**：`rm -rf /`、`mkfs`、`dd of=/dev/`、fork 炸弹模式
  （`:(){:|:&};:`）、`shutdown` / `reboot`、`curl ... | sh` 管道执行、
  任何命中模块级 `DANGEROUS_PATTERNS: list[re.Pattern]` 的命令。
- **要求确认（Confirm→放行+日志）**：`git push --force`、`npm publish`、
  `docker rm -v`、写系统路径等。
- 工作区边界不变：cwd 仍是 ContextVar workspace，越界由现有逻辑兜底。

### 5.2 write_file.security_review

1. 复用 `_resolve_target` 的工作区边界检查作为第一道审查；
2. 额外拒绝写入 `PROTECTED_PATH_PATTERNS`：`thumbelina.db*`、`MEMORY/`
   （记忆库唯一写路径是抽取器，防 agent 绕过配额）、`prompts/roles/`、
   `.env*`、`plugins/`。

### 5.3 self_verify

- `run_shell`：exit code ≠ 0 且输出含 `error|denied|not found|Traceback`
  等标记 → `Suspect("命令退出码非零: {code}")`；超时由 `_execute` 的
  TimeoutError catch 返回 `Error:` 串，不进入 verify。
- `write_file`：写完回读 `stat().st_size` 与 `len(content.encode())` 比对，
  不一致 → `Suspect("写入字节数与内容不符")`。
- `remember`：decision ∈ {NEW, UPDATE, DELETE} 为 `Ok`；NOOP 返回普通说明，
  不报警。单轮配额计数器保留在 `RememberTool` 自身（`reset_turn_quota`），
  基类生命周期不感知。
- 技能组合：`execute_skill_composition` 结果为空串 → `Suspect`；
  `create_skill_composition` verify 检查 composition.id 非空；
  `list_skill_compositions` 为只读语义，`security_review` pass-through。

## 6. 装配变化

- `get_all_tools(search_config)`：聚合五类工具。内置感知/执行工具直接构造；
  依赖外部服务的工具（memory / composition / channel / scheduler /
  subagent）经各自 `make_*` 函数注入实例。
- `agent/graph.py` 删除 4 个 `_make_*_tools` 工厂，改调：
  `make_collaboration_tools(manager)` / `make_event_tools(scheduler, time_parser)` /
  `make_skill_tools(engine)` / `make_communication_tools(agent_ref)`。
  channels 仍是调用时查注册表（`CommunicationTool` 持 agent 引用，
  保持热注册语义）；`register_channel` 等公共方法留在 `ThumbelinaAgent`，
  仅工具实现移入 `communication.py`。
- 现有「按 name 去重 + `_remember_tool` 引用指向去重后实例」逻辑保留。

## 7. 测试策略（TDD，先测后写）

- `tests/test_tools_base.py`：模板方法顺序（review 拒绝则不执行、
  verify 追加 `[warn]`、异常转 `Error:` 串、`category` 必填）。
- `tests/test_execution_review.py`：run_shell 黑名单逐条命中、管道执行、
  fork 炸弹；write_file 工作区越界 + 保护路径；`self_verify` 非零退出、
  字节数不符。
- 每个分类基类一个 `tests/test_<category>_contract.py`：`TaskTool.task`
  强类型、TimeParser 可注入、`CommunicationTool` 回执文案等契约。
- 回归：`get_all_tools()` 名称集合与迁移前完全一致（防漏工具、防重名）；
  现有 memory 测试（`make_memory_tools` / `reset_turn_quota`）全绿；
  现有 agent 图测试不改动即通过（`_arun` 契约未变）。

## 8. 任务拆分（5 步，每步独立可验证、独立提交）

1. **基座**：`base.py` + 五个分类基类 + `test_tools_base.py`。纯新增，
   不改任何现有文件，先红后绿。
2. **感知迁移**：11 个感知工具改 `PerceptionTool` 子类；`memory/tools.py`
   检索两类迁入并保留 `make_memory_tools` 出口。全量测试。
3. **执行迁移（核心增量行为）**：`write_file` / `run_shell` 实现真实
   review/verify；`remember` 轻实现；技能组合三件套迁 `execution_skill.py`。
4. **沟通/协作/事件迁移**：三类工具改类；`graph.py` 删工厂改调新装配函数。
5. **收口**：重写 `get_all_tools` 聚合五类；全量测试 + 前端冒烟
   （工具调用卡片正常渲染）；README 工具清单补分类说明。

## 9. 范围外（明确不做）

- confirm 回路的人机交互（HITL）
- 工具分类在 Web UI / API 的暴露展示
- 插件 `PluginType.TOOL` 产出真实工具实例
- `security/` 模块与工具审查的整合（保持独立：工具审查是运行时，
  security 是 HTTP 层）
- `run_shell` 真沙箱化（容器/只读挂载/stdin 非交互清洗）——对抗性隔离属
  未来自建沙箱层，本期黑名单仅为行为塑形层（见 §11 第 7 条威胁模型定位）

## 10. 兼容性承诺

- 所有工具 `name` 与对外参数 schema 不变 → LLM 侧行为零感知。
- `tool_node` / `bind_tools` / `ainvoke` 调用路径不变。
- 失败仍返回 `Error:` 前缀字符串，成功仍返回 `str`。
- `workspace_context` ContextVar 机制不变。

## 11. 实现期勘误（SDD 执行期裁定，2026-08-29，feat/tools-taxonomy）

1. **§3/§6 修订：记忆三类物理留在 `memory/tools.py`**，不迁入 `tools/` 包。仅换基类
   （`SearchMemoryTool`/`ReadMemoryTool`→`PerceptionTool`，`RememberTool`→`ExecutionTool`）
   与生命周期写法；`make_memory_tools` 出口、`graph.py` 的 `RememberTool` import 均不变。
   import 方向 memory→tools，无循环；分类语义不受影响。
2. **§4.3 修订：未建 `TaskTool` 类**。协作工具用显式 `args_schema` 内联模型声明强类型
   `task: str` 字段，契约语义等价（LLM 可见 schema 相同）；`report_status` 作为
   `ListSubagentsTool` 静态方法。
3. **§5.3 修订：`create_skill_composition` 的 verify 不检查 composition.id**——失败路径
   已由 `_execute` 返回 `Failed to create composition:` 串，重复报警无增益，返回 `Ok()`。
4. **§5.3 精确化：`write_file` 以 `newline=""` 写字节精确**（Windows 不再 `\n`→`\r\n`
   转译），使「N bytes」文案与自验证字节比对同时为真；`self_verify` 取输出中**最后**
   一个 `[exit code: N]` 标记（防程序伪造先前标记）。
5. **§5.1 增强（终审）**：`rm` 黑名单覆盖 `-rf/-fr/-r -f/--recursive --force` 各种
   合写/拆写顺序、目标为 `/` 开头任意路径（含 `/*`）；目录类保护守卫锚定工作区根
   分段（`src/memory/` 不误伤），文件名类（`thumbelina.db*`/`.env*`）任意层级。
   已知残留：`rm -rf --no-preserve-root /` 长短选项混写形式可绕过（后续项）。
6. **§2 判据修正（独立审核）：** 原判据「作用对象 + 副作用性质」二维未定优先级，
   落地时对 `list_scheduled_tasks` 用了「对象优先」、对 `remember` 用了「性质优先」，
   自相矛盾。修正为：主判据 = **副作用性质优先**（写外部状态即执行类）；例外原则 =
   纯查询型工具（`list_*`/`search_*`/`read_*`）随其资源域归组（如
   `list_scheduled_tasks` 归事件触发）；两判据仍多命中时，显式裁决序为
   **副作用性质 > 资源域 > 作用对象**。
7. **§5.1 威胁模型定位声明（独立审核）：** 正则黑名单是**行为塑形层（防误操作）+
   纵深防御最外层，不是对抗性边界**。嵌套解释器（`bash -c`/`python -c`/
   `os.system`）、变量展开（`$HOME`）、路径改写、shell 续行等构造上可绕过，
   本节规则只求覆盖 LLM 高频输出中的直接危险形态。对抗性隔离由未来自建沙箱层
   承担（见 §9）。
8. **§4.2 异常留痕补充（独立审核）：** 「失败返回 `str`」约定下，基类模板的每个
   try 分支在返回 `Error:` 串之前**同时 `logger.exception` 落栈**，保留第一现场
   （栈信息只进日志，不进 ToolMessage/LLM 上下文）。且 try 范围覆盖
   security_review / _execute / self_verify 三段（review 故障 fail-closed 转
   Error，verify 故障降级为 `[warn] 结果自验证异常` 保留已发生输出），
   修正原 docstring 与实现不符处。
9. **安全规则已知缺口补记（独立审核，均 best-effort 不阻塞）：**
   ① `--no-preserve-root` 长短选项混写绕过（见第 5 条）；
   ② shell 续行：本轮已修「反斜杠+换行」折叠（`_normalize_command` 先折
   `\\\r?\n` 再剥注释/折空白），其余续行构造（如变量分片）仍可绕过；
   ③ 嵌套解释器（`bash -c "..."` 内部命令不受黑名单约束）；
   ④ `rm ~`/`rm $HOME` 等家目录目标（无绝对路径前缀可锚）；
   ⑤ 命令位误判：`grep -r shutdown src/` 会被 `\bshutdown\b` 误杀——引入命令
   位置解析属过度设计，明确接受该误杀为已知局限。
   可用性修正：`> /dev/null`、`2>/dev/null`、`dd of=/dev/null` 不再误杀
   （负向前瞻排除 null）；Reject/Confirm reason 改为人类可读短名，不再泄露
   正则源码（防污染 LLM 上下文与向模型披露规则）。
10. **延迟副作用不受门控（设计缺口，后续项，不阻塞本 PR）：** `schedule_task`
    注册的是「未来无人监督的完整 agent run」、`create_subagent` 无 spawn
    深度/配额限制，二者当前默认 `Allow()`——执行时刻不在审查链路内、协作扇出
    无上限。后续项：事件/协作类工具的轻量审查（延迟副作用声明式检查）+
    spawn 深度/配额限制，连同 §9 的 run_shell 真沙箱化一并规划。
