"""T6 测试：ContextSummarizer 以及 full_summary / summary_recent 策略。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from thumbelina.agent.compression import (
    LOW_WATERMARK,
    FullSummaryCompressor,
    SlidingWindowCompressor,
    SummaryRecentCompressor,
    estimate_messages_tokens,
)
from thumbelina.agent.compression.summarizer_context import (
    MERGE_PROMPT,
    SUMMARY_PROMPT,
    ContextSummarizer,
)

SUMMARY = "一段摘要。"


def _provider(chat: AsyncMock | None = None) -> MagicMock:
    provider = MagicMock()
    provider.chat = chat or AsyncMock(return_value=SUMMARY)
    return provider


def _ai_with_tool_call(call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": "echo", "args": {}}])


class TestContextSummarizer:
    """专用于压缩的摘要器：剥离、分批、失败模式。"""

    @pytest.mark.asyncio
    async def test_single_shot_summarizes(self):
        provider = _provider()
        summarizer = ContextSummarizer(provider)
        result = await summarizer.summarize(
            [HumanMessage(content="你好"), AIMessage(content="你好呀")]
        )
        assert result == SUMMARY
        provider.chat.assert_called_once()
        prompt = provider.chat.call_args[0][0]
        assert prompt[0] == {"role": "system", "content": SUMMARY_PROMPT}
        assert "你好" in prompt[1]["content"]

    @pytest.mark.asyncio
    async def test_thinking_blocks_stripped_before_summarizing(self):
        provider = _provider()
        summarizer = ContextSummarizer(provider)
        await summarizer.summarize(
            [
                AIMessage(
                    content=[
                        {"type": "thinking", "thinking": "内部推理不该出现"},
                        {"type": "text", "text": "可见回答"},
                    ]
                )
            ]
        )
        sent = provider.chat.call_args[0][0][1]["content"]
        assert "内部推理不该出现" not in sent
        assert "可见回答" in sent

    @pytest.mark.asyncio
    async def test_overlong_tool_output_truncated(self):
        provider = _provider()
        summarizer = ContextSummarizer(provider)
        await summarizer.summarize([ToolMessage(content="x" * 10_000, tool_call_id="t1")])
        sent = provider.chat.call_args[0][0][1]["content"]
        assert "[工具输出过长，已截断]" in sent
        assert "x" * 5_000 not in sent

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        provider = _provider(AsyncMock(side_effect=RuntimeError("down")))
        summarizer = ContextSummarizer(provider)
        assert await summarizer.summarize([HumanMessage(content="hi")]) is None

    @pytest.mark.asyncio
    async def test_empty_llm_result_returns_none(self):
        provider = _provider(AsyncMock(return_value="  "))
        summarizer = ContextSummarizer(provider)
        assert await summarizer.summarize([HumanMessage(content="hi")]) is None

    @pytest.mark.asyncio
    async def test_no_provider_returns_none(self):
        assert await ContextSummarizer().summarize([HumanMessage(content="hi")]) is None

    @pytest.mark.asyncio
    async def test_empty_messages_return_none(self):
        assert await ContextSummarizer(_provider()).summarize([]) is None

    @pytest.mark.asyncio
    async def test_batch_recursive_merge(self):
        # 6 × ~26 token 超过 60-token 上限 → 3 个分批 + 1 次合并调用。
        chat = AsyncMock(side_effect=["s1", "s2", "s3", "merged"])
        summarizer = ContextSummarizer(_provider(chat), max_input_tokens=60)
        messages = [HumanMessage(content="a" * 100) for _ in range(6)]
        result = await summarizer.summarize(messages)
        assert result == "merged"
        assert chat.call_count == 4
        last_prompt = chat.call_args[0][0]
        assert last_prompt[0] == {"role": "system", "content": MERGE_PROMPT}
        merged_input = last_prompt[1]["content"]
        assert "s1" in merged_input and "s3" in merged_input
        # 分批调用使用的是普通摘要提示词。
        for call in chat.call_args_list[:3]:
            assert call[0][0][0] == {"role": "system", "content": SUMMARY_PROMPT}

    @pytest.mark.asyncio
    async def test_depth_cap_hard_truncates_input(self):
        chat = AsyncMock(return_value=SUMMARY)
        summarizer = ContextSummarizer(_provider(chat), max_input_tokens=40, max_depth=0)
        result = await summarizer.summarize([HumanMessage(content="x" * 10_000)])
        assert result == SUMMARY
        chat.assert_called_once()
        sent = chat.call_args[0][0][1]["content"]
        assert estimate_messages_tokens([HumanMessage(content=sent)]) <= 40

    @pytest.mark.asyncio
    async def test_single_oversized_entry_truncated_instead_of_split(self):
        chat = AsyncMock(return_value=SUMMARY)
        summarizer = ContextSummarizer(_provider(chat), max_input_tokens=60)
        result = await summarizer.summarize([HumanMessage(content="x" * 10_000)])
        assert result == SUMMARY
        chat.assert_called_once()
        sent = chat.call_args[0][0][1]["content"]
        assert estimate_messages_tokens([HumanMessage(content=sent)]) <= 60


class TestFullSummary:
    """策略 2：头部 + 摘要 + 当前轮尾部。"""

    def _messages(self) -> list:
        return [
            SystemMessage(content="role"),
            HumanMessage(content="x" * 4000),
            AIMessage(content="y" * 4000),
            HumanMessage(content="z" * 4000),
            HumanMessage(content="now"),
        ]

    @pytest.mark.asyncio
    async def test_compresses_below_low_watermark(self):
        messages = self._messages()
        result = await FullSummaryCompressor(_provider()).compress(messages, 1000)
        assert estimate_messages_tokens(result) <= 1000 * LOW_WATERMARK
        assert result[0] is messages[0]  # 会话头部受保护
        assert result[-1] is messages[-1]  # 当前轮受保护
        summaries = [m for m in result if isinstance(m, SystemMessage)]
        assert len(summaries) == 2  # 头部 + 生成的摘要
        assert summaries[1].content.startswith("【对话历史摘要】")
        assert all("x" * 4000 not in str(m.content) for m in result)
        assert all(m.content not in ("y" * 4000, "z" * 4000) for m in result)

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_to_pure_deletion(self):
        messages = self._messages()
        provider = _provider(AsyncMock(side_effect=RuntimeError("down")))
        result = await FullSummaryCompressor(provider).compress(messages, 1000)
        assert result == [messages[0], messages[-1]]
        assert not any(
            isinstance(m, SystemMessage) and m.content.startswith("【对话历史摘要】")
            for m in result
        )

    @pytest.mark.asyncio
    async def test_tool_group_summarized_as_a_whole(self):
        messages = [
            SystemMessage(content="role"),
            HumanMessage(content="start"),
            _ai_with_tool_call("call_1"),
            ToolMessage(content="result", tool_call_id="call_1"),
            AIMessage(content="done"),
            HumanMessage(content="now"),
        ]
        result = await FullSummaryCompressor(_provider()).compress(messages, 1000)
        assert estimate_messages_tokens(result) <= 1000 * LOW_WATERMARK
        assert not any(isinstance(m, ToolMessage) for m in result)
        assert not any(isinstance(m, AIMessage) and m.tool_calls for m in result)

    @pytest.mark.asyncio
    async def test_oversized_summary_truncated_to_budget(self):
        chat = AsyncMock(return_value="x" * 4000)  # 约 1000 个预估 token
        result = await FullSummaryCompressor(_provider(chat)).compress(self._messages(), 1000)
        assert estimate_messages_tokens(result) <= 1000 * LOW_WATERMARK
        summary = next(m for m in result if isinstance(m, SystemMessage) and m is not result[0])
        assert summary.content.endswith("…")
        assert len(summary.content) < 2000  # 被大幅截断

    @pytest.mark.asyncio
    async def test_noop_when_only_head_and_tail(self):
        messages = [SystemMessage(content="role"), HumanMessage(content="now")]
        result = await FullSummaryCompressor(_provider()).compress(messages, 1000)
        assert result == messages

    @pytest.mark.asyncio
    async def test_current_turn_system_injections_are_preserved(self):
        """当前轮的 RAG/技能系统消息注入不得被子摘要掉。"""
        rag = SystemMessage(content="retrieved chunk for the current question")
        messages = [
            SystemMessage(content="role"),
            HumanMessage(content="t1q"),
            AIMessage(content="t1a"),
            rag,
            HumanMessage(content="t2 now"),
        ]
        result = await FullSummaryCompressor(_provider()).compress(messages, 100_000)
        assert any(m is rag for m in result)  # 注入随当前轮保留
        assert any(m is messages[4] for m in result)  # 当前轮输入保留
        assert not any(m is messages[1] for m in result)  # 旧轮被摘要


class TestSummaryRecent:
    """策略 3：汇总旧轮次，原样保留最近 K 轮。"""

    def _turns(self) -> list:
        return [
            SystemMessage(content="role"),
            HumanMessage(content="t1q"),
            AIMessage(content="t1a"),
            HumanMessage(content="t2q"),
            _ai_with_tool_call("c2"),
            ToolMessage(content="t2 result", tool_call_id="c2"),
            AIMessage(content="t2a"),
            HumanMessage(content="t3q"),
            AIMessage(content="t3a"),
            HumanMessage(content="t4 now"),
        ]

    @pytest.mark.asyncio
    async def test_keeps_recent_k_turns_and_summarizes_older(self):
        messages = self._turns()
        compressor = SummaryRecentCompressor(recent_turns=2, llm_provider=_provider())
        result = await compressor.compress(messages, 100_000)
        assert estimate_messages_tokens(result) <= 100_000 * LOW_WATERMARK
        # 保留的第 3、4 轮以其原对象留存。
        assert any(m is messages[7] for m in result)  # t3q
        assert any(m is messages[8] for m in result)  # t3a
        assert any(m is messages[9] for m in result)  # t4
        # 更旧的轮次被摘要替换。
        assert not any(str(m.content).startswith("t1") for m in result)
        assert not any(str(m.content).startswith("t2") for m in result)
        summaries = [m for m in result if isinstance(m, SystemMessage)]
        assert len(summaries) == 2  # role + 摘要
        assert summaries[1].content.startswith("【对话历史摘要】")

    @pytest.mark.asyncio
    async def test_tool_pair_in_kept_turns_intact(self):
        messages = self._turns()
        compressor = SummaryRecentCompressor(recent_turns=3, llm_provider=_provider())
        result = await compressor.compress(messages, 100_000)
        kept_ai = [m for m in result if isinstance(m, AIMessage) and m.tool_calls]
        kept_tool = [m for m in result if isinstance(m, ToolMessage)]
        assert len(kept_ai) == 1 and len(kept_tool) == 1
        assert result.index(kept_ai[0]) < result.index(kept_tool[0])
        assert kept_ai[0].tool_calls[0]["id"] == kept_tool[0].tool_call_id

    @pytest.mark.asyncio
    async def test_k_shrinks_when_recent_turns_exceed_watermark(self):
        messages = [
            SystemMessage(content="role"),
            HumanMessage(content="x" * 4000),  # 第 1 轮：1000 token
            AIMessage(content="t1a"),
            HumanMessage(content="y" * 4000),  # 第 2 轮：1000 token
            AIMessage(content="t2a"),
            HumanMessage(content="now"),  # 当前轮：很小
        ]
        compressor = SummaryRecentCompressor(recent_turns=6, llm_provider=_provider())
        result = await compressor.compress(messages, 1000)
        assert estimate_messages_tokens(result) <= 1000 * LOW_WATERMARK
        # K 一路收缩到只剩当前轮。
        assert result[-1] is messages[-1]
        assert len(result) == 3  # role + 摘要 + 当前轮
        assert not any("x" * 4000 in str(m.content) for m in result)
        assert not any("y" * 4000 in str(m.content) for m in result)
        assert any(
            isinstance(m, SystemMessage) and m.content.startswith("【对话历史摘要】")
            for m in result
        )

    @pytest.mark.asyncio
    async def test_k_fits_without_shrink(self):
        messages = self._turns()
        compressor = SummaryRecentCompressor(recent_turns=2, llm_provider=_provider())
        result = await compressor.compress(messages, 100_000)
        humans = [m for m in result if isinstance(m, HumanMessage)]
        assert [m.content for m in humans] == ["t3q", "t4 now"]

    @pytest.mark.asyncio
    async def test_per_turn_injections_stay_with_their_turn(self):
        rag = SystemMessage(content="rag snippet")
        messages = [
            HumanMessage(content="t1q"),
            AIMessage(content="t1a"),
            rag,
            HumanMessage(content="t2 now"),
        ]
        compressor = SummaryRecentCompressor(recent_turns=1, llm_provider=_provider())
        result = await compressor.compress(messages, 100_000)
        assert any(m is rag for m in result)  # 注入随当前轮保留
        assert any(m is messages[3] for m in result)
        assert not any(m is messages[0] for m in result)

    @pytest.mark.asyncio
    async def test_single_turn_noop(self):
        messages = [SystemMessage(content="role"), HumanMessage(content="now")]
        compressor = SummaryRecentCompressor(recent_turns=6, llm_provider=_provider())
        result = await compressor.compress(messages, 1000)
        assert result == messages

    @pytest.mark.asyncio
    async def test_more_recent_turns_than_history_noop(self):
        messages = self._turns()
        compressor = SummaryRecentCompressor(recent_turns=10, llm_provider=_provider())
        result = await compressor.compress(messages, 100_000)
        assert [m.id for m in result] == [m.id for m in messages]

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_to_pure_deletion(self):
        messages = [
            SystemMessage(content="role"),
            HumanMessage(content="x" * 4000),
            AIMessage(content="t1a"),
            HumanMessage(content="y" * 4000),
            AIMessage(content="t2a"),
            HumanMessage(content="now"),
        ]
        provider = _provider(AsyncMock(side_effect=RuntimeError("down")))
        compressor = SummaryRecentCompressor(recent_turns=2, llm_provider=provider)
        result = await compressor.compress(messages, 1000)
        # 降级结果与纯删除策略完全一致。
        expected = await SlidingWindowCompressor().compress(messages, 1000)
        assert result == expected
        assert not any(
            isinstance(m, SystemMessage) and m.content.startswith("【对话历史摘要】")
            for m in result
        )


class TestSummaryStrategiesThroughAgent:
    """摘要策略的图级行为（MemorySaver）。"""

    @pytest.mark.asyncio
    async def test_summary_recent_replaces_old_turns_end_to_end(self):
        from langgraph.checkpoint.memory import MemorySaver

        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.config.models import ContextCompressConfig, ContextConfig

        provider = MagicMock()
        provider.chat = AsyncMock(return_value="历史摘要文本")
        provider.chat_model = AsyncMock()
        provider.chat_model.ainvoke.side_effect = lambda *a, **k: AIMessage(content="ack")

        agent = ThumbelinaAgent(
            llm_provider=provider,
            checkpointer=MemorySaver(),
            context_config=ContextConfig(
                compress=ContextCompressConfig(
                    strategy="summary_recent", threshold=0.8, recent_turns=1
                )
            ),
            context_window_tokens=1000,
        )
        agent.current_conversation_id = "conv-summary-recent"

        await agent.run("x" * 4000, context_window_tokens=1000)
        await agent.run("second", context_window_tokens=1000)

        snapshot = await agent.graph.aget_state(
            {"configurable": {"thread_id": "conv-summary-recent"}}
        )
        messages = snapshot.values["messages"]
        contents = [m.content for m in messages]
        assert contents[0].startswith("【对话历史摘要】")
        assert "历史摘要文本" in contents[0]
        assert contents[-2:] == ["second", "ack"]
        # 摘要只在第 2 轮运行（第 1 轮没有旧轮次）。窗口 1000 → 单次输入
        # 上限 500，约 1000 token 的旧轮被拆成 2 批 + 1 次归并 = 3 次调用。
        assert provider.chat.call_count == 3

    @pytest.mark.asyncio
    async def test_swap_provider_repoints_compressor_summarizer(self):
        agent = _agent_with_summary_strategy()
        assert isinstance(agent._compressor, SummaryRecentCompressor)
        original = agent._compressor.llm_provider
        new_provider = MagicMock()
        new_provider.chat_model = AsyncMock()
        agent.swap_provider(new_provider)
        assert agent._compressor.llm_provider is new_provider
        assert agent._compressor.llm_provider is not original

    @pytest.mark.asyncio
    async def test_apply_conversation_provider_repoints_compressor_summarizer(self):
        """会话端点切换时，压缩器 summarizer 必须随端点 provider 一起重定向（#7）。"""
        agent = _agent_with_summary_strategy()
        assert isinstance(agent._compressor, SummaryRecentCompressor)
        new_provider = MagicMock()
        new_provider.chat_model = AsyncMock()
        agent.apply_conversation_provider(new_provider)
        assert agent._compressor.llm_provider is new_provider
        assert agent.llm is new_provider.chat_model
        # 重置回默认 provider 时压缩器也随之恢复，而不是停留在端点模型上。
        agent.apply_conversation_provider(None)
        assert agent._compressor.llm_provider is agent.llm_provider
        assert agent.llm is agent.llm_provider.chat_model


