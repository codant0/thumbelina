# 聊天流内实时工具调用卡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对话进行中，聊天流内实时显示工具调用卡（运行中 → 完成/失败，含耗时与可展开的参数/结果预览）。

**Architecture:** 工具节点通过 LangGraph custom stream writer（`get_stream_writer()`）发射 tool_start/tool_end 事件，`ThumbelinaAgent.stream()` 以 `stream_mode=["messages","custom"]` 把它们与 token 流在同一生成器内交错产出；WS 层转发为 `tool_event` 帧并把非流式分支统一到 `stream()`；前端复用现有 `Message.toolCalls`/`ToolCallItem` 骨架实时渲染。

**Tech Stack:** Python 3.11 / FastAPI / LangGraph 1.2.7 / pytest（`asyncio_mode="auto"`）；React 19 / TypeScript / vitest。

**Spec:** `docs/specs/2026-09-05-tool-visibility-design.md`（执行者必须同时阅读本计划与 spec）

## Global Constraints

- **禁止新增依赖**：后端仅用 langgraph 现有 API（`from langgraph.config import get_stream_writer`，已验证 1.2.7 可导入）；前端零新包。
- **契约冻结（前后端并行开发的唯一接口，不得更改字段名）**：
  - `stream()` 产出事件（dict）：
    - `{"type": "tool_start", "call_id": str, "name": str, "args": dict|{"_truncated_json": str}, "args_truncated": bool}`
    - `{"type": "tool_end", "call_id": str, "duration_ms": int, "is_error": bool, "result_preview": str, "result_truncated": bool}`
    - 现有 `{"type": "content"|"reasoning", "text": str}` 形状不变。
  - WS 下行帧：`{"tool_event": {"phase": "start"|"end", "call_id", "name"?, "args"?, "args_truncated"?, "duration_ms"?, "is_error"?, "result_preview"?, "result_truncated"?}, "conversation_id": cid}`（`phase` 由 WS 层从 `type` 映射，其余字段原样透传）。
  - 前端 `ToolCall`：`{ call_id?, name, args, result?, status: 'running'|'ok'|'error'|'interrupted', durationMs?, resultTruncated?, argsTruncated? }`。
- **工具错误文案格式不变**：`Error: Unknown tool '{name}'` 与 `Error executing tool '{name}': {exc}` 原样保留（下游兼容）。
- 错误状态判定改由 `tool_node` 控制流给出；`content.startswith("Error")` 反推退役（review P0-13）。
- 前端样式只用主题令牌，动画仅 transform/opacity；历史加载（loadHistory）不填充 toolCalls。
- **并发执行约束：两个执行代理都不得执行 `git commit`/`git add`**——由主会话在集成验证后统一提交（避免并行 index.lock 竞争）。各任务只允许改动本任务 Files 列出的文件。
- 命令均在仓库根 `F:\projects\thumbelina` 用 Git Bash 执行；后端测试用 `.venv/Scripts/python.exe -m pytest`，前端测试用 `cd frontend && npx vitest run <file>`。
- 提交信息风格沿用 `feat(agent): ...` / `feat(api): ...` / `feat(web): ...`（主会话使用）。

---

## 后端任务（执行代理 A，按序执行 Task 1-4）

### Task 1: `tool_node` 增加 `on_tool_event` 回调

**Files:**
- Modify: `src/thumbelina/agent/nodes.py`
- Test: `tests/test_agent/test_nodes.py`

**Interfaces:**
- Consumes: 现有 `tool_node(state, tools) -> {"messages": [ToolMessage, ...]}`（返回值结构不变）。
- Produces: `ToolEventCallback = Callable[[dict], Awaitable[None]]`（模块级类型别名）；回调 payload：`{"call_id": str, "is_error": bool, "duration_ms": int, "content": str}`；新签名 `tool_node(state, tools, on_tool_event=None)`。Task 2 依赖此签名与 payload。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_agent/test_nodes.py`，模块已 `from langchain_core.messages import AIMessage, HumanMessage`，文件头部需补 `from langchain_core.tools import tool`；该测试文件遵循 `asyncio_mode="auto"`，直接写 `async def test_...` 即可，无需 marker）

```python
from langchain_core.tools import tool


