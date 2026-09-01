"""Anthropic LLM provider backed by LangChain."""

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


class AnthropicProvider(LLMProvider):
    """LLM provider that delegates to Anthropic Claude models via LangChain.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    model:
        Model identifier (default ``"claude-sonnet-4-20250514"``).
    base_url:
        Optional custom base URL for Anthropic-compatible endpoints. Both
        conventions (with or without a ``/v1`` suffix) are accepted and
        normalised internally — see :meth:`_normalize_urls`.
    **kwargs:
        Extra keyword arguments forwarded to ``ChatAnthropic``.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "claude-sonnet-4-20250514",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._model_name = model
        self._api_key = api_key
        self._base_url = base_url
        self._chat_model_kwargs = kwargs
        self._chat_model: BaseChatModel | None = None

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def chat_model(self) -> BaseChatModel:
        if self._chat_model is None:
            from langchain_anthropic import ChatAnthropic

            kwargs: dict[str, Any] = {
                "api_key": self._api_key or None,
                "model": self._model_name,
            }
            if self._base_url:
                # The anthropic SDK string-concatenates its request path onto
                # base_url, so the chat client must not receive a /v1 suffix.
                kwargs["base_url"] = self._normalize_urls(self._base_url)[1]
            kwargs.update(self._chat_model_kwargs)
            self._chat_model = ChatAnthropic(**kwargs)
        return self._chat_model

    @staticmethod
    def _normalize_urls(base_url: str | None) -> tuple[str, str]:
        """Resolve a user-supplied base URL into ``(api_url, sdk_base_url)``.

        The anthropic SDK concatenates its request path (``v1/messages``)
        onto the configured base URL, so the chat client must point at the
        host **without** a ``/v1`` suffix, while the raw HTTP probes need
        the full ``/v1``-prefixed API root. Either convention is accepted:

        - empty path        → ``api_url`` gains ``/v1``, sdk stays as-is
        - path ends ``/v1`` → ``api_url`` keeps it, sdk drops it
        - any other path    → both kept verbatim (proxy-specific mounts)
        """
        url = (base_url or "https://api.anthropic.com").rstrip("/")
        path = urllib.parse.urlparse(url).path.rstrip("/")
        if not path:
            return f"{url}/v1", url
        if path.endswith("/v1"):
            return url, url[: -len("/v1")]
        return url, url

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        """Return model IDs from the Anthropic /v1/models endpoint."""
        url, _ = self._normalize_urls(base_url or self._base_url)
        key = api_key or self._api_key
        headers: dict[str, str] = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{url}/models", headers=headers, timeout=30.0)
                response.raise_for_status()
                payload = response.json()
            return [m["id"] for m in payload.get("data", []) if "id" in m]
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403, 404, 405):
                logger.warning(
                    "Model listing not supported at %s (HTTP %d). Falling back to empty list.",
                    url,
                    e.response.status_code,
                )
                return []
            raise
        except Exception:
            logger.warning("Failed to fetch models from %s", url, exc_info=True)
            return []

    async def speed_test(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> SpeedTestResult:
        """Run a minimal streamed messages request and measure latency."""
        url, _ = self._normalize_urls(base_url or self._base_url)
        key = api_key or self._api_key
        headers: dict[str, str] = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }

        start = time.perf_counter()
        latency_ms: int | None = None
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{url}/messages",
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
            logger.warning("Anthropic speed test failed: %s", exc)
            return SpeedTestResult(
                reachable=False,
                error=str(exc),
                tested_at=datetime.now(UTC),
            )

    async def test_connection(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> ConnectionTestResult:
        """Test connectivity to the Anthropic API endpoint."""
        url, _ = self._normalize_urls(base_url or self._base_url)
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
            steps.auth = ConnectionTestStep(ok=False, latency_ms=auth_latency_ms, error=str(exc))
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
