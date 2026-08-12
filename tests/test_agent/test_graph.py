"""Tests for thumbelina.agent.graph module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage


def _create_mock_provider():
    """Create a mock LLMProvider for testing."""
    mock_provider = MagicMock()
    mock_provider.chat_model = AsyncMock()
    mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello! How can I help?")
    return mock_provider


class TestThumbelinaAgent:
    """Tests for the ThumbelinaAgent class."""

    def test_agent_class_exists(self):
        """ThumbelinaAgent should be importable."""
        from thumbelina.agent.graph import ThumbelinaAgent

        assert ThumbelinaAgent is not None

    def test_agent_requires_llm_provider(self):
        """ThumbelinaAgent should accept an LLM provider."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.llm_provider is mock_provider

    def test_agent_has_graph(self):
        """ThumbelinaAgent should have a compiled graph."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.graph is not None

    def test_agent_accepts_tools(self):
        """ThumbelinaAgent should accept optional tools."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_tool = MagicMock()
        mock_tool.name = "search"

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[mock_tool])

        assert len(agent.tools) == 1
        assert agent.tools[0].name == "search"

    def test_agent_default_empty_tools(self):
        """ThumbelinaAgent should default to empty tools list."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.tools == []

    @pytest.mark.asyncio
    async def test_agent_run_returns_string(self):
        """run() should return a string response."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello! How can I help?")

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        result = await agent.run("Hi")

        assert isinstance(result, str)
        assert result == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_agent_run_passes_user_message(self):
        """run() should create a HumanMessage from user input."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="response")

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        await agent.run("test input")

        # Verify the LLM was called with a HumanMessage
        call_args = mock_provider.chat_model.ainvoke.call_args[0][0]
        assert len(call_args) == 1
        assert isinstance(call_args[0], HumanMessage)
        assert call_args[0].content == "test input"

    @pytest.mark.asyncio
    async def test_agent_stream_yields_chunks(self):
        """stream() should yield typed content events."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello World")

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        chunks = []
        async for chunk in agent.stream("Hi"):
            chunks.append(chunk)

        # Should have received at least one chunk
        assert len(chunks) >= 1
        # All events are typed dicts; content events carry the response
        assert all(c["type"] == "content" for c in chunks)
        assert "".join(c["text"] for c in chunks) == "Hello World"

    @pytest.mark.asyncio
    async def test_agent_stream_yields_reasoning_events(self):
        """stream() should surface reasoning_content as reasoning events."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(
            content="The answer is 4.",
            additional_kwargs={"reasoning_content": "Let me think: 2+2..."},
        )

        agent = ThumbelinaAgent(llm_provider=mock_provider)
        events = []
        async for event in agent.stream("What is 2+2?"):
            events.append(event)

        reasoning = "".join(e["text"] for e in events if e["type"] == "reasoning")
        content = "".join(e["text"] for e in events if e["type"] == "content")
        assert reasoning == "Let me think: 2+2..."
        assert content == "The answer is 4."


class TestRolePrompt:
    """Tests for role persona prompt injection."""

    @pytest.mark.asyncio
    async def test_run_injects_role_prompt_first(self):
        """run() should prepend the role SystemMessage before the user input."""
        from langchain_core.messages import SystemMessage

        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.prompts.roles import get_role_prompt

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider, role="assistant")
        await agent.run("Hi")

        sent = mock_provider.chat_model.ainvoke.call_args[0][0]
        assert len(sent) == 2
        assert isinstance(sent[0], SystemMessage)
        assert sent[0].content == get_role_prompt("assistant")
        assert isinstance(sent[1], HumanMessage)

    @pytest.mark.asyncio
    async def test_stream_injects_role_prompt_first(self):
        """stream() should also prepend the role SystemMessage."""
        from langchain_core.messages import SystemMessage

        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider, role="coder")

        async for _ in agent.stream("Hi"):
            pass

        sent = mock_provider.chat_model.ainvoke.call_args[0][0]
        assert isinstance(sent[0], SystemMessage)
        assert "工程师" in sent[0].content

    def test_no_role_means_no_system_message(self):
        """Without a role, no prompt should be resolved."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.role is None
        assert agent.role_prompt is None

    def test_unknown_role_raises(self):
        """Constructing with a missing role file should fail fast."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        with pytest.raises(ValueError, match="Unknown role"):
            ThumbelinaAgent(llm_provider=mock_provider, role="ghost")

    def test_clone_propagates_role(self):
        """clone() should keep the same role and resolved prompt."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider, role="coder")
        cloned = agent.clone()

        assert cloned.role == "coder"
        assert cloned.role_prompt == agent.role_prompt