@tool
def _ok_tool(dummy: str = "") -> str:
    """always returns ok"""
    return "ok result"


@tool
def _boom_tool(dummy: str = "") -> str:
    """always raises"""
    raise RuntimeError("boom")


def _state_with(tool_call: dict):
    return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}


class TestToolNodeEventCallback:
    async def test_success_event_payload(self):
        from thumbelina.agent.nodes import tool_node

        events = []

        async def cb(info):
            events.append(info)

        await tool_node(
            _state_with({"name": "_ok_tool", "args": {}, "id": "c1"}),
            [_ok_tool],
            on_tool_event=cb,
        )
        assert len(events) == 1
        assert events[0]["call_id"] == "c1"
        assert events[0]["is_error"] is False
        assert events[0]["content"] == "ok result"
        assert isinstance(events[0]["duration_ms"], int) and events[0]["duration_ms"] >= 0

    async def test_exception_event_is_error(self):
        from thumbelina.agent.nodes import tool_node

        events = []

        async def cb(info):
            events.append(info)

        result = await tool_node(
            _state_with({"name": "_boom_tool", "args": {}, "id": "c2"}),
            [_boom_tool],
            on_tool_event=cb,
        )
        assert events[0]["is_error"] is True
        assert "boom" in events[0]["content"]
        assert result["messages"][0].content.startswith("Error executing tool")

    async def test_unknown_tool_event_is_error(self):
        from thumbelina.agent.nodes import tool_node

        events = []

        async def cb(info):
            events.append(info)

        await tool_node(
            _state_with({"name": "nope", "args": {}, "id": "c3"}),
            [_ok_tool],
            on_tool_event=cb,
        )
        assert events[0]["is_error"] is True
        assert events[0]["content"] == "Error: Unknown tool 'nope'"

    async def test_callback_exception_does_not_break_execution(self):
        from thumbelina.agent.nodes import tool_node

        async def cb(info):
            raise ValueError("callback exploded")

        result = await tool_node(
            _state_with({"name": "_ok_tool", "args": {}, "id": "c4"}),
            [_ok_tool],
            on_tool_event=cb,
        )
        assert result["messages"][0].content == "ok result"

    async def test_no_callback_default_unchanged(self):
        from thumbelina.agent.nodes import tool_node

        result = await tool_node(
            _state_with({"name": "_ok_tool", "args": {}, "id": "c5"}), [_ok_tool]
        )
        assert result["messages"][0].content == "ok result"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent/test_nodes.py::TestToolNodeEventCallback -q`
Expected: FAIL（`tool_node` 不接受 `on_tool_event` 参数 / TypeError）

- [ ] **Step 3: 最小实现**（`nodes.py`：头部补 `import logging`、`import time`、`from typing import Awaitable, Callable`，模块级加 `logger = logging.getLogger(__name__)`；`tool_node` 及 `_invoke_one` 改为如下形状，docstring 相应补充回调说明，其余逻辑不动）

```python
ToolEventCallback = Callable[[dict], Awaitable[None]]


