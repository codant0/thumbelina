"""Anthropic LLM provider backed by LangChain."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from thumbelina.llm.base import LLMProvider, _to_langchain_messages


class AnthropicProvider(LLMProvider):
    """LLM provider that delegates to Anthropic Claude models via LangChain.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    model:
        Model identifier (default ``"claude-sonnet-4-20250514"``).
    **kwargs:
        Extra keyword arguments forwarded to ``ChatAnthropic``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        **kwargs: Any,
    ) -> None:
        from langchain_anthropic import ChatAnthropic

        self._model_name = model
        self._model = ChatAnthropic(api_key=api_key, model=model, **kwargs)

    @property
    def model(self) -> str:
        return self._model_name

    async def chat(self, messages: list[dict[str, str]]) -> str:
        lc_messages = _to_langchain_messages(messages)
        response = await self._model.ainvoke(lc_messages)
        return str(response.content)

    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        lc_messages = _to_langchain_messages(messages)
        async for chunk in self._model.astream(lc_messages):
            yield str(chunk.content)
