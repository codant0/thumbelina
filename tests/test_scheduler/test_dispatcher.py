"""Tests for the DeliveryDispatcher (design §5.1/§8.2, review ruling).

Contract under the post-task-5 review ruling (which amends the brief):
COMPLETED/FAILED events are emitted *solely* by the scheduler, so the
dispatcher never subscribes to the bus and never emits on it — it either
returns a receipt string (the scheduler records it in the COMPLETED
payload ``result``) or raises (the scheduler catches and settles the
FAILED verdict with ``payload.error=str(exc)``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest

from thumbelina.channels.base import Channel
from thumbelina.scheduler.dispatcher import DeliveryDispatcher, DeliveryError
from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    TriggerKind,
)
from thumbelina.scheduler.scheduler import TaskScheduler

CONTENT = "早安简报已生成"


# ----------------------------------------------------------------------
# test doubles
# ----------------------------------------------------------------------


class FakeChannel(Channel):
    """Channel double recording send calls with controllable behaviour."""

    def __init__(
        self,
        *,
        last_user_id: str | None = "u-1",
        send_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._last_user_id = last_user_id
        self.send_error = send_error
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_message(
        self,
        user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any] | None:
        self.sent.append((user_id, text))
        if self.send_error is not None:
            raise self.send_error
        return {"ok": True}


class SpyBus(EventBus):
    """EventBus that records every emit call routed through it."""

    def __init__(self) -> None:
        super().__init__()
        self.emitted: list[TaskEvent] = []

    async def emit(self, event: TaskEvent) -> int:
        self.emitted.append(event)
        return await super().emit(event)


class WebPushSpy:
    """Async callable matching broadcast_chat_message's signature."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def __call__(self, message: dict[str, Any]) -> None:
        self.frames.append(message)
        if self.error is not None:
            raise self.error


def _task(**overrides: Any) -> ScheduledTask:
    """Build a minimal due task; overrides bypass enum typing on purpose."""
    values: dict[str, Any] = {
        "id": "task-1",
        "description": "morning briefing",
        "content": CONTENT,
        "channel": DeliveryChannel.WEB,
        "mode": "notify",
        "trigger": TriggerKind.ONCE,
    }
    values.update(overrides)
    return ScheduledTask(**values)


# ----------------------------------------------------------------------
# web delivery
# ----------------------------------------------------------------------


class TestWebDelivery:
    """web channel → web_push({"task_event": …}) per design §8.2."""

    async def test_pushes_completed_frame_with_design_shape(self):
        """The frame body matches §8.2 exactly and carries the receipt."""
        spy = WebPushSpy()
        dispatcher = DeliveryDispatcher(channels={}, web_push=spy)
        task = _task(trigger=TriggerKind.CRON, cron_expr="0 9 * * *")

        receipt = await dispatcher.on_due_task(task)

        assert isinstance(receipt, str) and receipt
        assert len(spy.frames) == 1
        frame = spy.frames[0]
        assert set(frame) == {"task_event"}
        body = frame["task_event"]
        assert set(body) == {
            "id",
            "type",
            "task_id",
            "fired_at",
            "trigger",
            "channel",
            "content",
            "payload",
        }
        assert body["type"] == "task.completed"
        assert body["task_id"] == task.id
        assert body["trigger"] == "cron"
        assert body["channel"] == "web"
        assert body["content"] == CONTENT
        assert isinstance(body["id"], str) and body["id"]
        fired_at = datetime.fromisoformat(body["fired_at"])
        assert abs((datetime.now() - fired_at).total_seconds()) < 5
        assert body["payload"]["result"] == receipt

    async def test_web_push_none_is_success_noop(self):
        """Without a wired web_push the delivery is a successful skip."""
        dispatcher = DeliveryDispatcher(channels={})

        receipt = await dispatcher.on_due_task(_task())

        assert isinstance(receipt, str) and receipt

    async def test_web_push_failure_propagates(self):
        """A raising web_push surfaces to the scheduler (→ FAILED)."""
        spy = WebPushSpy()
        spy.error = RuntimeError("ws closed")
        dispatcher = DeliveryDispatcher(channels={}, web_push=spy)

        with pytest.raises(RuntimeError, match="ws closed"):
            await dispatcher.on_due_task(_task())

    async def test_repeated_calls_deliver_independently(self):
        """No dedup: the same task due twice yields two distinct frames."""
        spy = WebPushSpy()
        dispatcher = DeliveryDispatcher(channels={}, web_push=spy)
        task = _task()

        await dispatcher.on_due_task(task)
        await dispatcher.on_due_task(task)

        assert len(spy.frames) == 2
        first, second = (f["task_event"] for f in spy.frames)
        assert first["id"] != second["id"]


