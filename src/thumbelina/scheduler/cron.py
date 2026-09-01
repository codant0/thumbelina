"""Cron trigger: a thin wrapper around :mod:`croniter`.

Semantics (design ``docs/plans/2026-08-30-event-timer-tasks-design.md`` §6):

- standard 5-field expressions (``分 时 日 月 周`` with ``* , - /``) plus the
  ``@hourly``/``@daily``/``@midnight``/``@weekly``/``@monthly``/``@yearly``
  descriptors; a seconds field is **not** supported (6/7-field input is
  rejected, even though croniter itself would accept it);
- times are **local naive** (the project-wide ``datetime.now()`` convention);
  DST transitions are deliberately not handled;
- :mod:`croniter` is an implementation detail: its exception hierarchy
  derives from :class:`ValueError`, so every failure surfaces to callers as
  :class:`ValueError` carrying the original expression;
- the dependency is declared in ``pyproject`` but the import is guarded:
  a missing :mod:`croniter` degrades cron scheduling (``validate_cron``
  rejects every expression with an install hint) instead of bricking the
  whole server at import time — one-shot tasks keep working. Mirrors the
  lazy-import convention used for ``botpy``/chromadb.
"""

from __future__ import annotations

from datetime import datetime

try:
    from croniter import croniter  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised via monkeypatched flag
    croniter = None

__all__ = ["CRONITER_AVAILABLE", "CronTrigger", "validate_cron"]

CRONITER_AVAILABLE = croniter is not None

_CRONITER_HINT = (
    "croniter is not installed; cron scheduling is disabled "
    "(install it, e.g. 'uv sync' or 'pip install -e .')"
)


def validate_cron(expr: str) -> str | None:
    """Check whether *expr* is a supported cron expression.

    Returns ``None`` when the expression is valid, otherwise a human
    readable error message quoting the offending expression.
    """
    if not CRONITER_AVAILABLE:
        return _CRONITER_HINT
    fields = expr.split()
    if not expr.strip().startswith("@") and len(fields) != 5:
        return (
            f"Invalid cron expression: {expr!r} (expected 5 fields "
            f"'min hour day month weekday', got {len(fields)})"
        )
    try:
        croniter(expr)
    except ValueError as exc:
        return f"Invalid cron expression: {expr!r} ({exc})"
    return None


class CronTrigger:
    """A parsed cron expression producing strictly-after fire times.

    Attributes
    ----------
    expr:
        The original expression, verbatim.
    """

    def __init__(self, expr: str) -> None:
        error = validate_cron(expr)
        if error is not None:
            raise ValueError(error)
        self.expr = expr

    def next_after(self, dt: datetime) -> datetime:
        """Return the first fire time strictly after *dt* (local naive).

        A *dt* landing exactly on a fire time is consumed: the result is
        the following occurrence.  Only reachable when :mod:`croniter` is
        installed — :meth:`__init__` already validated availability.
        """
        assert croniter is not None
        nxt: datetime = croniter(self.expr, dt).get_next(datetime)
        return nxt

    def describe(self) -> str:
        """Return the trigger's display form — the expression itself."""
        return self.expr
