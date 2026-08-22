"""压缩框架与压缩图节点（T5）的测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from thumbelina.agent.compression import (
    LOW_WATERMARK,
    ContextCompressor,
    SlidingWindowCompressor,
    available_strategies,
    create_compressor,
    ensure_tool_pairing,
    estimate_messages_tokens,
    group_atomic_units,
    register_compressor,
    strip_first_assistant_thinking,
)
from thumbelina.agent.compression.base import INTERRUPTED_TOOL_PLACEHOLDER
from thumbelina.agent.graph import ThumbelinaAgent, _messages_state_update


def _ai_with_tool_call(call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"id": call_id, "name": "echo", "args": {"text": "hi"}}]
    )


def _make_mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.chat_model = MagicMock()
    # 每次调用都返回全新的 AIMessage：add_messages 按 id 合并，
    # 共享对象会被替换而不是追加。
    provider.chat_model.ainvoke = AsyncMock(side_effect=lambda *a, **k: AIMessage(content="ack"))
    # agent 始终携带内置通知工具，图会调用 bind_tools；返回自身保持 ainvoke 行为。
    provider.chat_model.bind_tools.return_value = provider.chat_model
    return provider


def _sequenced_side_effect(factories):
    """每次 ainvoke 调用返回一条全新回复。

    ``unittest.mock`` 会把可迭代 ``side_effect`` 的元素原样返回
    （可调用对象不会被调用），因此用一个分发可调用对象逐个弹出
    下一个工厂并调用它 —— 每条回复都是全新消息。
    """
    queue = iter(factories)

    def dispatch(*args, **kwargs):
        return next(queue)(*args, **kwargs)

    return dispatch


def _make_agent(
    default_window: int | None = None,
    strategy: str = "sliding_window",
    threshold: float = 0.8,
    tools: list | None = None,
    provider: MagicMock | None = None,
) -> tuple[ThumbelinaAgent, MagicMock]:
    from langgraph.checkpoint.memory import MemorySaver

    from thumbelina.config.models import ContextCompressConfig, ContextConfig

    mock_provider = provider or _make_mock_provider()
    agent = ThumbelinaAgent(
        llm_provider=mock_provider,
        tools=tools,
        checkpointer=MemorySaver(),
        context_config=ContextConfig(
            compress=ContextCompressConfig(strategy=strategy, threshold=threshold)
        ),
        context_window_tokens=default_window,
    )
    agent.current_conversation_id = "conv-compress"
    return agent, mock_provider


class TestFactory:
    """策略注册表与创建。"""

    def test_builtin_strategies_registered(self):
        assert {"sliding_window", "full_summary", "summary_recent"} <= set(available_strategies())

    def test_create_sliding_window(self):
        assert isinstance(create_compressor("sliding_window"), SlidingWindowCompressor)

    @pytest.mark.parametrize("name", ["full_summary", "summary_recent"])
    def test_summarizing_strategies_resolve(self, name):
        compressor = create_compressor(name)
        assert isinstance(compressor, ContextCompressor)

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown compression strategy"):
            create_compressor("does_not_exist")

    def test_register_third_party_strategy(self):
        class NoopCompressor(ContextCompressor):
            name = "noop_test"

            async def compress(self, messages, window_tokens):
                return list(messages)

        register_compressor("noop_test_unique", NoopCompressor)
        assert isinstance(create_compressor("noop_test_unique"), NoopCompressor)

    def test_duplicate_registration_raises(self):
        with pytest.raises(ValueError, match="already registered"):
            register_compressor("sliding_window", SlidingWindowCompressor)

    def test_kwargs_filtered_by_constructor_signature(self):
        compressor = create_compressor("summary_recent", recent_turns=3)
        assert compressor.recent_turns == 3
        # sliding_window 未声明参数 —— 多余参数被丢弃。
        sliding = create_compressor("sliding_window", recent_turns=3)
        assert isinstance(sliding, SlidingWindowCompressor)


class TestEstimation:
    """用量估算复用 RAG 上下文 formatter 的估算器。"""

    def test_matches_context_formatter_estimator(self):
        from thumbelina.rag.retrieval.context_formatter import estimate_tokens

        text = "你好" * 10
        messages = [HumanMessage(content=text)]
        assert estimate_messages_tokens(messages) == estimate_tokens(text) == 40

    def test_ascii_estimate(self):
        assert estimate_messages_tokens([HumanMessage(content="x" * 4000)]) == 1000

    def test_block_content_is_counted(self):
        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "ab"},
                {"type": "text", "text": "cd"},
            ]
        )
        assert estimate_messages_tokens([message]) == 1


class TestGroupDeletionUnits:
    """AIMessage(tool_calls) 与 ToolMessage 构成原子单元。"""

    def test_tool_pair_grouped(self):
        ai = _ai_with_tool_call()
        tool = ToolMessage(content="ok", tool_call_id="call_1")
        units = group_atomic_units(
            [HumanMessage(content="hi"), ai, tool, AIMessage(content="done")]
        )
        assert [len(unit) for unit in units] == [1, 2, 1]
        assert units[1][0] is ai
        assert units[1][1] is tool

    def test_plain_messages_are_singletons(self):
        messages = [HumanMessage(content="a"), AIMessage(content="b")]
        units = group_atomic_units(messages)
        assert len(units) == 2
        assert all(len(unit) == 1 for unit in units)
        assert units[0][0] is messages[0]
        assert units[1][0] is messages[1]

    def test_unrelated_tool_message_not_grouped(self):
        ai = _ai_with_tool_call("call_1")
        foreign = ToolMessage(content="stale", tool_call_id="call_other")
        units = group_atomic_units([ai, foreign])
        assert [len(unit) for unit in units] == [1, 1]


class TestEnsureToolPairing:
    """配对不变量修复：悬空 tool_calls 补占位，孤儿 ToolMessage 剔除。"""

    def test_well_formed_returns_same_object(self):
        ai = _ai_with_tool_call("c1")
        tool = ToolMessage(content="ok", tool_call_id="c1")
        messages = [HumanMessage(content="hi"), ai, tool]
        assert ensure_tool_pairing(messages) is messages  # 零改动，保留附加前缀

    def test_dangling_tool_call_gets_placeholder_response(self):
        ai = _ai_with_tool_call("c1")
        human = HumanMessage(content="now")
        # c1 之后没有紧跟任何 ToolMessage —— c1 悬空。
        repaired = ensure_tool_pairing([human, ai])
        assert len(repaired) == 3  # 原 2 条 + 1 条占位
        assert repaired != [human, ai]
        assert isinstance(repaired[-1], ToolMessage)
        assert repaired[-1].tool_call_id == "c1"
        assert repaired[-1].content == INTERRUPTED_TOOL_PLACEHOLDER
        # 其他消息原样保留（沿用对象）。
        assert repaired[0] is human
        assert repaired[1] is ai

    def test_partial_responses_filled_in_order(self):
        ai = AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "echo", "args": {}},
                {"id": "c2", "name": "echo", "args": {}},
                {"id": "c3", "name": "echo", "args": {}},
            ],
        )
        tool1 = ToolMessage(content="r1", tool_call_id="c1")
        tool3 = ToolMessage(content="r3", tool_call_id="c3")
        repaired = ensure_tool_pairing([ai, tool1, tool3])
        tool_ids = [m.tool_call_id for m in repaired if isinstance(m, ToolMessage)]
        assert tool_ids == ["c1", "c3", "c2"]  # c2 按声明顺序补在已响应之后
        assert repaired[-1].content == INTERRUPTED_TOOL_PLACEHOLDER

    def test_orphaned_tool_message_dropped(self):
        tool = ToolMessage(content="stale", tool_call_id="c9")
        human = HumanMessage(content="hi")
        repaired = ensure_tool_pairing([tool, human])
        assert repaired == [human]

    def test_mismatched_tool_message_after_ai_dropped(self):
        ai = _ai_with_tool_call("c1")
        foreign = ToolMessage(content="foreign", tool_call_id="c_other")
        repaired = ensure_tool_pairing([ai, foreign])
        # foreign 不与 c1 匹配 → 丢弃；c1 本身缺响应 → 补占位。
        assert [m.tool_call_id for m in repaired if isinstance(m, ToolMessage)] == ["c1"]

    def test_additional_kwargs_tool_calls_counted(self):
        ai = AIMessage(content="")
        ai.additional_kwargs["tool_calls"] = [{"id": "c9", "name": "echo", "arguments": "{}"}]
        repaired = ensure_tool_pairing([ai])
        assert repaired != [ai]
        assert repaired[-1].tool_call_id == "c9"
        assert repaired[-1].content == INTERRUPTED_TOOL_PLACEHOLDER

    def test_consecutive_tool_rounds_repaired_independently(self):
        ai1 = _ai_with_tool_call("c1")
        tool1 = ToolMessage(content="r1", tool_call_id="c1")
        ai2 = _ai_with_tool_call("c2")  # 悬空
        messages = [ai1, tool1, ai2]
        repaired = ensure_tool_pairing(messages)
        assert [m.tool_call_id for m in repaired if isinstance(m, ToolMessage)] == ["c1", "c2"]
        assert repaired[-1].content == INTERRUPTED_TOOL_PLACEHOLDER

    def test_idempotent_after_repair(self):
        ai = _ai_with_tool_call("c1")
        once = ensure_tool_pairing([ai])
        assert ensure_tool_pairing(once) is once  # 补占位后再修复 → 零改动


class TestSlidingWindow:
    """策略 1：丢弃最旧的消息，降到低水位。"""

    @pytest.mark.asyncio
    async def test_compresses_below_low_watermark(self):
        messages = [HumanMessage(content="x" * 4000) for _ in range(3)] + [AIMessage(content="ok")]
        result = await SlidingWindowCompressor().compress(messages, window_tokens=1000)
        assert estimate_messages_tokens(result) <= 1000 * LOW_WATERMARK
        # 先丢最旧的；最后一个单元永远保留。
        assert result[-1].content == "ok"
        assert len(result) < len(messages)

    @pytest.mark.asyncio
    async def test_tool_group_dropped_as_a_whole(self):
        big_head = HumanMessage(content="x" * 4000)
        ai = _ai_with_tool_call()
        tool = ToolMessage(content="result", tool_call_id="call_1")
        big_tail = HumanMessage(content="y" * 4000)
        result = await SlidingWindowCompressor().compress(
            [big_head, ai, tool, big_tail], window_tokens=1000
        )
        kept_ai = any(m is ai for m in result)
        kept_tool = any(m is tool for m in result)
        assert kept_ai == kept_tool  # 配对绝不会被拆开
        assert not kept_ai  # 两者都被丢弃以降到低水位
        assert any(m is big_tail for m in result)  # 当前轮受到保护

    @pytest.mark.asyncio
    async def test_tool_group_kept_as_a_whole(self):
        big_head = HumanMessage(content="x" * 4000)
        ai = _ai_with_tool_call()
        tool = ToolMessage(content="result", tool_call_id="call_1")
        tail = HumanMessage(content="now")
        result = await SlidingWindowCompressor().compress(
            [big_head, ai, tool, tail], window_tokens=1000
        )
        # 只丢头部即可降到低水位；配对保留。
        assert any(m is ai for m in result) and any(m is tool for m in result)
        assert not any(m is big_head for m in result)

    @pytest.mark.asyncio
    async def test_leading_system_messages_protected(self):
        role = SystemMessage(content="role prompt")
        profile = SystemMessage(content="user profile")
        filler = HumanMessage(content="x" * 4000)
        stale = AIMessage(content="y" * 4000)
        current = HumanMessage(content="now")
        result = await SlidingWindowCompressor().compress(
            [role, profile, filler, stale, current], window_tokens=1000
        )
        assert result[0] is role
        assert result[1] is profile
        assert any(m is current for m in result)

    @pytest.mark.asyncio
    async def test_noop_when_only_protected_messages(self):
        role = SystemMessage(content="role")
        current = HumanMessage(content="x" * 4000)
        result = await SlidingWindowCompressor().compress([role, current], window_tokens=100)
        assert len(result) == 2


class TestStripThinking:
    """Anthropic 边界：剥离第一条 assistant 的 thinking 块。"""

    def test_strips_thinking_from_first_assistant(self):
        ai = AIMessage(
            content=[
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": "answer"},
            ]
        )
        result = strip_first_assistant_thinking([ai])
        assert result[0].content == [{"type": "text", "text": "answer"}]
        assert result[0].id == ai.id  # 同一条消息，就地更新

    def test_only_first_assistant_touched(self):
        ai1 = AIMessage(
            content=[{"type": "thinking", "thinking": "a"}, {"type": "text", "text": "1"}]
        )
        ai2 = AIMessage(
            content=[{"type": "thinking", "thinking": "b"}, {"type": "text", "text": "2"}]
        )
        result = strip_first_assistant_thinking([HumanMessage(content="q"), ai1, ai2])
        assert result[1] is not ai1  # 被剥离后的副本替换
        assert result[2] is ai2  # 未被触碰

    def test_no_thinking_returns_same_list(self):
        messages = [AIMessage(content="plain")]
        assert strip_first_assistant_thinking(messages) is messages

    def test_string_content_untouched(self):
        ai = AIMessage(content="no blocks")
        assert strip_first_assistant_thinking([ai]) == [ai]


class TestMessagesStateUpdate:
    """压缩后的序列转换为 add_messages 更新。"""

    def test_pure_deletion_emits_remove_only(self):
        kept = AIMessage(content="keep", id="a")
        dropped = HumanMessage(content="drop", id="b")
        update = _messages_state_update([dropped, kept], [kept])
        assert update == {"messages": [RemoveMessage(id="b")]}

    def test_modified_kept_message_is_reemitted(self):
        original = AIMessage(content=[{"type": "thinking", "thinking": "x"}], id="a")
        stripped = original.model_copy(update={"content": ""})
        update = _messages_state_update([original], [stripped])
        assert update == {"messages": [stripped]}

    def test_no_change_emits_empty_update(self):
        message = HumanMessage(content="same", id="a")
        assert _messages_state_update([message], [message]) == {}

    def test_restructuring_replaces_whole_sequence(self):
        old = [HumanMessage(content="a", id="1"), AIMessage(content="b", id="2")]
        summary = SystemMessage(content="summary")  # 新消息，无 id
        update = _messages_state_update(old, [summary, old[1]])
        assert update["messages"][:2] == [RemoveMessage(id="1"), RemoveMessage(id="2")]
        assert update["messages"][2] is summary
        # 被复用的保留消息会以全新 id 重新发出，使 add_messages 把
        # 它们追加在摘要之后，而不是插回原来的位置。
        assert update["messages"][3].content == "b"
        assert update["messages"][3].id is None


class TestCompressNode:
    """压缩节点的图级行为（MemorySaver）。"""

    def test_graph_has_compress_entry_node(self):
        agent, _ = _make_agent()
        assert "compress" in agent.graph.nodes

    def test_agent_unknown_strategy_degrades_to_sliding_window(self):
        from thumbelina.config.models import ContextCompressConfig, ContextConfig

        broken = ContextConfig(
            compress=ContextCompressConfig.model_construct(
                strategy="bogus", threshold=0.8, recent_turns=6
            )
        )
        agent = ThumbelinaAgent(llm_provider=_make_mock_provider(), context_config=broken)
        assert isinstance(agent._compressor, SlidingWindowCompressor)

    def test_clone_propagates_context_settings(self):
        agent, _ = _make_agent(default_window=4321)
        cloned = agent.clone()
        assert cloned._context_config is agent._context_config
        assert cloned._context_window_tokens == 4321
        assert cloned._compressor.name == agent._compressor.name

    @pytest.mark.asyncio
    async def test_direct_node_passes_through_below_threshold(self):
        agent, _ = _make_agent(default_window=1000)
        state = {"messages": [HumanMessage(content="x" * 3000, id="h1")]}  # 750 < 800
        assert await agent._compress_node(state, {"configurable": {}}) == {}

    @pytest.mark.asyncio
    async def test_direct_node_triggers_at_threshold(self):
        agent, _ = _make_agent(default_window=1000)
        dropped = HumanMessage(content="x" * 3200, id="h1")  # 正好 800 >= 800
        kept_ai = AIMessage(content="a", id="a1")
        kept_human = HumanMessage(content="b", id="h2")
        state = {"messages": [dropped, kept_ai, kept_human]}
        update = await agent._compress_node(state, {"configurable": {}})
        assert update == {"messages": [RemoveMessage(id="h1")]}

    @pytest.mark.asyncio
    async def test_direct_node_repairs_dangling_tool_calls_below_threshold(self):
        """低于压缩阈值时也要修复悬空 tool_calls（中断轮次遗留的畸形状态）。"""
        agent, _ = _make_agent(default_window=1_000_000)  # 永不触发压缩
        ai = AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "echo", "args": {}},
                {"id": "c2", "name": "echo", "args": {}},
            ],
            id="ai1",
        )
        tool1 = ToolMessage(content="r1", tool_call_id="c1", id="t1")
        current = HumanMessage(content="now", id="h1")
        state = {"messages": [ai, tool1, current]}
        update = await agent._compress_node(state, {"configurable": {}})
        # 修复写回了状态更新（不再 no-op）。
        assert update
        # 应用更新后（RemoveMessages + 追加）序列应满足配对不变量。
        from langgraph.graph.message import add_messages

        applied = add_messages(state["messages"], update["messages"])
        tool_ids = [m.tool_call_id for m in applied if isinstance(m, ToolMessage)]
        assert tool_ids == ["c1", "c2"]
        assert applied[-2].content == INTERRUPTED_TOOL_PLACEHOLDER

    @pytest.mark.asyncio
    async def test_direct_node_clean_state_below_threshold_is_noop(self):
        """无畸形且低于阈值：零改动放行，保留纯追加前缀。"""
        agent, _ = _make_agent(default_window=1_000_000)
        messages = [
            HumanMessage(content="a", id="h1"),
            AIMessage(content="b", id="a1"),
            HumanMessage(content="c", id="h2"),
        ]
        state = {"messages": messages}
        assert await agent._compress_node(state, {"configurable": {}}) == {}

    @pytest.mark.asyncio
    async def test_direct_node_without_window_is_noop(self):
        agent, _ = _make_agent(default_window=None)
        state = {
            "messages": [
                HumanMessage(content="x" * 40000, id="h1"),
                AIMessage(content="a", id="a1"),
                HumanMessage(content="b", id="h2"),
            ]
        }
        assert await agent._compress_node(state, {"configurable": {}}) == {}

    @pytest.mark.asyncio
    async def test_threshold_triggers_compression(self):
        agent, provider = _make_agent()
        await agent.run("x" * 4000, context_window_tokens=1000)
        await agent.run("second", context_window_tokens=1000)

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        contents = [m.content for m in snapshot.values["messages"]]
        # 1000-token 的首条消息被丢弃，以降到 50% 低水位。
        assert contents == ["ack", "second", "ack"]
        # LLM 在第二轮从未看到被丢弃的消息。
        sent = provider.chat_model.ainvoke.call_args[0][0]
        assert [m.content for m in sent] == ["ack", "second"]

    @pytest.mark.asyncio
    async def test_below_threshold_passes_through_untouched(self):
        agent, _ = _make_agent()
        await agent.run("x" * 4000, context_window_tokens=1_000_000)
        await agent.run("second", context_window_tokens=1_000_000)

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        contents = [m.content for m in snapshot.values["messages"]]
        assert contents == ["x" * 4000, "ack", "second", "ack"]

    @pytest.mark.asyncio
    async def test_window_falls_back_to_agent_default(self):
        agent, _ = _make_agent(default_window=1000)  # 未传入单次调用的窗口
        await agent.run("x" * 4000)
        await agent.run("second")

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        contents = [m.content for m in snapshot.values["messages"]]
        assert contents == ["ack", "second", "ack"]

    @pytest.mark.asyncio
    async def test_no_window_anywhere_never_compresses(self):
        agent, _ = _make_agent(default_window=None)
        await agent.run("x" * 4000)
        await agent.run("second")

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        contents = [m.content for m in snapshot.values["messages"]]
        assert contents == ["x" * 4000, "ack", "second", "ack"]

    @pytest.mark.asyncio
    async def test_tool_pairs_stay_intact_across_compression(self):
        from langchain_core.tools import tool

        @tool
        async def echo(text: str) -> str:
            """原样返回输入的文本。"""
            return text

        responses = [
            # 第 1 轮：带大工具结果（约 1000 token）的工具调用循环。
            lambda *a, **k: AIMessage(
                content="",
                tool_calls=[{"id": "call_A", "name": "echo", "args": {"text": "t" * 4000}}],
            ),
            lambda *a, **k: AIMessage(content="done1 " + "y" * 4000),
            # 第 2 轮。
            lambda *a, **k: AIMessage(content="done2 " + "z" * 4000),
            # 第 3 轮。
            lambda *a, **k: AIMessage(content="final"),
        ]
        bound_model = AsyncMock()
        bound_model.ainvoke.side_effect = _sequenced_side_effect(responses)
        provider = MagicMock()
        provider.chat_model = MagicMock()
        provider.chat_model.bind_tools.return_value = bound_model

        agent, _ = _make_agent(default_window=3000, tools=[echo], provider=provider)
        await agent.run("start")
        await agent.run("more")
        await agent.run("final?")

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        messages: list[BaseMessage] = snapshot.values["messages"]

        # 压缩确实发生了（最旧的轮次被丢弃）。
        assert all(m.content != "start" for m in messages)
        assert len(messages) < 7
        # 工具调用组被整体丢弃：没有孤立的半边残留。
        assert not any(isinstance(m, ToolMessage) for m in messages)
        assert not any(isinstance(m, AIMessage) and m.tool_calls for m in messages)

        # 不变量：没有孤立的 ToolMessage，也没有孤立的 tool_calls ——
        # 每个 ToolMessage 的所有者 AIMessage 都在其之前。
        seen_call_ids: set[str] = set()
        for message in messages:
            if isinstance(message, AIMessage) and message.tool_calls:
                seen_call_ids.update(call["id"] for call in message.tool_calls)
            elif isinstance(message, ToolMessage):
                assert message.tool_call_id in seen_call_ids

    @pytest.mark.asyncio
    async def test_thinking_stripped_from_promoted_first_assistant(self):
        responses = [
            lambda *a, **k: AIMessage(
                content=[
                    {"type": "thinking", "thinking": "deep thought"},
                    {"type": "text", "text": "first answer"},
                ]
            ),
            lambda *a, **k: AIMessage(content="second answer"),
        ]
        provider = MagicMock()
        provider.chat_model = MagicMock()
        provider.chat_model.ainvoke = AsyncMock(side_effect=_sequenced_side_effect(responses))
        provider.chat_model.bind_tools.return_value = provider.chat_model

        agent, _ = _make_agent(provider=provider)
        await agent.run("x" * 4000, context_window_tokens=1000)
        await agent.run("second", context_window_tokens=1000)

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        messages = snapshot.values["messages"]
        # 大的 human 轮次被丢弃，assistant 轮次被提升到头部。
        assert isinstance(messages[0], AIMessage)
        assert messages[0].content == [{"type": "text", "text": "first answer"}]

    @pytest.mark.asyncio
    async def test_summary_strategy_llm_failure_falls_back_to_sliding_window(self):
        # summary_recent 自 T6 起实现：摘要 LLM 失败时必须降级为
        # 纯删除，而不是让会话失败。
        provider = _make_mock_provider()
        provider.chat = AsyncMock(side_effect=RuntimeError("summarizer down"))
        agent, _ = _make_agent(strategy="summary_recent", provider=provider)
        await agent.run("x" * 4000, context_window_tokens=1000)
        await agent.run("second", context_window_tokens=1000)

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        contents = [m.content for m in snapshot.values["messages"]]
        assert contents == ["ack", "second", "ack"]