class TestGraphStructure:
    """Tests for the agent graph structure."""

    def test_graph_has_agent_node(self):
        """Graph should have an 'agent' node."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        # The graph should be compiled and have nodes
        assert agent.graph is not None

    def test_graph_has_tool_node_when_tools_provided(self):
        """Graph should have a 'tools' node when tools are provided."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_tool = MagicMock()
        mock_tool.name = "search"

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[mock_tool])

        # Graph should be built with tools
        assert agent.graph is not None


class TestAgentMemoryIntegration:
    """Tests for agent integration with memory system."""

    def test_agent_accepts_memory_manager(self):
        """ThumbelinaAgent should accept an optional memory manager."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()
        mock_memory = MagicMock(spec=MemoryManager)

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)

        assert agent.memory_manager is mock_memory

    def test_agent_default_no_memory(self):
        """ThumbelinaAgent should default to no memory manager."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent.memory_manager is None

    @pytest.mark.asyncio
    async def test_agent_creates_conversation_on_run(self):
        """Agent should create a conversation when memory is enabled."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello!")

        mock_memory = AsyncMock(spec=MemoryManager)
        mock_memory.create_conversation.return_value = "test-conversation-id"
        mock_memory.add_message = AsyncMock()

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)
        await agent.run("Hi")

        mock_memory.create_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_saves_user_message(self):
        """Agent should save user message to memory."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello!")

        mock_memory = AsyncMock(spec=MemoryManager)
        mock_memory.create_conversation.return_value = "test-conversation-id"
        mock_memory.add_message = AsyncMock()

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)
        await agent.run("Hi")

        # Verify user message was saved
        mock_memory.add_message.assert_any_call(
            conversation_id="test-conversation-id",
            role="user",
            content="Hi",
            reasoning_content=None,
        )

    @pytest.mark.asyncio
    async def test_agent_saves_assistant_response(self):
        """Agent should save assistant response to memory."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello!")

        mock_memory = AsyncMock(spec=MemoryManager)
        mock_memory.create_conversation.return_value = "test-conversation-id"
        mock_memory.add_message = AsyncMock()

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)
        await agent.run("Hi")

        # Verify assistant message was saved
        mock_memory.add_message.assert_any_call(
            conversation_id="test-conversation-id",
            role="assistant",
            content="Hello!",
            reasoning_content=None,
        )

    @pytest.mark.asyncio
    async def test_agent_does_not_save_without_memory(self):
        """Agent should not attempt to save messages without memory manager."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Hello!")

        agent = ThumbelinaAgent(llm_provider=mock_provider)

        # Should not raise any errors
        result = await agent.run("Hi")
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_agent_creates_conversation_only_once(self):
        """Agent should create conversation only once for multiple messages."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()
        mock_provider.chat_model.ainvoke.return_value = AIMessage(content="Response")

        mock_memory = AsyncMock(spec=MemoryManager)
        mock_memory.create_conversation.return_value = "test-conversation-id"
        mock_memory.add_message = AsyncMock()

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)
        await agent.run("First message")
        await agent.run("Second message")

        # create_conversation should only be called once
        mock_memory.create_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_stream_saves_user_message(self):
        """Agent should save user message during streaming."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()

        mock_memory = AsyncMock(spec=MemoryManager)
        mock_memory.create_conversation.return_value = "test-conversation-id"
        mock_memory.add_message = AsyncMock()

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)

        chunks = []
        async for chunk in agent.stream("Hi"):
            chunks.append(chunk)

        # Verify user message was saved
        mock_memory.add_message.assert_any_call(
            conversation_id="test-conversation-id",
            role="user",
            content="Hi",
            reasoning_content=None,
        )

    @pytest.mark.asyncio
    async def test_agent_stream_saves_assistant_response(self):
        """Agent should save assistant response during streaming."""
        from thumbelina.agent.graph import ThumbelinaAgent
        from thumbelina.memory.manager import MemoryManager

        mock_provider = _create_mock_provider()

        mock_memory = AsyncMock(spec=MemoryManager)
        mock_memory.create_conversation.return_value = "test-conversation-id"
        mock_memory.add_message = AsyncMock()

        agent = ThumbelinaAgent(llm_provider=mock_provider, memory_manager=mock_memory)

        chunks = []
        async for chunk in agent.stream("Hi"):
            chunks.append(chunk)

        # Verify assistant message was saved (should have 2 calls: user + assistant)
        assert mock_memory.add_message.call_count == 2
        assistant_call = mock_memory.add_message.call_args_list[1]
        assert assistant_call.kwargs["role"] == "assistant"
        assert assistant_call.kwargs["conversation_id"] == "test-conversation-id"


