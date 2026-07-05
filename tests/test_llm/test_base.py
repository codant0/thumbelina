"""Tests for thumbelina.llm.base module."""

from __future__ import annotations

import inspect

import pytest

from thumbelina.llm.base import LLMProvider, SpeedTestResult


class TestLLMProviderABC:
    """Tests for the LLMProvider abstract base class."""

    def test_cannot_instantiate_directly(self):
        """LLMProvider is abstract and cannot be instantiated."""
        from thumbelina.llm.base import LLMProvider

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            LLMProvider()  # type: ignore[abstract]

    def test_must_implement_chat(self):
        """Subclass must implement chat() to be instantiated."""

        from thumbelina.llm.base import LLMProvider

        class IncompleteProvider(LLMProvider):
            async def stream(self, messages):
                yield ""

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteProvider()  # type: ignore[abstract]

    def test_must_implement_stream(self):
        """Subclass must implement stream() to be instantiated."""

        from thumbelina.llm.base import LLMProvider

        class IncompleteProvider(LLMProvider):
            async def chat(self, messages):
                return ""

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteProvider()  # type: ignore[abstract]

    def test_complete_subclass_can_instantiate(self):
        """A subclass implementing all abstract methods can be instantiated."""

        from unittest.mock import MagicMock

        from thumbelina.llm.base import LLMProvider

        class CompleteProvider(LLMProvider):
            @property
            def model(self) -> str:
                return "test-model"

            @property
            def chat_model(self):
                return MagicMock()

            async def chat(self, messages):
                return "response"

            async def stream(self, messages):
                yield "chunk"

            async def list_models(self, *, base_url=None, api_key=None):
                return []

            async def speed_test(self, model, *, base_url=None, api_key=None):
                return SpeedTestResult(reachable=True)

            async def test_connection(self, *, base_url=None, api_key=None, model=None):
                from thumbelina.llm.base import ConnectionTestResult

                return ConnectionTestResult(reachable=True)

        provider = CompleteProvider()
        assert isinstance(provider, LLMProvider)

    def test_chat_is_coroutine(self):
        """chat() should be an async method."""
        from thumbelina.llm.base import LLMProvider

        assert inspect.iscoroutinefunction(LLMProvider.chat)

    def test_stream_returns_async_generator(self):
        """stream() should be an async generator function."""
        from thumbelina.llm.base import LLMProvider

        assert inspect.isasyncgenfunction(LLMProvider.stream)

    def test_chat_accepts_message_list(self):
        """chat() signature should accept a list of dicts."""

        from thumbelina.llm.base import LLMProvider

        sig = inspect.signature(LLMProvider.chat)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "messages" in params

    def test_stream_accepts_message_list(self):
        """stream() signature should accept a list of dicts."""

        from thumbelina.llm.base import LLMProvider

        sig = inspect.signature(LLMProvider.stream)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "messages" in params


class TestMessageConversion:
    """Tests for the _to_langchain_messages helper."""

    def test_convert_user_message(self):
        from langchain_core.messages import HumanMessage

        from thumbelina.llm.base import LLMProvider

        result = LLMProvider._to_langchain_messages([{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)
        assert result[0].content == "hello"

    def test_convert_assistant_message(self):
        from langchain_core.messages import AIMessage

        from thumbelina.llm.base import LLMProvider

        result = LLMProvider._to_langchain_messages([{"role": "assistant", "content": "hi"}])
        assert len(result) == 1
        assert isinstance(result[0], AIMessage)
        assert result[0].content == "hi"

    def test_convert_system_message(self):
        from langchain_core.messages import SystemMessage

        from thumbelina.llm.base import LLMProvider

        result = LLMProvider._to_langchain_messages([{"role": "system", "content": "behave"}])
        assert len(result) == 1
        assert isinstance(result[0], SystemMessage)
        assert result[0].content == "behave"

    def test_convert_multiple_messages(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from thumbelina.llm.base import LLMProvider

        messages = [
            {"role": "system", "content": "behave"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = LLMProvider._to_langchain_messages(messages)
        assert len(result) == 3
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], HumanMessage)
        assert isinstance(result[2], AIMessage)

    def test_unknown_role_raises(self):
        from thumbelina.llm.base import LLMProvider

        with pytest.raises(ValueError, match="Unknown role"):
            LLMProvider._to_langchain_messages([{"role": "ghost", "content": "boo"}])


def test_speed_test_result_has_reachable_field():
    result = SpeedTestResult(reachable=True, latency_ms=123, total_ms=456)
    assert result.reachable is True
    assert result.latency_ms == 123
    assert result.total_ms == 456


def test_provider_has_list_models_and_speed_test_methods():
    assert hasattr(LLMProvider, "list_models")
    assert hasattr(LLMProvider, "speed_test")
    assert hasattr(LLMProvider, "test_connection")
