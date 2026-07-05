"""OpenAI LLM provider backed by LangChain."""

from __future__ import annotations

import asyncio
import logging
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

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{url}/models", headers=headers, timeout=30.0)
                response.raise_for_status()
                payload = response.json()
            return [m["id"] for m in payload.get("data", []) if "id" in m]
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403, 404):
                logger.warning(
                    "Model listing not supported at %s (HTTP %d). "
                    "Falling back to empty list.",
                    url,
                    e.response.status_code,
                )
                return []
            raise
        except Exception:
            logger.warning("Failed to fetch models from %s", url, exc_info=True)
            return []

    async def test_connection(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> ConnectionTestResult:
        """Test connectivity to an OpenAI-compatible endpoint.

        Performs a three-level check: network reachability, auth validity,
        and service availability. Returns a detailed result with per-step
        timing and errors.
        """
        url = (base_url or self._base_url or "https://api.openai.com/v1").rstrip("/")
        key = api_key or self._api_key
        headers: dict[str, str] = {"Authorization": f"Bearer {key}"} if key else {}
        tested_at = datetime.now(UTC)
        steps = ConnectionTestDetails(
            network=ConnectionTestStep(ok=False),
            auth=ConnectionTestStep(ok=False),
            service=ConnectionTestStep(ok=False),
        )

        # Level 1: network reachability (TCP handshake)
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

        # Level 2: auth validity (GET /models)
        auth_latency_ms: int | None = None
        try:
            t0 = time.perf_counter()
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{url}/models", headers=headers, timeout=10.0
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

        # Level 3: service availability (minimal chat completion)
        try:
            t0 = time.perf_counter()
            payload = {
                "model": model or self._model_name or "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "stream": False,
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{url}/chat/completions",
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
                tested_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI speed test failed: %s", exc)
            return SpeedTestResult(
                reachable=False,
                error=str(exc),
                tested_at=datetime.now(UTC),
            )
