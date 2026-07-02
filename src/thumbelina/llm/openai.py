"""OpenAI LLM provider backed by LangChain."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import LLMProvider, SpeedTestResult

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """LLM provider that delegates to OpenAI models via LangChain.

    Parameters
    ----------
    api_key:
        OpenAI API key.
    model:
        Model identifier (default ``"gpt-4o"``).
    base_url:
        Optional custom base URL for the OpenAI-compatible endpoint.
    **kwargs:
        Extra keyword arguments forwarded to ``ChatOpenAI``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        from langchain_openai import ChatOpenAI

        self._model_name = model
        self._api_key = api_key
        self._base_url = base_url
        self._model = ChatOpenAI(
            api_key=api_key,
            model=model,
            base_url=base_url,
            **kwargs,
        )

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
        """Return model IDs from the OpenAI /v1/models endpoint."""
        url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
        key = api_key or self._api_key
        headers: dict[str, str] = {"Authorization": f"Bearer {key}"} if key else {}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/models", headers=headers, timeout=30.0)
            response.raise_for_status()
            payload = response.json()

        return [m["id"] for m in payload.get("data", []) if "id" in m]

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        """Run a minimal streamed chat completion and measure latency."""
        url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
        key = api_key or self._api_key
        headers: dict[str, str] = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": True,
        }

        start = time.perf_counter()
        latency_ms: int | None = None
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                ) as response:
                    response.raise_for_status()
                    async for _ in response.aiter_text():
                        if latency_ms is None:
                            latency_ms = int((time.perf_counter() - start) * 1000)
                        break
            total_ms = int((time.perf_counter() - start) * 1000)
            return SpeedTestResult(
                reachable=True,
                latency_ms=latency_ms or total_ms,
                total_ms=total_ms,
                tested_at=datetime.now(timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI speed test failed: %s", exc)
            return SpeedTestResult(
                reachable=False,
                error=str(exc),
                tested_at=datetime.now(timezone.utc),
            )
