"""Ollama LLM provider for local models, backed by LangChain."""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from thumbelina.llm.base import (
    ConnectionTestDetails,
    ConnectionTestResult,
    ConnectionTestStep,
    LLMProvider,
    SpeedTestResult,
)


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

    async def test_connection(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> ConnectionTestResult:
        """Test connectivity to a local Ollama server."""
        url = (base_url or self._base_url or "http://localhost:11434").rstrip("/")
        tested_at = datetime.now(UTC)
        steps = ConnectionTestDetails(
            network=ConnectionTestStep(ok=False),
            auth=ConnectionTestStep(ok=False),
            service=ConnectionTestStep(ok=False),
        )

        # Level 1: network reachability
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 11434
            t0 = time.perf_counter()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0
            )
            writer.close()
            await writer.wait_closed()
            steps.network = ConnectionTestStep(
                ok=True, latency_ms=int((time.perf_counter() - t0) * 1000)
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            steps.network = ConnectionTestStep(ok=False, error=error)
            return ConnectionTestResult(
                reachable=False,
                network_reachable=False,
                error=error,
                details=steps,
                tested_at=tested_at,
            )

        # Level 2: Ollama has no api-key auth — mark as skipped/ok.
        steps.auth = ConnectionTestStep(ok=True, latency_ms=0)

        # Level 3: service availability (GET /api/tags)
        try:
            t0 = time.perf_counter()
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{url}/api/tags",
                    timeout=15.0,
                )
                resp.raise_for_status()
            total_latency = int((time.perf_counter() - t0) * 1000)
            steps.service = ConnectionTestStep(ok=True, latency_ms=total_latency)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            steps.service = ConnectionTestStep(ok=False, error=error)
            return ConnectionTestResult(
                reachable=False,
                network_reachable=True,
                auth_valid=True,
                error=error,
                details=steps,
                tested_at=tested_at,
            )

        return ConnectionTestResult(
            reachable=True,
            network_reachable=True,
            auth_valid=True,
            service_available=True,
            latency_ms=total_latency,
            details=steps,
            tested_at=tested_at,
        )