def _agent_with_summary_strategy():
    from langgraph.checkpoint.memory import MemorySaver

    from thumbelina.agent.graph import ThumbelinaAgent
    from thumbelina.config.models import ContextCompressConfig, ContextConfig

    provider = MagicMock()
    provider.chat = AsyncMock(return_value=SUMMARY)
    provider.chat_model = AsyncMock()
    provider.chat_model.ainvoke.side_effect = lambda *a, **k: AIMessage(content="ack")
    return ThumbelinaAgent(
        llm_provider=provider,
        checkpointer=MemorySaver(),
        context_config=ContextConfig(compress=ContextCompressConfig(strategy="summary_recent")),
        context_window_tokens=1000,
    )


class TestHeadBoundary:
    """摘要 SystemMessage 不得计入受保护会话头部（#2 重算 head 边界）。"""

    @pytest.mark.asyncio
    async def test_previous_summary_not_counted_as_head(self):
        from thumbelina.agent.compression.base import group_atomic_units
        from thumbelina.agent.compression.summarizer_context import (
            leading_protected_head_count,
        )

        messages = [
            SystemMessage(content="role"),
            SystemMessage(content="【对话历史摘要】\n旧历史要点"),
            HumanMessage(content="t1q"),
            AIMessage(content="t1a"),
            HumanMessage(content="t2 now"),
        ]
        units = group_atomic_units(messages)
        # 只保留会话头部 role，摘要不得进入受保护头部。
        assert leading_protected_head_count(units) == 1

    @pytest.mark.asyncio
    async def test_summary_recent_resummarizes_previous_summary(self):
        compressor = SummaryRecentCompressor(recent_turns=1, llm_provider=_provider())
        messages = [
            SystemMessage(content="role"),
            SystemMessage(content="【对话历史摘要】\n旧历史要点"),
            HumanMessage(content="t1q"),
            AIMessage(content="t1a"),
            HumanMessage(content="t2 now"),
        ]
        result = await compressor.compress(messages, 100_000)
        assert result[0] is messages[0]  # 会话头部受保护
        # 旧摘要被重新摘要（连同更旧的历史），不再原样留在头部。
        assert not any("旧历史要点" in str(m.content) for m in result)
        summaries = [m for m in result if isinstance(m, SystemMessage)]
        assert summaries[1].content.startswith("【对话历史摘要】")

    @pytest.mark.asyncio
    async def test_head_stays_bounded_across_cycles(self):
        from thumbelina.agent.compression.base import group_atomic_units
        from thumbelina.agent.compression.summarizer_context import (
            leading_protected_head_count,
        )

        compressor = SummaryRecentCompressor(recent_turns=2, llm_provider=_provider())
        messages = [
            SystemMessage(content="role"),
            HumanMessage(content="t1q"),
            AIMessage(content="t1a"),
            HumanMessage(content="t2q"),
            AIMessage(content="t2a"),
            HumanMessage(content="t3q"),
            AIMessage(content="t3a"),
            HumanMessage(content="t4 now"),
        ]
        head_counts = []
        for index in range(5):
            result = await compressor.compress(messages, 100_000)
            messages = result + [
                HumanMessage(content=f"next{index + 5}q"),
                AIMessage(content=f"next{index + 5}a"),
            ]
            head_counts.append(leading_protected_head_count(group_atomic_units(messages)))
        assert len(set(head_counts)) == 1  # 头部尺寸恒定，不随压缩轮次膨胀

    @pytest.mark.asyncio
    async def test_full_summary_resummarizes_previous_summary(self):
        compressor = FullSummaryCompressor(_provider())
        messages = [
            SystemMessage(content="role"),
            SystemMessage(content="【对话历史摘要】\n旧历史要点"),
            HumanMessage(content="x" * 4000),
            AIMessage(content="y" * 4000),
            HumanMessage(content="now"),
        ]
        result = await compressor.compress(messages, 1000)
        assert result[0] is messages[0]  # 会话头部受保护
        assert not any("旧历史要点" in str(m.content) for m in result)
        summaries = [m for m in result if isinstance(m, SystemMessage)]
        assert summaries[1].content.startswith("【对话历史摘要】")


