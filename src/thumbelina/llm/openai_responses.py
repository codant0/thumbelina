"""OpenAI Responses API provider (``/v1/responses`` wire format)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import SpeedTestResult
from thumbelina.llm.openai import OpenAIProvider

logger = logging.getLogger(__name__)


class OpenAIResponsesProvider(OpenAIProvider):
    """LLM provider that talks the OpenAI Responses API.

    Shares the ``/v1/models`` listing with the Chat Completions channel;
    chat, connectivity probing and speed tests use the Responses wire
    format instead. Intended for the official OpenAI API and endpoints
    that explicitly implement ``/v1/responses`` — most OpenAI-compatible
    proxies only serve ``/v1/chat/completions``, so pick the channel
    per endpoint.

    Reasoning summaries are mapped by langchain-openai onto
    ``additional_kwargs["reasoning"]``, which the agent's reasoning
    extractor already consumes.
    """

    @property
    def chat_model(self) -> BaseChatModel:
        if self._chat_model is None:
            from langchain_openai import ChatOpenAI

            # 不透传父类的 MiniMax 私有 extra_body/reasoning_split；
            # Responses API 原生返回 usage，无需 stream_usage。
            kwargs: dict[str, Any] = {
                "api_key": self._api_key or None,
                "model": self._model_name,
                "base_url": self._base_url,
                "reasoning_effort": self.reasoning_effort,
                "use_responses_api": True,
            }
            kwargs.update(self._chat_model_kwargs)
            self._chat_model = ChatOpenAI(**kwargs)
        return self._chat_model

    async def _probe_chat(
        self, url: str, headers: dict[str, str], model_name: str
    ) -> httpx.Response:
        """Level 3 probe against ``/responses`` with the Responses payload."""
        payload = {
            "model": model_name,
            "input": "hi",
            "max_output_tokens": 1,
            "stream": False,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/responses",
                headers=headers | {"Content-Type": "application/json"},
                json=payload,
                timeout=15.0,
            )
        if resp.status_code in (404, 405):
            # 路径不存在与模型无关，直接给出可操作的错误提示。
            raise RuntimeError(
                f"Endpoint does not implement the Responses API (HTTP {resp.status_code}); "
                "use the OpenAI (Chat Completions) provider for this base URL."
            )
        return resp

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        """Run a minimal streamed Responses request and measure latency."""
        url = self._normalize_url(base_url)
        key = api_key or self._api_key
        headers: dict[str, str] = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": "hi",
            "max_output_tokens": 1,
            "stream": True,
        }

        start = time.perf_counter()
        latency_ms: int | None = None
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{url}/responses",
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
                tested_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI Responses speed test failed: %s", exc)
            return SpeedTestResult(
                reachable=False,
                error=str(exc),
                tested_at=datetime.now(UTC),
            )