async def tool_node(
    state: AgentState,
    tools: list[BaseTool],
    on_tool_event: ToolEventCallback | None = None,
) -> dict[str, list[ToolMessage]]:
```

```python
    async def _invoke_one(tool_call: dict) -> ToolMessage:
        tool_name = tool_call["name"]
        tool_call_id = tool_call["id"]
        started = time.monotonic()

        async def _notify(is_error: bool, content: str) -> None:
            if on_tool_event is None:
                return
            try:
                await on_tool_event(
                    {
                        "call_id": tool_call_id,
                        "is_error": is_error,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "content": content,
                    }
                )
            except Exception:
                logger.debug("tool_node on_tool_event callback failed", exc_info=True)

        if tool_name not in tool_map:
            content = f"Error: Unknown tool '{tool_name}'"
            await _notify(True, content)
            return ToolMessage(content=content, tool_call_id=tool_call_id)

        try:
            result = await tool_map[tool_name].ainvoke(tool_call["args"])
        except Exception as exc:
            content = f"Error executing tool '{tool_name}': {exc}"
            await _notify(True, content)
            return ToolMessage(content=content, tool_call_id=tool_call_id)
        content = str(result)
        await _notify(False, content)
        return ToolMessage(content=content, tool_call_id=tool_call_id)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent/test_nodes.py -q`
Expected: PASS（新旧用例全绿）

### Task 2: `_tool_node_node` 发射事件 + trajectory 真实状态与耗时

**Files:**
- Modify: `src/thumbelina/agent/graph.py`（`_tool_node_node` 约 :751-784；模块头部与工具函数）
- Modify: `src/thumbelina/agent/trajectory.py`（`record_tool_result` 约 :99-102）
- Test: `tests/test_trajectory/`（现有 recorder 测试文件内追加）

**Interfaces:**
- Consumes: Task 1 的 `tool_node(state, tools, on_tool_event)` 与回调 payload。
- Produces: （a）writer 自定义事件 payload：`{"tool_start": {call_id, name, args, args_truncated}}` / `{"tool_end": {call_id, duration_ms, is_error, result_preview, result_truncated}}`（Task 3 消费）；（b）`TrajectoryRecorder.record_tool_result(call_id, content, is_error=False, duration_ms=None)`（新增可选参数）；（c）`graph.py` 模块级 `_truncate_text(text: str, limit: int) -> tuple[str, bool]` 与常量 `TOOL_RESULT_PREVIEW_LIMIT=2048`、`TOOL_ARGS_PREVIEW_LIMIT=8192`。

- [ ] **Step 1: 写失败测试**（在 `tests/test_trajectory/` 现有 recorder 测试文件中追加，先查看该文件如何构造 `TrajectoryRecorder` 与假存储，复用其既有 fixture/写法）

```python
async def test_record_tool_result_duration_ms_optional():
    recorder = _make_recorder()  # 按该文件现有方式构造
    await recorder.record_tool_result("c1", "fine", is_error=False, duration_ms=1234)
    payload = _last_event_payload(recorder, "tool_result")  # 按该文件现有断言方式取 payload
    assert payload["duration_ms"] == 1234
    assert payload["is_error"] is False

