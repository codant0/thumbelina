"""把配置名映射到压缩策略的注册表/工厂。

策略按名称注册；``context.compress.strategy`` 在 agent 构造时选定其一。
第三方策略只需继承
:class:`~thumbelina.agent.compression.base.ContextCompressor` 并调用
:func:`register_compressor` —— 无需其他代码改动。
"""

from __future__ import annotations

import inspect
from typing import Any

from thumbelina.agent.compression.base import ContextCompressor

_REGISTRY: dict[str, type[ContextCompressor]] = {}


def register_compressor(name: str, compressor_cls: type[ContextCompressor]) -> None:
    """将 *compressor_cls* 注册到配置名 *name* 之下。

    Raises:
        ValueError: 如果 *name* 已被注册（防止悄悄遮蔽内置策略）。
    """
    if name in _REGISTRY:
        raise ValueError(f"Compression strategy {name!r} is already registered")
    _REGISTRY[name] = compressor_cls


def available_strategies() -> list[str]:
    """所有已注册策略的名称（排序后）。"""
    return sorted(_REGISTRY)


def create_compressor(name: str, **kwargs: Any) -> ContextCompressor:
    """实例化以 *name* 注册的策略。

    关键字参数会转发给策略构造函数，并过滤为其实际接受的参数 ——
    调用方可以传入整个 compress 配置包，而无需了解每个策略的签名。

    Raises:
        ValueError: 如果 *name* 未注册。
    """
    compressor_cls = _REGISTRY.get(name)
    if compressor_cls is None:
        raise ValueError(
            f"Unknown compression strategy {name!r}; available: {', '.join(available_strategies())}"
        )
    return compressor_cls(**_accepted_kwargs(compressor_cls, kwargs))


def _accepted_kwargs(cls: type[ContextCompressor], kwargs: dict[str, Any]) -> dict[str, Any]:
    """将 *kwargs* 过滤为 *cls* 构造函数声明的参数。"""
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