class TestWindowLinkedInputCap:
    """摘要调用输入上限与模型窗口联动（四.5.2 扩展）。"""

    def test_cap_resolves_to_half_of_window(self):
        from thumbelina.agent.compression.summarizer_context import resolve_input_cap

        assert resolve_input_cap(100) == 50
        assert resolve_input_cap(1000) == 500

    def test_cap_capped_at_default_ceiling(self):
        from thumbelina.agent.compression.summarizer_context import (
            DEFAULT_MAX_INPUT_TOKENS,
            resolve_input_cap,
        )

        assert resolve_input_cap(1_000_000) == DEFAULT_MAX_INPUT_TOKENS

    def test_cap_clamps_tiny_windows_to_one(self):
        from thumbelina.agent.compression.summarizer_context import resolve_input_cap

        assert resolve_input_cap(1) == 1
        assert resolve_input_cap(0) == 1

    @pytest.mark.asyncio
    async def test_full_summary_small_window_caps_single_call_input(self):
        # 窗口 100 → 输入上限 50；middle 远超上限时调用前截断。
        chat = AsyncMock(return_value=SUMMARY)
        compressor = FullSummaryCompressor()
        compressor.llm_provider = _provider(chat)
        # 最后一个轮次（当前输入）始终受保护；更旧的轮次进入 middle。
        messages = [
            HumanMessage(content="x" * 500),
            AIMessage(content="y" * 500),
            HumanMessage(content="now"),
        ]
        result = await compressor.compress(messages, window_tokens=100)
        assert result is not None
        sent = chat.call_args[0][0][1]["content"]
        assert estimate_messages_tokens([HumanMessage(content=sent)]) <= 50

    @pytest.mark.asyncio
    async def test_summary_recent_small_window_caps_single_call_input(self):
        # 窗口 100 → 输入上限 50；仅保留最近 1 轮，旧轮进入摘要且被截断。
        chat = AsyncMock(return_value=SUMMARY)
        compressor = SummaryRecentCompressor(recent_turns=1)
        compressor.llm_provider = _provider(chat)
        messages = [
            HumanMessage(content="a" * 500),
            AIMessage(content="b" * 100),
            HumanMessage(content="c" * 100),
            AIMessage(content="d" * 100),
        ]
        result = await compressor.compress(messages, window_tokens=100)
        assert result is not None
        sent = chat.call_args[0][0][1]["content"]
        assert estimate_messages_tokens([HumanMessage(content=sent)]) <= 50