async def test_record_tool_result_omits_duration_when_none():
    recorder = _make_recorder()
    await recorder.record_tool_result("c2", "bad", is_error=True)
    payload = _last_event_payload(recorder, "tool_result")
    assert "duration_ms" not in payload
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_trajectory -q`
Expected: FAIL（`record_tool_result` 不接受 `duration_ms`）

- [ ] **Step 3: 实现 trajectory.py**（`record_tool_result` 增加可选参数 `duration_ms: int | None = None`，payload 仅在非 None 时含 `duration_ms` 键）

- [ ] **Step 4: 实现 graph.py 的 `_tool_node_node`**（模块头部补 `import json` 与 `from langgraph.config import get_stream_writer`；模块级加：

```python
TOOL_RESULT_PREVIEW_LIMIT = 2048
TOOL_ARGS_PREVIEW_LIMIT = 8192


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True
```

`_tool_node_node` 改为（trajectory 记录调用保留在原位置）：

```python
    async def _tool_node_node(self, state: AgentState) -> dict[str, list[Any]]:
        """Node wrapper for executing tools."""
        calls: list[dict] = []
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage):
            calls = list(last_message.tool_calls or [])
        for tool_call in calls:
            await self.trajectory_recorder.record_tool_call(
                tool_call.get("name", ""), tool_call.get("args", {}), tool_call.get("id", "")
            )
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

        statuses: dict[str, dict[str, Any]] = {}

        async def on_tool_event(info: dict) -> None:
            call_id = info.get("call_id", "")
            statuses[call_id] = {
                "is_error": bool(info.get("is_error")),
                "duration_ms": int(info.get("duration_ms", 0)),
            }
            if writer is None:
                return
            preview, truncated = _truncate_text(
                str(info.get("content", "")), TOOL_RESULT_PREVIEW_LIMIT
            )
            writer(
                {
                    "tool_end": {
                        "call_id": call_id,
                        "duration_ms": statuses[call_id]["duration_ms"],
                        "is_error": statuses[call_id]["is_error"],
                        "result_preview": preview,
                        "result_truncated": truncated,
                    }
                }
            )

        for tool_call in calls:
            if writer is None:
                continue
            args = tool_call.get("args", {}) or {}
            args_json = json.dumps(args, ensure_ascii=False, default=str)
            if len(args_json.encode("utf-8")) > TOOL_ARGS_PREVIEW_LIMIT:
                args_preview, _ = _truncate_text(args_json, TOOL_ARGS_PREVIEW_LIMIT)
                writer(
                    {
                        "tool_start": {
                            "call_id": tool_call.get("id", ""),
                            "name": tool_call.get("name", ""),
                            "args": {"_truncated_json": args_preview},
                            "args_truncated": True,
                        }
                    }
                )
            else:
                writer(
                    {
                        "tool_start": {
                            "call_id": tool_call.get("id", ""),
                            "name": tool_call.get("name", ""),
                            "args": args,
                            "args_truncated": False,
                        }
                    }
                )
        result = await tool_node(state, self.tools, on_tool_event=on_tool_event)
        tool_messages = result.get("messages", [])
        if len(calls) != len(tool_messages):
            logger.error(
                "Tool call/result count mismatch in trajectory recording: "
                "%d call(s) but %d tool message(s); pairing by zip truncation",
                len(calls),
                len(tool_messages),
            )
        for tool_call, tool_message in zip(calls, tool_messages):
            content = str(getattr(tool_message, "content", ""))
            status = statuses.get(tool_call.get("id", ""))
            if status is None:
                logger.warning(
                    "Trajectory: no live status recorded for tool call %r",
                    tool_call.get("id", ""),
                )
            await self.trajectory_recorder.record_tool_result(
                tool_call.get("id", ""),
                content,
                is_error=bool(status["is_error"]) if status else False,
                duration_ms=status["duration_ms"] if status else None,
            )
        if len(calls) > len(tool_messages):
            for orphan in calls[len(tool_messages) :]:
                logger.warning(
                    "Trajectory: tool call %r has no ToolMessage counterpart; "
                    "skipping result record",
                    orphan.get("id", ""),
                )
        return result
```

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_trajectory tests/test_agent -q`
Expected: PASS

### Task 3: `stream()` 双模式（messages + custom）

**Files:**
- Modify: `src/thumbelina/agent/graph.py`（`stream()` :1215-1357，及返回类型注解）
- Test: `tests/test_agent/test_graph.py`（复用 `_create_mock_provider` 与 `ThumbelinaAgent(llm_provider=...)` 既有模式）

**Interfaces:**
- Consumes: Task 2 的 writer 事件 payload。
- Produces: `stream()` 完整事件集（Global Constraints 契约冻结段）；返回类型注解改为 `AsyncGenerator[dict[str, Any], None]`。Task 4 消费。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_agent/test_graph.py`。要点：用真实 `@tool` 装饰器工具（放在模块级，勿用 MagicMock，`ainvoke` 才能走通成功路径）；mock provider 的 `ainvoke` 用 `side_effect` 先返回带 `tool_calls` 的 AIMessage 再返回最终回复）

```python
from langchain_core.tools import tool


@tool
def _graph_echo_tool(text: str = "") -> str:
    """echoes its input"""
    return f"echo:{text}"


