"""Ollama LLM provider for local models, backed by LangChain."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import LLMProvider, SpeedTestResult


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

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        raise NotImplementedError("Ollama does not support model listing yet.")

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        raise NotImplementedError("Ollama does not support speed tests yet.")
