"""Web request tools for the Thumbelina agent."""

from __future__ import annotations

from langchain_core.tools import tool

_MAX_CONTENT_SIZE = 50 * 1024  # 50KB


@tool
async def fetch_url(url: str) -> str:
    """Fetch the content of a URL and return the text. Limited to 50KB."""
    try:
        import httpx
    except ImportError:
        return "Error: httpx is not installed. Run: pip install httpx"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
            if len(text) > _MAX_CONTENT_SIZE:
                return text[:_MAX_CONTENT_SIZE] + "\n... (truncated at 50KB)"
            return text
    except httpx.TimeoutException:
        return f"Error: Request timed out after 10 seconds: {url}"
    except httpx.HTTPStatusError as exc:
        return f"Error: HTTP {exc.response.status_code} from {url}"
    except httpx.RequestError as exc:
        return f"Error fetching URL: {exc}"