class TestStreamToolEvents:
    async def test_stream_emits_tool_start_and_end(self):
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke = AsyncMock(
            side_effect=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "_graph_echo_tool", "args": {"text": "hi"}, "id": "call_1"}],
                ),
                AIMessage(content="final answer"),
            ]
        )
        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[_graph_echo_tool])
        events = [e async for e in agent.stream("use the tool")]

        types = [e["type"] for e in events]
        assert "tool_start" in types and "tool_end" in types
        start = next(e for e in events if e["type"] == "tool_start")
        end = next(e for e in events if e["type"] == "tool_end")
        assert start["call_id"] == "call_1"
        assert start["name"] == "_graph_echo_tool"
        assert start["args"] == {"text": "hi"}
        assert start["args_truncated"] is False
        assert end["call_id"] == "call_1"
        assert end["is_error"] is False
        assert end["result_preview"] == "echo:hi"
        assert end["result_truncated"] is False
        assert isinstance(end["duration_ms"], int)
        # 内容事件不受影响
        assert "".join(e["text"] for e in events if e["type"] == "content") == "final answer"

    async def test_stream_pure_text_round_has_no_tool_events(self):
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="plain")
        agent = ThumbelinaAgent(llm_provider=mock_provider)
        events = [e async for e in agent.stream("hi")]
        assert all(e["type"] in ("content", "reasoning") for e in events)

    async def test_run_path_unchanged_no_events(self):
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke = AsyncMock(
            side_effect=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "_graph_echo_tool", "args": {"text": "x"}, "id": "call_2"}],
                ),
                AIMessage(content="done"),
            ]
        )
        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[_graph_echo_tool])
        assert await agent.run("use the tool") == "done"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent/test_graph.py::TestStreamToolEvents -q`
Expected: FAIL（stream 未产出 tool_start/tool_end）

- [ ] **Step 3: 实现**（`stream()` 内：`astream_iter = self.graph.astream(initial_state, stream_mode=["messages", "custom"], config=config)`；主循环改为先按 mode 分流，`messages` 分支保留全部现有逻辑（compress 过滤、AIMessage/tool_calls 过滤、批量缓冲）：

```python
        async for stream_mode, event in astream_iter:
            if stream_mode == "custom":
                if isinstance(event, dict) and "tool_start" in event:
                    yield {"type": "tool_start", **event["tool_start"]}
                elif isinstance(event, dict) and "tool_end" in event:
                    yield {"type": "tool_end", **event["tool_end"]}
                continue
            message_chunk = event[0]
            metadata = event[1] if len(event) > 1 and isinstance(event[1], dict) else {}
            # ……以下为现有 messages 分支逻辑，原样保留……
```

同时更新 `stream()` docstring（4 类事件）与返回注解。**注意**：原 `if not isinstance(event, tuple)` 守卫可移除（双模式事件恒为元组）。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent -q`
Expected: PASS

### Task 4: WS 层转发 + 非流式分支统一

**Files:**
- Modify: `src/thumbelina/api/websocket.py`（`_run_generation` :146-295）
- Test: `tests/test_api/test_websocket.py`（先读该文件现有 fake agent/连接模式，复用其 fixture 写法）

**Interfaces:**
- Consumes: Task 3 的 `stream()` 事件集。
- Produces: WS 下行帧（Global Constraints 契约冻结段）；模块级辅助函数 `_tool_event_frame(event: dict) -> dict`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_api/test_websocket.py`，断言帧序列：tool_event 帧形如 `{"tool_event": {"phase": "start", "call_id": ..., ...}, "conversation_id": ...}`；流式分支 tool_event 帧出现在 content chunk 之前、done 之前；非流式分支（`llm.streaming_enabled=False`）产出 tool_event 帧 + 单个 `{"response": ...}` 帧 + done 帧 `streaming_mode: False`。按该文件现有方式构造带 fake `agent.stream` 的 app/websocket）

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api/test_websocket.py -q`
Expected: FAIL（新用例）；旧用例全绿

- [ ] **Step 3: 实现**（`websocket.py` 模块级加辅助函数；`_run_generation` 流式分支在 `event["type"]` 判断中加入 tool 分支；非流式分支整体替换为消费 `stream()`）：

```python
def _tool_event_frame(event: dict) -> dict:
    """把 agent.stream 的 tool_start/tool_end 事件映射为 WS 下行帧。"""
    payload = {k: v for k, v in event.items() if k != "type"}
    payload["phase"] = "start" if event["type"] == "tool_start" else "end"
    return {"tool_event": payload}
```

流式分支（`if streaming:` 内，`async for` 循环体**整体替换**为如下——注意现有循环体第一行 `text = event["text"]` 必须移入 content 分支，否则工具事件会 KeyError）：

```python
                etype = event["type"]
                if etype in ("tool_start", "tool_end"):
                    frame = _tool_event_frame(event)
                    frame["conversation_id"] = cid
                    await websocket.send_json(frame)
                elif etype == "reasoning":
                    await websocket.send_json(
                        {
                            "chunk": event["text"],
                            "chunk_type": "reasoning",
                            "conversation_id": cid,
                        }
                    )
                else:
                    full_response += event["text"]
                    await websocket.send_json({"chunk": event["text"], "conversation_id": cid})
```

