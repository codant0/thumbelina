"""Web search tool for the Thumbelina agent.

Backends:
- ``tavily``: official Tavily Search API (requires an API key). Returns
  LLM-friendly answer snippets alongside ranked results.
- ``duckduckgo``: no API key required, backed by the ``ddgs`` library
  (lazy-imported, mirroring the project's botpy/chromadb pattern).

The tool reads its configuration from a shared :class:`ToolsConfig`
object at call time, so provider/key changes take effect without
rebuilding the agent.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import tool

_MAX_RESULTS = 5
_RESULT_TOKEN_LIMIT = 4000  # 字符截断上限，防结果过大撑爆上下文


def _truncate(text: str) -> str:
    if len(text) > _RESULT_TOKEN_LIMIT:
        return text[:_RESULT_TOKEN_LIMIT] + "\n... (truncated)"
    return text


def _summaries(payload: dict[str, Any]) -> list[str]:
    """Return Tavily answer snippets (raw + llm) as a small list."""
    parts: list[str] = []
    for key in ("answer", "llm_response"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return parts


def _search_tavily(query: str, api_key: str) -> str:
    import httpx

    response = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": _MAX_RESULTS},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()

    sections: list[str] = _summaries(payload)
    results: list[str] = []
    for item in payload.get("results", [])[:_MAX_RESULTS]:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip()
        bullet = f"- {title}\n  {url}\n  {content}"
        results.append(bullet)
    if results:
        sections.append("Results:\n" + "\n".join(results))
    text = "\n\n".join(s for s in sections if s)
    return _truncate(text) if text else "No results found."


def _search_duckduckgo(query: str) -> str:
    try:
        from ddgs import DDGS  # type: ignore[import-not-found]
    except ImportError:
        return "Error: 'ddgs' is not installed. Run: pip install ddgs"

    try:
        hits = list(DDGS().text(query, max_results=_MAX_RESULTS))
    except Exception as exc:  # 网络错误 / 反爬限流等
        return f"Error searching DuckDuckGo: {exc}"

    if not hits:
        return "No results found."

    results: list[str] = []
    for item in hits:
        title = (item.get("title") or "").strip()
        url = (item.get("href") or item.get("url") or "").strip()
        body = (item.get("body") or "").strip()
        results.append(f"- {title}\n  {url}\n  {body}")
    return _truncate("\n".join(results))


def make_web_search_tool(search_config_provider: Any) -> Any:
    """Build the ``web_search`` tool bound to a live config object.

    Parameters
    ----------
    search_config_provider:
        Any object exposing ``.enabled``, ``.provider`` and ``.api_key``
        (typically a :class:`thumbelina.config.models.WebSearchConfig`).
        Attribute access happens at call time, so hot-swaps are picked up
        automatically.
    """

    @tool
    async def web_search(query: str) -> str:
        """Search the web for a query and return ranked results and summaries.

        Useful when you need up-to-date or external information beyond what
        you already know. Returns a concise list of titles, URLs and snippets.
        """
        if not search_config_provider.enabled:
            return "Web search is currently disabled."
        provider = search_config_provider.provider
        if provider == "tavily":
            api_key = search_config_provider.api_key
            if not api_key:
                return (
                    "Error: Tavily search requires an API key. Configure it in "
                    "Settings → Tools → Web Search."
                )
            try:
                return await asyncio.to_thread(_search_tavily, query, api_key)
            except Exception as exc:
                return f"Error searching Tavily: {exc}"
        # duckduckgo — no API key required
        try:
            return await asyncio.to_thread(_search_duckduckgo, query)
        except Exception as exc:
            return f"Error searching DuckDuckGo: {exc}"

    return web_search
