"""OpenAI LLM provider backed by LangChain."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import LLMProvider, _to_langchain_messages


class OpenAIProvider(LLMProvider):
    """LLM provider that delegates to OpenAI models via LangChain.

    Parameters
    ----------
    api_key:
        OpenAI API key.
    model:
        Model identifier (default ``"gpt-4o"``).
    **kwargs:
        Extra keyword arguments forwarded to ``ChatOpenAI``.
    """

    def __init__(self, *, api_key: str, model: str = "gpt-4o", **kwargs: Any) -> None:
        from langchain_openai import ChatOpenAI

        self._model_name = model
        self._model = ChatOpenAI(api_key=api_key, model=model, **kwargs)

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def chat_model(self) -> BaseChatModel:
        return self._model

    async def chat(self, messages: list[dict[str, str]]) -> str:
        lc_messages = _to_langchain_messages(messages)
        response = await self._model.ainvoke(lc_messages)
        return str(response.content)

    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        lc_messages = _to_langchain_messages(messages)
        async for chunk in self._model.astream(lc_messages):
            yield str(chunk.content)