非流式分支（`else:` 整体替换；reasoning 事件不下发但 stream() 会照常持久化）：

```python
        else:
            full_response = ""
            async for event in agent.stream(
                message, context_window_tokens=window_tokens, attachments=attachments
            ):
                etype = event["type"]
                if etype in ("tool_start", "tool_end"):
                    frame = _tool_event_frame(event)
                    frame["conversation_id"] = cid
                    await websocket.send_json(frame)
                elif etype == "content":
                    full_response += event["text"]
            await websocket.send_json({"response": full_response, "conversation_id": cid})
```

同时更新 `_run_generation` docstring（工具事件帧 + 非流式统一走 stream）。**不要**改动 `agent.run()` 本身及其它调用方。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api -q`
Expected: PASS

---

## 前端任务（执行代理 B，按序执行 Task 5-6）

### Task 5: 类型 + 纯函数 + useWebSocket 消费

**Files:**
- Modify: `frontend/src/types/chat.ts`（`ToolCall` :1-5、新增 `ToolEventPayload`）
- Create: `frontend/src/components/Chat/toolCallEvents.ts`（纯函数，独立可测）
- Modify: `frontend/src/hooks/useWebSocket.ts`（`WsIncoming` :4-32 + onmessage 处理 + done/stopped/error 收尾）
- Test: `frontend/src/components/Chat/toolCallEvents.test.ts`；`frontend/src/hooks/useWebSocket.test.tsx`（或该仓现有的 useWebSocket 测试文件——两个变体都存在时选实际被 vitest 收集的那个，先看现有用例怎么写）

**Interfaces:**
- Consumes: WS 契约（Global Constraints 冻结段 `tool_event` 帧）。
- Produces: `ToolCall` 扩展类型；`upsertToolCall(toolCalls: ToolCall[], ev: ToolEventPayload): ToolCall[]`；`markInterrupted(toolCalls: ToolCall[]): ToolCall[]`（Task 6 的组件消费 `ToolCall.status/durationMs/resultTruncated/argsTruncated`）。

- [ ] **Step 1: 类型**（`types/chat.ts`）

```typescript
export interface ToolCall {
  call_id?: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: 'running' | 'ok' | 'error' | 'interrupted';
  durationMs?: number;
  resultTruncated?: boolean;
  argsTruncated?: boolean;
}

export interface ToolEventPayload {
  phase: 'start' | 'end';
  call_id: string;
  name?: string;
  args?: Record<string, unknown>;
  args_truncated?: boolean;
  duration_ms?: number;
  is_error?: boolean;
  result_preview?: string;
  result_truncated?: boolean;
}
```

- [ ] **Step 2: 纯函数 + 失败测试**（`toolCallEvents.test.ts`）

```typescript
import { describe, expect, it } from 'vitest';
import { markInterrupted, upsertToolCall } from './toolCallEvents';
import type { ToolEventPayload } from '../../types/chat';

const start = (call_id: string, name = 'web_search'): ToolEventPayload => ({
  phase: 'start', call_id, name, args: { query: 'q' },
});
const end = (call_id: string, is_error = false): ToolEventPayload => ({
  phase: 'end', call_id, duration_ms: 1800, is_error,
  result_preview: 'preview...', result_truncated: true,
});

describe('upsertToolCall', () => {
  it('start 创建 running 卡', () => {
    const list = upsertToolCall([], start('c1'));
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ call_id: 'c1', name: 'web_search', status: 'running' });
  });
  it('end 把 running 卡改为 ok 并带结果与耗时', () => {
    let list = upsertToolCall([], start('c1'));
    list = upsertToolCall(list, end('c1'));
    expect(list[0]).toMatchObject({ status: 'ok', durationMs: 1800, resultTruncated: true });
  });
  it('end is_error 时状态为 error', () => {
    let list = upsertToolCall([], start('c1'));
    list = upsertToolCall(list, end('c1', true));
    expect(list[0].status).toBe('error');
  });
  it('重复 start 忽略；孤立 end 防御性建卡', () => {
    let list = upsertToolCall([], start('c1'));
    list = upsertToolCall(list, start('c1'));
    expect(list).toHaveLength(1);
    list = upsertToolCall(list, end('c9'));
    expect(list).toHaveLength(2);
    expect(list[1].status).toBe('ok');
  });
  it('多工具并发各自成卡', () => {
    let list = upsertToolCall([], start('a', 't1'));
    list = upsertToolCall(list, start('b', 't2'));
    list = upsertToolCall(list, end('a'));
    expect(list.map((tc) => tc.status)).toEqual(['ok', 'running']);
  });
});

