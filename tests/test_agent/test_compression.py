"""Tests for the compression framework and the compress graph node (T5)."""

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
    estimate_messages_tokens,
    group_deletion_units,
    register_compressor,
    strip_first_assistant_thinking,
)
from thumbelina.agent.graph import ThumbelinaAgent, _messages_state_update


def _ai_with_tool_call(call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"id": call_id, "name": "echo", "args": {"text": "hi"}}]
    )


def _make_mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.chat_model = AsyncMock()
    # Fresh AIMessage per call: add_messages merges by id, so a shared
    # object would be replaced instead of appended.
    provider.chat_model.ainvoke.side_effect = lambda *a, **k: AIMessage(content="ack")
    return provider


def _sequenced_side_effect(factories):
    """One fresh reply per ainvoke call.

    ``unittest.mock`` returns elements of an iterable ``side_effect``
    verbatim (callables are not invoked), so a single dispatcher callable
    pops the next factory and calls it — each reply is a fresh message.
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
    """Strategy registry and creation."""

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
        # sliding_window declares no parameters — extras are dropped.
        sliding = create_compressor("sliding_window", recent_turns=3)
        assert isinstance(sliding, SlidingWindowCompressor)


class TestEstimation:
    """Usage estimation reuses the RAG context formatter estimator."""

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
    """AIMessage(tool_calls) and ToolMessages form atomic units."""

    def test_tool_pair_grouped(self):
        ai = _ai_with_tool_call()
        tool = ToolMessage(content="ok", tool_call_id="call_1")
        units = group_deletion_units(
            [HumanMessage(content="hi"), ai, tool, AIMessage(content="done")]
        )
        assert [len(unit) for unit in units] == [1, 2, 1]
        assert units[1][0] is ai
        assert units[1][1] is tool

    def test_plain_messages_are_singletons(self):
        messages = [HumanMessage(content="a"), AIMessage(content="b")]
        units = group_deletion_units(messages)
        assert len(units) == 2
        assert all(len(unit) == 1 for unit in units)
        assert units[0][0] is messages[0]
        assert units[1][0] is messages[1]

    def test_unrelated_tool_message_not_grouped(self):
        ai = _ai_with_tool_call("call_1")
        foreign = ToolMessage(content="stale", tool_call_id="call_other")
        units = group_deletion_units([ai, foreign])
        assert [len(unit) for unit in units] == [1, 1]


class TestSlidingWindow:
    """Strategy 1: drop oldest messages down to the low watermark."""

    @pytest.mark.asyncio
    async def test_compresses_below_low_watermark(self):
        messages = [HumanMessage(content="x" * 4000) for _ in range(3)] + [AIMessage(content="ok")]
        result = await SlidingWindowCompressor().compress(messages, window_tokens=1000)
        assert estimate_messages_tokens(result) <= 1000 * LOW_WATERMARK
        # Oldest dropped first; the final unit always survives.
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
        assert kept_ai == kept_tool  # pair never split
        assert not kept_ai  # both were dropped to reach the watermark
        assert any(m is big_tail for m in result)  # current turn protected

    @pytest.mark.asyncio
    async def test_tool_group_kept_as_a_whole(self):
        big_head = HumanMessage(content="x" * 4000)
        ai = _ai_with_tool_call()
        tool = ToolMessage(content="result", tool_call_id="call_1")
        tail = HumanMessage(content="now")
        result = await SlidingWindowCompressor().compress(
            [big_head, ai, tool, tail], window_tokens=1000
        )
        # Dropping the head alone reaches the watermark; the pair survives.
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
    """Anthropic boundary: strip thinking blocks from the first assistant."""

    def test_strips_thinking_from_first_assistant(self):
        ai = AIMessage(
            content=[
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": "answer"},
            ]
        )
        result = strip_first_assistant_thinking([ai])
        assert result[0].content == [{"type": "text", "text": "answer"}]
        assert result[0].id == ai.id  # same message, updated in place

    def test_only_first_assistant_touched(self):
        ai1 = AIMessage(
            content=[{"type": "thinking", "thinking": "a"}, {"type": "text", "text": "1"}]
        )
        ai2 = AIMessage(
            content=[{"type": "thinking", "thinking": "b"}, {"type": "text", "text": "2"}]
        )
        result = strip_first_assistant_thinking([HumanMessage(content="q"), ai1, ai2])
        assert result[1] is not ai1  # replaced by stripped copy
        assert result[2] is ai2  # untouched

    def test_no_thinking_returns_same_list(self):
        messages = [AIMessage(content="plain")]
        assert strip_first_assistant_thinking(messages) is messages

    def test_string_content_untouched(self):
        ai = AIMessage(content="no blocks")
        assert strip_first_assistant_thinking([ai]) == [ai]


class TestMessagesStateUpdate:
    """Compressed sequences translate into add_messages updates."""

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
        summary = SystemMessage(content="summary")  # new message, no id
        update = _messages_state_update(old, [summary, old[1]])
        assert update["messages"][:2] == [RemoveMessage(id="1"), RemoveMessage(id="2")]
        assert update["messages"][2] is summary
        # Reused kept messages are re-emitted with fresh ids so add_messages
        # appends them after the summary instead of re-inserting at their
        # original position.
        assert update["messages"][3].content == "b"
        assert update["messages"][3].id is None


class TestCompressNode:
    """Graph-level behaviour of the compress node (MemorySaver)."""

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
        dropped = HumanMessage(content="x" * 3200, id="h1")  # exactly 800 >= 800
        kept_ai = AIMessage(content="a", id="a1")
        kept_human = HumanMessage(content="b", id="h2")
        state = {"messages": [dropped, kept_ai, kept_human]}
        update = await agent._compress_node(state, {"configurable": {}})
        assert update == {"messages": [RemoveMessage(id="h1")]}

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
        # The 1000-token first message was dropped to reach the 50% watermark.
        assert contents == ["ack", "second", "ack"]
        # The LLM never saw the dropped message on the second turn.
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
        agent, _ = _make_agent(default_window=1000)  # no per-call window passed
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
            """Echo the input text."""
            return text

        responses = [
            # Turn 1: tool-call loop with a large tool result (~1000 tokens).
            lambda *a, **k: AIMessage(
                content="",
                tool_calls=[{"id": "call_A", "name": "echo", "args": {"text": "t" * 4000}}],
            ),
            lambda *a, **k: AIMessage(content="done1 " + "y" * 4000),
            # Turn 2.
            lambda *a, **k: AIMessage(content="done2 " + "z" * 4000),
            # Turn 3.
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

        # Compression actually happened (oldest turns dropped).
        assert all(m.content != "start" for m in messages)
        assert len(messages) < 7
        # The tool-call group was dropped as a whole: no orphan half left.
        assert not any(isinstance(m, ToolMessage) for m in messages)
        assert not any(isinstance(m, AIMessage) and m.tool_calls for m in messages)

        # Invariant: no orphan ToolMessage and no orphan tool_calls —
        # every ToolMessage's owning AIMessage precedes it.
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
        provider.chat_model = AsyncMock()
        provider.chat_model.ainvoke.side_effect = _sequenced_side_effect(responses)

        agent, _ = _make_agent(provider=provider)
        await agent.run("x" * 4000, context_window_tokens=1000)
        await agent.run("second", context_window_tokens=1000)

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        messages = snapshot.values["messages"]
        # The big human turn was dropped, promoting the assistant turn.
        assert isinstance(messages[0], AIMessage)
        assert messages[0].content == [{"type": "text", "text": "first answer"}]

    @pytest.mark.asyncio
    async def test_summary_strategy_llm_failure_falls_back_to_sliding_window(self):
        # summary_recent is implemented since T6: a failing summarizer LLM
        # must degrade to pure deletion instead of failing the conversation.
        provider = _make_mock_provider()
        provider.chat = AsyncMock(side_effect=RuntimeError("summarizer down"))
        agent, _ = _make_agent(strategy="summary_recent", provider=provider)
        await agent.run("x" * 4000, context_window_tokens=1000)
        await agent.run("second", context_window_tokens=1000)

        snapshot = await agent.graph.aget_state({"configurable": {"thread_id": "conv-compress"}})
        contents = [m.content for m in snapshot.values["messages"]]
        assert contents == ["ack", "second", "ack"]
