"""Factory for creating LLM providers by name."""

from __future__ import annotations

from typing import Any

from thumbelina.llm.base import LLMProvider

# Registry of provider name -> class (populated lazily to avoid import errors
# when optional SDKs are not installed).
_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {}


def _build_registry() -> dict[str, type[LLMProvider]]:
    """Build the provider registry, importing classes lazily."""
    from thumbelina.llm.anthropic import AnthropicProvider
    from thumbelina.llm.ollama import OllamaProvider
    from thumbelina.llm.openai import OpenAIProvider

    return {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
    }


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
    registry = _build_registry()
    key = name.lower()
    cls = registry.get(key)
    if cls is None:
        available = ", ".join(sorted(registry.keys()))
        raise ValueError(
            f"Unknown provider: {name!r}. Available providers: {available}"
        )
    return cls(**kwargs)


def list_providers() -> list[str]:
    """Return a sorted list of registered provider names."""
    registry = _build_registry()
    return sorted(registry.keys())
