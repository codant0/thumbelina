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

## 10. 兼容性承诺

- 所有工具 `name` 与对外参数 schema 不变 → LLM 侧行为零感知。
- `tool_node` / `bind_tools` / `ainvoke` 调用路径不变。
- 失败仍返回 `Error:` 前缀字符串，成功仍返回 `str`。
- `workspace_context` ContextVar 机制不变。
