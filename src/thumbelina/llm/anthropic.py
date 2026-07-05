"""Anthropic LLM provider backed by LangChain."""

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

    async def test_connection(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> ConnectionTestResult:
        """Test connectivity to the Anthropic API endpoint."""
        url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        key = api_key or getattr(self, "_api_key", "")
        headers: dict[str, str] = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        tested_at = datetime.now(UTC)
        steps = ConnectionTestDetails(
            network=ConnectionTestStep(ok=False),
            auth=ConnectionTestStep(ok=False),
            service=ConnectionTestStep(ok=False),
        )

        # Level 1: network reachability
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                raise ValueError(f"Invalid URL: {url}")
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

        # Level 2: auth validity (GET /v1/messages?limit=1)
        auth_latency_ms: int | None = None
        try:
            t0 = time.perf_counter()
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{url}/messages?limit=1",
                    headers=headers,
                    timeout=10.0,
                )
            auth_latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code in (401, 403):
                steps.auth = ConnectionTestStep(
                    ok=False,
                    latency_ms=auth_latency_ms,
                    error=f"HTTP {resp.status_code}",
                )
                return ConnectionTestResult(
                    reachable=False,
                    network_reachable=True,
                    auth_valid=False,
                    error=f"Authentication failed: HTTP {resp.status_code}",
                    details=steps,
                    tested_at=tested_at,
                )
            # Anthropic may return 400 for missing body on GET /messages; that
            # is acceptable for auth checking — treat non-5xx as auth ok.
            if resp.status_code >= 500:
                resp.raise_for_status()
            steps.auth = ConnectionTestStep(ok=True, latency_ms=auth_latency_ms)
        except httpx.HTTPStatusError as exc:
            steps.auth = ConnectionTestStep(
                ok=False, latency_ms=auth_latency_ms, error=str(exc)
            )
            return ConnectionTestResult(
                reachable=False,
                network_reachable=True,
                auth_valid=False,
                error=str(exc),
                details=steps,
                tested_at=tested_at,
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            steps.auth = ConnectionTestStep(ok=False, error=error)
            return ConnectionTestResult(
                reachable=False,
                network_reachable=True,
                auth_valid=False,
                error=error,
                details=steps,
                tested_at=tested_at,
            )

        # Level 3: service availability (minimal messages request)
        try:
            t0 = time.perf_counter()
            payload = {
                "model": model or self._model_name,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{url}/messages",
                    headers=headers | {"Content-Type": "application/json"},
                    json=payload,
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