# ----------------------------------------------------------------------
# wechat / qq delivery
# ----------------------------------------------------------------------


class TestImChannelDelivery:
    """IM channels → Channel.send_message to the channel's last user."""

    @pytest.mark.parametrize(
        ("name", "enum"),
        [("wechat", DeliveryChannel.WECHAT), ("qq", DeliveryChannel.QQ)],
    )
    async def test_sends_content_to_last_user_and_receipts(self, name, enum):
        """send_message gets (last_user_id, content); receipt names both."""
        channel = FakeChannel(last_user_id="wx-user-7")
        dispatcher = DeliveryDispatcher(channels={name: channel})

        receipt = await dispatcher.on_due_task(_task(channel=enum))

        assert channel.sent == [("wx-user-7", CONTENT)]
        assert name in receipt
        assert "wx-user-7" in receipt

    @pytest.mark.parametrize("name", ["wechat", "qq"])
    async def test_channel_missing_raises(self, name):
        """A channel absent from the injected table fails delivery."""
        dispatcher = DeliveryDispatcher(channels={})

        with pytest.raises(DeliveryError, match="channel not available"):
            await dispatcher.on_due_task(_task(channel=name))

    async def test_no_recent_user_raises(self):
        """A channel with no last_user_id fails before any send."""
        channel = FakeChannel(last_user_id=None)
        dispatcher = DeliveryDispatcher(channels={"wechat": channel})

        with pytest.raises(DeliveryError, match="no recent user on channel"):
            await dispatcher.on_due_task(_task(channel=DeliveryChannel.WECHAT))

        assert channel.sent == []

    async def test_send_message_exception_propagates_unchanged(self):
        """The channel's own exception is re-raised as-is, not wrapped."""
        boom = ValueError("wechat gateway down")
        channel = FakeChannel(last_user_id="u-1", send_error=boom)
        dispatcher = DeliveryDispatcher(channels={"wechat": channel})

        with pytest.raises(ValueError) as excinfo:  # noqa: PT011 - exact type matters
            await dispatcher.on_due_task(_task(channel=DeliveryChannel.WECHAT))

        assert excinfo.value is boom
        assert channel.sent == [("u-1", CONTENT)]  # attempt happened first


# ----------------------------------------------------------------------
# unsupported deliveries
# ----------------------------------------------------------------------


class TestUnsupportedDeliveries:
    """Reservations for prompt mode and out-of-enum channel values."""

    def test_delivery_error_is_runtime_error(self):
        """All dispatcher failures are RuntimeError subclasses (ruling)."""
        assert issubclass(DeliveryError, RuntimeError)

    async def test_prompt_mode_raises_not_supported(self):
        """mode != notify is a reserved failure (prompt lands later)."""
        spy = WebPushSpy()
        dispatcher = DeliveryDispatcher(channels={}, web_push=spy)

        with pytest.raises(DeliveryError, match="mode not supported yet"):
            await dispatcher.on_due_task(_task(mode="prompt"))

        assert spy.frames == []

    async def test_unknown_channel_value_raises(self):
        """An out-of-enum channel value fails with 'unknown channel'."""
        dispatcher = DeliveryDispatcher(channels={})

        with pytest.raises(DeliveryError, match="unknown channel"):
            await dispatcher.on_due_task(_task(channel="sms"))


# ----------------------------------------------------------------------
# double-emission regression (review ruling)
# ----------------------------------------------------------------------