describe('markInterrupted', () => {
  it('把 running 卡标为 interrupted，其余不动', () => {
    let list = upsertToolCall([], start('c1'));
    list = upsertToolCall(list, end('c1'));
    list = upsertToolCall(list, start('c2'));
    const marked = markInterrupted(list);
    expect(marked.map((tc) => tc.status)).toEqual(['ok', 'interrupted']);
  });
  it('无 running 时返回原数组', () => {
    const list = upsertToolCall(upsertToolCall([], start('c1')), end('c1'));
    expect(markInterrupted(list)).toBe(list);
  });
});
```

Run: `cd frontend && npx vitest run src/components/Chat/toolCallEvents.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现纯函数**（`toolCallEvents.ts`）

```typescript
import type { ToolCall, ToolEventPayload } from '../../types/chat';

export function upsertToolCall(toolCalls: ToolCall[], ev: ToolEventPayload): ToolCall[] {
  const idx = toolCalls.findIndex((tc) => tc.call_id === ev.call_id);
  if (ev.phase === 'start') {
    if (idx >= 0) return toolCalls;
    return [
      ...toolCalls,
      {
        call_id: ev.call_id,
        name: ev.name ?? 'unknown',
        args: ev.args ?? {},
        argsTruncated: ev.args_truncated ?? false,
        status: 'running' as const,
      },
    ];
  }
  const status = ev.is_error ? ('error' as const) : ('ok' as const);
  if (idx < 0) {
    return [
      ...toolCalls,
      {
        call_id: ev.call_id,
        name: 'unknown',
        args: {},
        status,
        result: ev.result_preview,
        resultTruncated: ev.result_truncated,
        durationMs: ev.duration_ms,
      },
    ];
  }
  const next = [...toolCalls];
  next[idx] = {
    ...next[idx],
    status,
    result: ev.result_preview,
    resultTruncated: ev.result_truncated,
    durationMs: ev.duration_ms,
  };
  return next;
}

export function markInterrupted(toolCalls: ToolCall[]): ToolCall[] {
  if (!toolCalls.some((tc) => tc.status === 'running')) return toolCalls;
  return toolCalls.map((tc) =>
    tc.status === 'running' ? { ...tc, status: 'interrupted' as const } : tc
  );
}
```

Run: `cd frontend && npx vitest run src/components/Chat/toolCallEvents.test.ts` → PASS

- [ ] **Step 4: 接入 useWebSocket**。要点（接线方式以该文件现有的 chunk 路由/按会话分桶结构为准，工具事件必须走同一条会话维度路径）：
  1. `WsIncoming` 增加可选字段 `tool_event?: ToolEventPayload;`（import 自 `../types/chat`）。
  2. onmessage 中收到 `tool_event` 时：定位当前会话的流式 assistant 消息（与 chunk 落点同一条）；若无则按 chunk 首次到达的方式创建占位 assistant 消息；对其实施 `upsertToolCall`。占位创建逻辑若已抽取为函数则复用，避免复制。
  3. done / stopped / error 三个收尾分支：对当轮 in-flight assistant 消息执行 `markInterrupted`。
  4. `loadHistory` 不填充 `toolCalls`（维持现状）。
  5. 在 useWebSocket 现有测试文件中补集成用例：mock WS 收到 start→end 帧，断言消息 `toolCalls` 变化；收到 stopped 后 running 卡变 interrupted（断言方式仿照现有 chunk 用例）。
