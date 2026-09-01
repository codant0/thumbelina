"""Tests for the EventBus (design §3 event flow, §11 hook isolation)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from thumbelina.scheduler.events import EventBus, Hook
from thumbelina.scheduler.models import (
    DeliveryChannel,
    TaskEvent,
    TaskEventType,
    TriggerKind,
)


def _event(event_type: TaskEventType = TaskEventType.DUE) -> TaskEvent:
    """Build a minimal TaskEvent of the given type."""
    return TaskEvent(
        type=event_type,
        task_id="task-1",
        trigger=TriggerKind.ONCE,
        channel=DeliveryChannel.WEB,
        content="hello",
    )


def _recorder(calls: list[str], name: str) -> Hook:
    """An async hook appending its name to ``calls`` when awaited."""

    async def hook(event: TaskEvent) -> None:
        calls.append(name)

    return hook


class TestHookAlias:
    """Hook is the documented callable alias (brief interface)."""

    def test_alias_shape(self):
        """Hook aliases Callable[[TaskEvent], Awaitable[None]]."""
        assert Hook == Callable[[TaskEvent], Awaitable[None]]


class TestSubscribeAndEmit:
    """emit dispatches matching hooks and returns the dispatched count."""

    async def test_hook_receives_emitted_event(self):
        """The hook is awaited with the exact emitted event object."""
        bus = EventBus()
        received: list[TaskEvent] = []

        async def hook(event: TaskEvent) -> None:
            received.append(event)

        bus.subscribe(TaskEventType.DUE, hook)
        event = _event()

        assert await bus.emit(event) == 1
        assert received == [event]

    async def test_filters_by_event_type(self):
        """A hook subscribed to one type does not receive another type."""
        bus = EventBus()
        calls: list[str] = []
        bus.subscribe(TaskEventType.DUE, _recorder(calls, "due"))

        assert await bus.emit(_event(TaskEventType.COMPLETED)) == 0
        assert calls == []

        assert await bus.emit(_event(TaskEventType.DUE)) == 1
        assert calls == ["due"]

    async def test_emit_returns_number_of_dispatched_hooks(self):
        """emit returns how many hooks matched and completed."""
        bus = EventBus()
        calls: list[str] = []
        bus.subscribe(TaskEventType.DUE, _recorder(calls, "a"))
        bus.subscribe(TaskEventType.DUE, _recorder(calls, "b"))

        assert await bus.emit(_event()) == 2
        assert calls == ["a", "b"]


class TestRegistrationOrder:
    """Hooks fire in subscription order (design §3)."""

    async def test_hooks_awaited_in_registration_order(self):
        """Three hooks subscribed in sequence run in that sequence."""
        bus = EventBus()
        calls: list[str] = []
        for name in ("first", "second", "third"):
            bus.subscribe(TaskEventType.DUE, _recorder(calls, name))

        await bus.emit(_event())

        assert calls == ["first", "second", "third"]

    async def test_order_stable_across_emits(self):
        """The subscription order holds on every emit."""
        bus = EventBus()
        calls: list[str] = []
        bus.subscribe(TaskEventType.DUE, _recorder(calls, "a"))
        bus.subscribe(TaskEventType.DUE, _recorder(calls, "b"))

        await bus.emit(_event())
        await bus.emit(_event())

        assert calls == ["a", "b", "a", "b"]


class TestExceptionIsolation:
    """A raising hook is logged and skipped; other hooks still run (§11)."""

    async def test_first_hook_raising_second_still_receives(self):
        """The core isolation guarantee: later hooks run after a failure."""
        bus = EventBus()
        calls: list[str] = []

        async def bad_hook(event: TaskEvent) -> None:
            raise RuntimeError("hook exploded")

        bus.subscribe(TaskEventType.DUE, bad_hook)
        bus.subscribe(TaskEventType.DUE, _recorder(calls, "second"))

        event = _event()
        assert await bus.emit(event) == 1  # only the surviving hook counts
        assert calls == ["second"]

    async def test_exception_not_propagated_to_emitter(self):
        """emit swallows the hook exception — the caller never sees it."""

        async def bad_hook(event: TaskEvent) -> None:
            raise ValueError("boom")

        bus = EventBus()
        bus.subscribe(TaskEventType.DUE, bad_hook)

        assert await bus.emit(_event()) == 0  # must not raise

    async def test_raising_hook_logged_as_warning(self, caplog):
        """The failure is recorded via logger.warning on the events logger."""

        async def bad_hook(event: TaskEvent) -> None:
            raise RuntimeError("hook exploded")

        bus = EventBus()
        bus.subscribe(TaskEventType.DUE, bad_hook)

        with caplog.at_level(logging.WARNING, logger="thumbelina.scheduler.events"):
            await bus.emit(_event())

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records
        assert "hook exploded" in caplog.text

    async def test_later_hook_failure_does_not_block_earlier_ones_next_emit(self):
        """Isolation is positional: a tail failure also leaves others intact."""
        bus = EventBus()
        calls: list[str] = []

        async def bad_hook(event: TaskEvent) -> None:
            raise RuntimeError("tail exploded")

        bus.subscribe(TaskEventType.DUE, _recorder(calls, "head"))
        bus.subscribe(TaskEventType.DUE, bad_hook)

        assert await bus.emit(_event()) == 1
        assert calls == ["head"]


class TestUnsubscribe:
    """Unsubscribe (closure and method) stops delivery to the hook."""

    async def test_unsubscribe_closure_stops_delivery(self):
        """After calling the returned closure the hook no longer fires."""
        bus = EventBus()
        calls: list[str] = []
        unsubscribe = bus.subscribe(TaskEventType.DUE, _recorder(calls, "a"))

        unsubscribe()

        assert await bus.emit(_event()) == 0
        assert calls == []

    async def test_repeated_unsubscribe_closure_calls_are_safe(self):
        """Calling the closure more than once does not raise."""
        bus = EventBus()
        unsubscribe = bus.subscribe(TaskEventType.DUE, _recorder([], "a"))

        unsubscribe()
        unsubscribe()

    async def test_unsubscribe_method_removes_hook(self):
        """The explicit unsubscribe(event_type, hook) API also works."""
        bus = EventBus()
        calls: list[str] = []
        hook = _recorder(calls, "a")

        bus.subscribe(TaskEventType.DUE, hook)
        bus.unsubscribe(TaskEventType.DUE, hook)

        assert await bus.emit(_event()) == 0
        assert calls == []

    async def test_unsubscribe_is_scoped_to_event_type(self):
        """Unsubscribing one type leaves the same hook on another type."""
        bus = EventBus()
        due_calls: list[str] = []
        completed_calls: list[str] = []

        async def hook(event: TaskEvent) -> None:
            if event.type is TaskEventType.DUE:
                due_calls.append("hit")
            else:
                completed_calls.append("hit")

        unsubscribe = bus.subscribe(TaskEventType.DUE, hook)
        bus.subscribe(TaskEventType.COMPLETED, hook)

        unsubscribe()
        await bus.emit(_event(TaskEventType.DUE))
        await bus.emit(_event(TaskEventType.COMPLETED))

        assert due_calls == []
        assert completed_calls == ["hit"]

    async def test_unsubscribe_unknown_hook_is_noop(self):
        """Unsubscribing a never-registered hook does not raise."""
        bus = EventBus()

        bus.unsubscribe(TaskEventType.DUE, _recorder([], "never"))


class TestIdempotentSubscription:
    """Subscribing the same (event_type, hook) twice dispatches once."""

    async def test_duplicate_subscription_dispatches_once(self):
        bus = EventBus()
        calls: list[str] = []
        hook = _recorder(calls, "a")

        bus.subscribe(TaskEventType.DUE, hook)
        bus.subscribe(TaskEventType.DUE, hook)

        assert await bus.emit(_event()) == 1
        assert calls == ["a"]

    async def test_one_unsubscribe_after_duplicate_subscribe_removes_hook(self):
        """The hook is stored once, so a single unsubscribe clears it."""
        bus = EventBus()
        calls: list[str] = []
        hook = _recorder(calls, "a")

        bus.subscribe(TaskEventType.DUE, hook)
        bus.subscribe(TaskEventType.DUE, hook)
        bus.unsubscribe(TaskEventType.DUE, hook)

        assert await bus.emit(_event()) == 0
        assert calls == []


class TestEmptyBus:
    """Emitting with no subscribers is a silent zero."""

    async def test_emit_without_subscribers_returns_zero(self):
        bus = EventBus()

        assert await bus.emit(_event()) == 0

    async def test_emit_after_all_unsubscribed_returns_zero(self):
        bus = EventBus()
        unsubscribe = bus.subscribe(TaskEventType.DUE, _recorder([], "a"))

        unsubscribe()

        assert await bus.emit(_event()) == 0
