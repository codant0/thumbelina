"""In-process async event bus for task lifecycle events.

Implements design decision D4: a minimal async pub/sub registry that
decouples the scheduler core from its observers (event log, WebSocket
push).  Emission is awaited inline by the emitter (D5); a failing hook
is isolated — logged and skipped — so it can never break the dispatch
loop or the scheduler's main cycle (design §3, §11).

See ``docs/plans/2026-08-30-event-timer-tasks-design.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from thumbelina.scheduler.models import TaskEvent, TaskEventType

__all__ = ["EventBus", "Hook"]

logger = logging.getLogger(__name__)

Hook = Callable[[TaskEvent], Awaitable[None]]


class EventBus:
    """Async pub/sub registry dispatching :class:`TaskEvent` to hooks.

    Hooks are async callables subscribed per
    :class:`~thumbelina.scheduler.models.TaskEventType`.  Guarantees:

    - hooks are awaited in subscription order, inline by the emitter;
    - a hook exception is logged (``logger.warning``) and swallowed —
      later hooks still run and the error never reaches the emitter;
    - subscribing the same ``(event_type, hook)`` pair again is a no-op
      (no duplicate dispatch);
    - emitting with no subscribers returns ``0``.
    """

    def __init__(self) -> None:
        self._hooks: dict[TaskEventType, list[Hook]] = {}

    def subscribe(self, event_type: TaskEventType, hook: Hook) -> Callable[[], None]:
        """Register ``hook`` for ``event_type``; return an unsubscribe closure.

        Subscribing an already-registered pair is idempotent: the hook is
        stored once and dispatched once per matching emit.
        """
        hooks = self._hooks.setdefault(event_type, [])
        if hook not in hooks:
            hooks.append(hook)
        return lambda: self.unsubscribe(event_type, hook)

    def unsubscribe(self, event_type: TaskEventType, hook: Hook) -> None:
        """Remove ``hook`` from ``event_type``; a no-op when not subscribed."""
        hooks = self._hooks.get(event_type)
        if hooks is None:
            return
        try:
            hooks.remove(hook)
        except ValueError:
            pass
        if not hooks:
            del self._hooks[event_type]

    async def emit(self, event: TaskEvent) -> int:
        """Dispatch ``event`` to matching hooks in registration order.

        Returns the number of hooks that ran to completion.  A hook that
        raises is logged and skipped without affecting the other hooks.
        """
        hooks = self._hooks.get(event.type)
        if not hooks:
            return 0
        dispatched = 0
        for hook in tuple(hooks):  # snapshot: a hook may unsubscribe mid-dispatch
            try:
                await hook(event)
            except Exception:
                logger.warning("Event hook %r raised on %s", hook, event.type.value, exc_info=True)
            else:
                dispatched += 1
        return dispatched