class TestAgentRAGIntegration:
    """Tests for agent RAG integration."""

    def test_rag_attributes_default_none(self):
        """RAG components should default to None."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        assert agent._rag_store_manager is None
        assert agent._rag_embedding_registry is None

    @pytest.mark.asyncio
    async def test_get_rag_context_returns_none_without_components(self):
        """Should return None when RAG components are not set."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        result = await agent._get_rag_context("test query", "0")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_rag_context_returns_none_with_empty_kb_id(self):
        """Should return None when knowledge_base_id is empty."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        result = await agent._get_rag_context("test query", "")
        assert result is None

    def test_clone_copies_rag_attributes(self):
        """clone() should copy RAG component references."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        agent = ThumbelinaAgent(llm_provider=mock_provider)

        mock_store_manager = MagicMock()
        mock_embedding_registry = MagicMock()
        agent._rag_store_manager = mock_store_manager
        agent._rag_embedding_registry = mock_embedding_registry

        cloned = agent.clone()

        assert cloned._rag_store_manager is mock_store_manager
        assert cloned._rag_embedding_registry is mock_embedding_registry

    def test_clone_does_not_duplicate_tool_names(self):
        """clone() must not re-add generated tools (LLM rejects dup names)."""
        from thumbelina.agent.graph import ThumbelinaAgent

        mock_provider = _create_mock_provider()
        mock_tool = MagicMock()
        mock_tool.name = "search"

        agent = ThumbelinaAgent(
            llm_provider=mock_provider,
            tools=[mock_tool],
            subagent_manager=MagicMock(),
            scheduler=MagicMock(),
            composition_engine=MagicMock(),
        )

        cloned = agent.clone()

        original_names = [t.name for t in agent.tools]
        cloned_names = [t.name for t in cloned.tools]
        assert len(cloned_names) == len(set(cloned_names)), (
            f"clone() produced duplicate tool names: {cloned_names}"
        )
        assert sorted(cloned_names) == sorted(original_names)


class TestToolBinding:
    """Tests that tools are bound to the LLM and executed in the loop."""

    @staticmethod
    def _make_echo_tool():
        from langchain_core.tools import tool

        @tool
        async def echo(text: str) -> str:
            """Echo the input text."""
            return text

        return echo

    @pytest.mark.asyncio
    async def test_model_is_bound_with_tools(self):
        """The chat model should receive the tool schemas via bind_tools."""
        from thumbelina.agent.graph import ThumbelinaAgent

        echo = self._make_echo_tool()

        bound_model = AsyncMock()
        bound_model.ainvoke.return_value = AIMessage(content="ok")
        mock_provider = MagicMock()
        mock_provider.chat_model = MagicMock()
        mock_provider.chat_model.bind_tools.return_value = bound_model

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[echo])
        result = await agent.run("hi")

        mock_provider.chat_model.bind_tools.assert_called_once()
        assert mock_provider.chat_model.bind_tools.call_args[0][0] == [echo]
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_tool_call_loop_executes_tool(self):
        """A tool call from the model should be executed and fed back."""
        from langchain_core.tools import tool

        from thumbelina.agent.graph import ThumbelinaAgent

        @tool
        async def read_file(path: str) -> str:
            """Read a file."""
            return "file-content"

        bound_model = AsyncMock()
        bound_model.ainvoke.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "a.txt"}}],
            ),
            AIMessage(content="The file contains: file-content"),
        ]
        mock_provider = MagicMock()
        mock_provider.chat_model = MagicMock()
        mock_provider.chat_model.bind_tools.return_value = bound_model

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[read_file])
        result = await agent.run("read a.txt")

        assert result == "The file contains: file-content"
        assert bound_model.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_bind_tools_not_supported_falls_back(self):
        """Models without tool support should fall back to plain chat."""
        from thumbelina.agent.graph import ThumbelinaAgent

        echo = self._make_echo_tool()

        mock_provider = MagicMock()
        mock_provider.chat_model = MagicMock()
        mock_provider.chat_model.bind_tools.side_effect = NotImplementedError
        mock_provider.chat_model.ainvoke = AsyncMock(return_value=AIMessage(content="plain"))

        agent = ThumbelinaAgent(llm_provider=mock_provider, tools=[echo])
        result = await agent.run("hi")

        assert result == "plain"
