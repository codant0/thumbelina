"""Ollama LLM provider for local models, backed by LangChain."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import LLMProvider, _to_langchain_messages


class OllamaProvider(LLMProvider):
    """LLM provider that delegates to a local Ollama server via LangChain.

    Parameters
    ----------
    model:
        Model identifier (default ``"llama3"``).
    base_url:
        Ollama server URL (default ``"http://localhost:11434"``).
    **kwargs:
        Extra keyword arguments forwarded to ``ChatOllama``.
    """

    def __init__(
        self,
        *,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        **kwargs: Any,
    ) -> None:
        from langchain_ollama import ChatOllama

        self._model_name = model
        self._base_url = base_url
        self._model = ChatOllama(model=model, base_url=base_url, **kwargs)

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def chat_model(self) -> BaseChatModel:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    async def chat(self, messages: list[dict[str, str]]) -> str:
        lc_messages = _to_langchain_messages(messages)
        response = await self._model.ainvoke(lc_messages)
        return str(response.content)

    async def stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
        lc_messages = _to_langchain_messages(messages)
        async for chunk in self._model.astream(lc_messages):
            yield str(chunk.content)
