"""Factory for creating LLM providers by name."""

from __future__ import annotations

from typing import Any

from thumbelina.llm.base import LLMProvider

# Module-level registry — built once on first access.
_registry: dict[str, type[LLMProvider]] | None = None


def _get_registry() -> dict[str, type[LLMProvider]]:
    """Return the provider name → class mapping, initialising lazily."""
    global _registry
    if _registry is None:
        from thumbelina.llm.anthropic import AnthropicProvider
        from thumbelina.llm.ollama import OllamaProvider
        from thumbelina.llm.openai import OpenAIProvider

        _registry = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "ollama": OllamaProvider,
        }
    return _registry


def create_provider(name: str, **kwargs: Any) -> LLMProvider:
    """Create an LLM provider instance by name.

    Parameters
    ----------
    name:
        Provider identifier (``"openai"``, ``"anthropic"``, or ``"ollama"``).
        Case-insensitive.
    **kwargs:
        Keyword arguments forwarded to the provider constructor.

    Returns
    -------
    LLMProvider
        An initialised provider instance.

    Raises
    ------
    ValueError
        If *name* does not match any registered provider.
    """
    registry = _get_registry()
    key = name.lower()
    cls = registry.get(key)
    if cls is None:
        available = ", ".join(sorted(registry.keys()))
        raise ValueError(f"Unknown provider: {name!r}. Available providers: {available}")
    return cls(**kwargs)


def list_providers() -> list[str]:
    """Return a sorted list of registered provider names."""
    return sorted(_get_registry().keys())