- [ ] **Step 5: 运行**：`cd frontend && npx vitest run src/hooks/useWebSocket src/components/Chat/toolCallEvents.test.ts` → PASS（全部新旧用例）

### Task 6: ToolCallItem 实时卡 + i18n + 样式

**Files:**
- Modify: `frontend/src/components/Chat/MessageList.tsx`（`ToolCallItem` :74-107）
- Modify: `frontend/src/i18n/locales/zh-CN.json`、`en.json`（`toolCalls.*` 命名空间，约 :601 附近）
- Modify: 工具卡样式所在 css（先在 `frontend/src/styles/` 与 `App.css` 中 grep 现有 ToolCallItem 类名，就地扩展）
- Test: `frontend/src/components/Chat/MessageList.test.tsx`（扩展现有 toolCalls 用例，:363 附近）

**Interfaces:**
- Consumes: Task 5 的 `ToolCall`（status/durationMs/resultTruncated/argsTruncated）。
- Produces: 四态实时卡 UI。

- [ ] **Step 1: i18n 键**（中英各 4 键，命名空间 `toolCalls`）：

```
zh-CN: running="调用中…"  interrupted="已中断"  durationMs="{{ms}} ms"  truncatedHint="完整内容见轨迹页"
en:    running="Running…" interrupted="Interrupted" durationMs="{{ms}} ms" truncatedHint="Full content in Trajectory page"
```

- [ ] **Step 2: 失败测试**（`MessageList.test.tsx` 追加四态用例：running 显示 `toolCalls.running` 文案且无结果区；ok 显示耗时与结果预览；error 卡带错误样式类（断言 className 含 error 变体）；interrupted 显示 `toolCalls.interrupted`。沿用该文件现有的渲染辅助函数与 i18n 测试装配方式）

- [ ] **Step 3: 运行确认失败**：`cd frontend && npx vitest run src/components/Chat/MessageList.test.tsx` → 新用例 FAIL

- [ ] **Step 4: 实现**（`ToolCallItem` 以 status 驱动，保持点击展开参数/结果的现有交互与折叠样式）：

```tsx
function ToolCallItem({ toolCall }: { toolCall: ToolCall }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={`tool-call-item status-${toolCall.status}`}>
      <button type="button" className="tool-call-header" onClick={() => setExpanded((v) => !v)}>
        <Wrench size={14} />
        <span className="tool-call-name">{toolCall.name}</span>
        {toolCall.status === 'running' && <span className="tool-call-spinner" aria-hidden />}
        {toolCall.status === 'running' && (
          <span className="tool-call-status">{t('toolCalls.running')}</span>
        )}
        {toolCall.status === 'ok' && (
          <span className="tool-call-status tool-call-ok">
            ✓ {t('toolCalls.durationMs', { ms: toolCall.durationMs ?? 0 })}
          </span>
        )}
        {toolCall.status === 'interrupted' && (
          <span className="tool-call-status">{t('toolCalls.interrupted')}</span>
        )}
        {toolCall.status === 'error' && <span className="tool-call-status tool-call-err" />}
      </button>
      {expanded && (
        <div className="tool-call-body">
          {/** 参数/结果渲染沿用现有展开结构；resultTruncated 时尾部追加 t('toolCalls.truncatedHint') */}
        </div>
      )}
    </div>
  );
}
```

（`tool-call-body` 内部结构、现有类名与 props 以文件现状为准做最小改造，不改其它消息渲染逻辑。）CSS：新增 `status-running`（spinner keyframes，仅 transform/opacity）、`status-ok`、`status-error`（沿用 `--error` 令牌红条语义）、`status-interrupted`（次级文字色）。

- [ ] **Step 5: 运行**：`cd frontend && npx vitest run` → PASS（全量前端用例）；`cd frontend && npm run lint` → 无新增告警

---

## 集成验证（主会话执行，不在代理任务内）

1. 全量后端：`.venv/Scripts/python.exe -m pytest -q`
2. 全量前端：`cd frontend && npx vitest run`
3. 差异审查：`git diff` 逐文件核对契约冻结段与约束（无越界文件、无提交）。
4. 统一提交（feat 三段式），必要时手工冒烟（流式/非流式各一轮带工具对话）。
