"""Anthropic LLM provider backed by LangChain."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import LLMProvider, SpeedTestResult


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

    @property
    def chat_model(self) -> BaseChatModel:
        return self._model

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        raise NotImplementedError("Anthropic does not support model listing yet.")

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        raise NotImplementedError("Anthropic does not support speed tests yet.")