class TestDispatcherNeverEmits:
    """The dispatcher must not emit COMPLETED/FAILED on the bus itself.

    The scheduler is the single emission authority; a dispatcher emit
    would double-fire every observer (bus hook + scheduler emit).
    """

    async def test_no_emit_on_success_paths(self):
        """Successful web and IM deliveries leave the injected bus silent."""
        spy_bus = SpyBus()
        dispatcher = DeliveryDispatcher(
            channels={"wechat": FakeChannel()},
            web_push=WebPushSpy(),
            bus=spy_bus,
        )

        await dispatcher.on_due_task(_task())
        await dispatcher.on_due_task(_task(channel=DeliveryChannel.WECHAT))

        assert spy_bus.emitted == []

    async def test_no_emit_on_failure_paths(self):
        """Failing deliveries raise instead of emitting a FAILED event."""
        spy_bus = SpyBus()
        dispatcher = DeliveryDispatcher(
            channels={}, web_push=None, bus=spy_bus
        )

        with pytest.raises(DeliveryError):
            await dispatcher.on_due_task(_task(channel=DeliveryChannel.QQ))

        with pytest.raises(DeliveryError):
            await dispatcher.on_due_task(_task(mode="prompt"))

        assert spy_bus.emitted == []


# ----------------------------------------------------------------------
# integration smoke: scheduler.start(on_due_task=dispatcher.on_due_task)
# ----------------------------------------------------------------------


async def _wait_for_status(
    scheduler: TaskScheduler, task_id: str, status: TaskStatus
) -> ScheduledTask:
    """Poll until the task reaches ``status`` (bounded)."""
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        task = await scheduler.get_task(task_id)
        if task is not None and task.status == status:
            return task
        if asyncio.get_running_loop().time() > deadline:
            seen = task.status.value if task is not None else "missing"
            raise AssertionError(f"task {task_id} never reached {status} (saw {seen})")
        await asyncio.sleep(0.05)


class TestSchedulerIntegration:
    """Full chain: once task due → dispatcher delivers → one COMPLETED."""

    async def test_once_task_delivers_and_completes_exactly_once(self):
        """Single delivery, single scheduler COMPLETED, silent dispatcher bus."""
        scheduler_bus = EventBus()
        due_events: list[TaskEvent] = []
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.DUE, due_events.append)
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

        dispatcher_bus = SpyBus()  # the dispatcher's own bus — must stay silent
        web_push = WebPushSpy()
        dispatcher = DeliveryDispatcher(
            channels={}, web_push=web_push, bus=dispatcher_bus
        )
        scheduler = TaskScheduler(bus=scheduler_bus)
        task = _task(id="once-1", scheduled_time=datetime.now() - timedelta(seconds=1))
        await scheduler.add_task(task)

        await scheduler.start(on_due_task=dispatcher.on_due_task)
        try:
            settled = await _wait_for_status(scheduler, "once-1", TaskStatus.COMPLETED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.COMPLETED
        assert len(web_push.frames) == 1  # delivered exactly once
        assert web_push.frames[0]["task_event"]["task_id"] == "once-1"
        assert len(due_events) == 1  # single trigger, no double-fire
        assert len(completed) == 1  # the scheduler is the sole emitter
        assert failed == []
        # The dispatcher's receipt reached the scheduler COMPLETED payload.
        frame_result = web_push.frames[0]["task_event"]["payload"]["result"]
        assert completed[0].payload["result"] == frame_result
        assert "duration_ms" in completed[0].payload
        # And the dispatcher never emitted anything itself.
        assert dispatcher_bus.emitted == []

    async def test_once_task_delivery_failure_ends_failed(self):
        """A raising dispatcher is settled by the scheduler as FAILED."""
        scheduler_bus = EventBus()
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

        # No web_push, no channels: the web task skips, so make it fail via
        # an unknown IM channel instead — "channel not available".
        dispatcher = DeliveryDispatcher(channels={})
        scheduler = TaskScheduler(bus=scheduler_bus)
        task = _task(
            id="once-2",
            channel="qq",
            scheduled_time=datetime.now() - timedelta(seconds=1),
        )
        await scheduler.add_task(task)

        await scheduler.start(on_due_task=dispatcher.on_due_task)
        try:
            settled = await _wait_for_status(scheduler, "once-2", TaskStatus.FAILED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.FAILED
        assert settled.error == "channel not available"
        assert completed == []
        assert len(failed) == 1
        assert failed[0].payload["error"] == "channel not available"
