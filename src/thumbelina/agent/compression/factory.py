"""Registry/factory mapping configuration names to compression strategies.

Strategies are registered by name; ``context.compress.strategy`` selects one
at agent construction time. Third-party strategies only need to subclass
:class:`~thumbelina.agent.compression.base.ContextCompressor` and call
:func:`register_compressor` — no other code changes required.
"""

from __future__ import annotations

import inspect
from typing import Any

from thumbelina.agent.compression.base import ContextCompressor

_REGISTRY: dict[str, type[ContextCompressor]] = {}


def register_compressor(name: str, compressor_cls: type[ContextCompressor]) -> None:
    """Register *compressor_cls* under configuration name *name*.

    Raises:
        ValueError: If *name* is already registered (prevents silently
            shadowing a built-in strategy).
    """
    if name in _REGISTRY:
        raise ValueError(f"Compression strategy {name!r} is already registered")
    _REGISTRY[name] = compressor_cls


def available_strategies() -> list[str]:
    """Sorted names of all registered strategies."""
    return sorted(_REGISTRY)


def create_compressor(name: str, **kwargs: Any) -> ContextCompressor:
    """Instantiate the strategy registered as *name*.

    Keyword arguments are forwarded to the strategy constructor, filtered
    down to the parameters it actually accepts — callers can pass the whole
    compress-config bundle without knowing each strategy's signature.

    Raises:
        ValueError: If *name* is not registered.
    """
    compressor_cls = _REGISTRY.get(name)
    if compressor_cls is None:
        raise ValueError(
            f"Unknown compression strategy {name!r}; available: {', '.join(available_strategies())}"
        )
    return compressor_cls(**_accepted_kwargs(compressor_cls, kwargs))


def _accepted_kwargs(cls: type[ContextCompressor], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter *kwargs* to the constructor parameters *cls* declares."""
    init = cls.__init__
    if init is object.__init__:
        return {}
    try:
        parameters = inspect.signature(init).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in parameters}


def _register_builtins() -> None:
    from thumbelina.agent.compression.full_summary import FullSummaryCompressor
    from thumbelina.agent.compression.sliding_window import SlidingWindowCompressor
    from thumbelina.agent.compression.summary_recent import SummaryRecentCompressor

    for cls in (SlidingWindowCompressor, FullSummaryCompressor, SummaryRecentCompressor):
        register_compressor(cls.name, cls)


_register_builtins()
