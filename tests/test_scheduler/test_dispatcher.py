"""Tests for the DeliveryDispatcher (design §5.1, review rulings).

Contracts under the review rulings (which amend the original brief):

- Task-5 ruling: COMPLETED/FAILED events are emitted *solely* by the
  scheduler, so the dispatcher never subscribes to the bus and never
  emits on it — it either returns a receipt string (the scheduler records
  it in the COMPLETED payload ``result``) or raises (the scheduler
  catches and settles the FAILED verdict with ``payload.error=str(exc)``).
- T7-R1 ruling (fix round 1): **web 渠道交付 = 事件管线本身** — for
  ``channel=web`` the dispatcher only returns a receipt; the T8-assembled
  WebPushHook observer broadcasts each event (including the scheduler's
  COMPLETED event) to the frontend exactly once.  There is no
  ``web_push`` injection point and the dispatcher builds no frames.
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
WEB_RECEIPT = "delivered via web event pipeline"


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
# web delivery (= the event pipeline itself, T7-R1)
# ----------------------------------------------------------------------


class TestWebDelivery:
    """web channel → receipt only; the event pipeline does the pushing."""

    async def test_web_delivery_returns_receipt_without_any_push(self):
        """A web task succeeds instantly: receipt + zero direct pushes."""
        spy_bus = SpyBus()  # no injection point exists — spy bus stays clean
        dispatcher = DeliveryDispatcher(channels={}, bus=spy_bus)
        task = _task()

        receipt = await dispatcher.on_due_task(task)

        assert isinstance(receipt, str) and receipt
        assert spy_bus.emitted == []

    def test_constructor_no_longer_accepts_web_push(self):
        """T7-R1 removed the web_push injection point — enforce mechanically."""
        with pytest.raises(TypeError):
            DeliveryDispatcher(channels={}, web_push=lambda m: None)  # type: ignore[call-arg]

    async def test_repeated_web_calls_are_pure_receipts(self):
        """No dedup needed and no side effects: two calls, two receipts."""
        spy_bus = SpyBus()
        dispatcher = DeliveryDispatcher(channels={}, bus=spy_bus)
        task = _task()

        first = await dispatcher.on_due_task(task)
        second = await dispatcher.on_due_task(task)

        assert first == second == WEB_RECEIPT
        assert spy_bus.emitted == []


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

    async def test_repeated_calls_deliver_independently(self):
        """No dedup: the same task due twice yields two independent sends."""
        channel = FakeChannel(last_user_id="u-1")
        dispatcher = DeliveryDispatcher(channels={"wechat": channel})
        task = _task(channel=DeliveryChannel.WECHAT)

        await dispatcher.on_due_task(task)
        await dispatcher.on_due_task(task)

        assert len(channel.sent) == 2


# ----------------------------------------------------------------------
# Task 12: on_prompt_task — 编排 prompt_runner + 频道副本 (§5.4)
# ----------------------------------------------------------------------


REPLY = "早安简报已生成（prompt 回复）"


class TestPromptModeDelivery:
    """dispatcher.on_prompt_task: mode 校验 → prompt_runner → 频道副本（wechat/qq
    发送的是**回复**）→ 返回 reply。dispatcher 永不 emit（与 notify 同裁定）。"""

    async def test_without_runner_raises(self):
        dispatcher = DeliveryDispatcher(channels={})

        with pytest.raises(DeliveryError, match="prompt runner not configured"):
            await dispatcher.on_prompt_task(_task(mode="prompt"))

    async def test_notify_mode_raises(self):
        async def runner(task: ScheduledTask) -> str:
            return "unused"

        dispatcher = DeliveryDispatcher(channels={}, prompt_runner=runner)

        with pytest.raises(DeliveryError, match="mode not supported"):
            await dispatcher.on_prompt_task(_task(mode="notify"))

    async def test_web_returns_reply_without_any_copy(self):
        """web prompt task: reply returned, zero channel sends, bus silent."""
        spy_bus = SpyBus()
        received: list[str] = []

        async def runner(task: ScheduledTask) -> str:
            received.append(task.id)
            return REPLY

        dispatcher = DeliveryDispatcher(channels={}, bus=spy_bus, prompt_runner=runner)

        reply = await dispatcher.on_prompt_task(_task(mode="prompt"))

        assert reply == REPLY
        assert received == ["task-1"]
        assert spy_bus.emitted == []

    @pytest.mark.parametrize(
        ("name", "enum"),
        [("wechat", DeliveryChannel.WECHAT), ("qq", DeliveryChannel.QQ)],
    )
    async def test_im_channel_sends_reply(self, name, enum):
        """IM prompt task: the REPLY (not task.content) goes out via send_message."""
        channel = FakeChannel(last_user_id="wx-user-7")
        sent_tasks: list[str] = []

        async def runner(task: ScheduledTask) -> str:
            sent_tasks.append(task.id)
            return REPLY

        dispatcher = DeliveryDispatcher(channels={name: channel}, prompt_runner=runner)

        reply = await dispatcher.on_prompt_task(_task(mode="prompt", channel=enum))

        assert reply == REPLY
        assert sent_tasks == ["task-1"]
        assert channel.sent == [("wx-user-7", REPLY)]  # the reply, not CONTENT

    async def test_missing_channel_raises(self):
        async def runner(task: ScheduledTask) -> str:
            return REPLY

        dispatcher = DeliveryDispatcher(channels={}, prompt_runner=runner)

        with pytest.raises(DeliveryError, match="channel not available"):
            await dispatcher.on_prompt_task(_task(mode="prompt", channel=DeliveryChannel.WECHAT))

    async def test_no_recent_user_raises(self):
        channel = FakeChannel(last_user_id=None)

        async def runner(task: ScheduledTask) -> str:
            return REPLY

        dispatcher = DeliveryDispatcher(channels={"wechat": channel}, prompt_runner=runner)

        with pytest.raises(DeliveryError, match="no recent user on channel"):
            await dispatcher.on_prompt_task(_task(mode="prompt", channel=DeliveryChannel.WECHAT))

        assert channel.sent == []

    async def test_runner_exception_propagates_unchanged(self):
        async def boom(task: ScheduledTask) -> str:
            raise ValueError("model down")

        dispatcher = DeliveryDispatcher(channels={}, prompt_runner=boom)

        with pytest.raises(ValueError, match="model down"):  # noqa: PT011 - exact type matters
            await dispatcher.on_prompt_task(_task(mode="prompt"))

    async def test_unknown_channel_value_raises(self):
        async def runner(task: ScheduledTask) -> str:
            return REPLY

        dispatcher = DeliveryDispatcher(channels={}, prompt_runner=runner)

        with pytest.raises(DeliveryError, match="unknown channel: sms"):
            await dispatcher.on_prompt_task(_task(mode="prompt", channel="sms"))

    async def test_no_emit_on_prompt_paths(self):
        """Success and failure prompt deliveries leave the injected bus silent."""
        spy_bus = SpyBus()
        channel = FakeChannel(last_user_id="u-1")

        async def runner(task: ScheduledTask) -> str:
            return REPLY

        dispatcher = DeliveryDispatcher(
            channels={"wechat": channel}, bus=spy_bus, prompt_runner=runner
        )

        await dispatcher.on_prompt_task(_task(mode="prompt"))
        await dispatcher.on_prompt_task(_task(mode="prompt", channel=DeliveryChannel.WECHAT))

        with pytest.raises(DeliveryError):
            await dispatcher.on_prompt_task(_task(mode="notify"))

        assert spy_bus.emitted == []


class _PromptRunner:
    """A prompt_runner stub that records the task it received."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: list[str] = []

    async def __call__(self, task: ScheduledTask) -> str:
        self.seen.append(task.id)
        return self.reply


# ----------------------------------------------------------------------
# unsupported deliveries
# ----------------------------------------------------------------------


class TestUnsupportedDeliveries:
    """Reservations for prompt mode and out-of-enum channel values."""

    def test_delivery_error_is_runtime_error(self):
        """All dispatcher failures are RuntimeError subclasses (ruling)."""
        assert issubclass(DeliveryError, RuntimeError)

    async def test_prompt_mode_raises_not_supported(self):
        """on_due_task does not handle prompt tasks — those go through the
        dedicated on_prompt_task entry (design §5.4)."""
        dispatcher = DeliveryDispatcher(channels={})

        with pytest.raises(DeliveryError, match="mode not supported"):
            await dispatcher.on_due_task(_task(mode="prompt"))

    async def test_unknown_channel_value_raises_with_actual_value(self):
        """An out-of-enum channel value fails, naming the offending value."""
        dispatcher = DeliveryDispatcher(channels={})

        with pytest.raises(DeliveryError, match="unknown channel: sms"):
            await dispatcher.on_due_task(_task(channel="sms"))


# ----------------------------------------------------------------------
# double-emission regression (task-5 review ruling)
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
            bus=spy_bus,
        )

        await dispatcher.on_due_task(_task())
        await dispatcher.on_due_task(_task(channel=DeliveryChannel.WECHAT))

        assert spy_bus.emitted == []

    async def test_no_emit_on_failure_paths(self):
        """Failing deliveries raise instead of emitting a FAILED event."""
        spy_bus = SpyBus()
        dispatcher = DeliveryDispatcher(channels={}, bus=spy_bus)

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

    async def test_web_task_full_chain_single_completed_event(self):
        """Web task: 0 direct frames (no injection point), 1 COMPLETED.

        The frontend frame comes from the T8 WebPushHook observer that
        broadcasts this single COMPLETED event — the dispatcher's role is
        only the receipt (recorded as payload.result by the scheduler).
        """
        scheduler_bus = EventBus()
        due_events: list[TaskEvent] = []
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.DUE, due_events.append)
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

        dispatcher_bus = SpyBus()  # the dispatcher's own bus — must stay silent
        dispatcher = DeliveryDispatcher(channels={}, bus=dispatcher_bus)
        scheduler = TaskScheduler(bus=scheduler_bus)
        task = _task(id="once-1", scheduled_time=datetime.now() - timedelta(seconds=1))
        await scheduler.add_task(task)

        await scheduler.start(on_due_task=dispatcher.on_due_task)
        try:
            settled = await _wait_for_status(scheduler, "once-1", TaskStatus.COMPLETED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.COMPLETED
        assert len(due_events) == 1  # single trigger, no double-fire
        assert len(completed) == 1  # the scheduler is the sole emitter
        assert failed == []
        # The dispatcher's receipt reached the scheduler COMPLETED payload;
        # that one event is the sole web push (T8 hook broadcasts it).
        assert completed[0].payload["result"] == WEB_RECEIPT
        assert "duration_ms" in completed[0].payload
        # And the dispatcher never emitted / pushed anything itself.
        assert dispatcher_bus.emitted == []

    async def test_wechat_task_full_chain_delivers_via_channel(self):
        """IM task: one send_message through the channel, one COMPLETED."""
        scheduler_bus = EventBus()
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

        channel = FakeChannel(last_user_id="wx-user-7")
        dispatcher = DeliveryDispatcher(channels={"wechat": channel})
        scheduler = TaskScheduler(bus=scheduler_bus)
        task = _task(
            id="once-3",
            channel=DeliveryChannel.WECHAT,
            scheduled_time=datetime.now() - timedelta(seconds=1),
        )
        await scheduler.add_task(task)

        await scheduler.start(on_due_task=dispatcher.on_due_task)
        try:
            settled = await _wait_for_status(scheduler, "once-3", TaskStatus.COMPLETED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.COMPLETED
        assert channel.sent == [("wx-user-7", CONTENT)]  # delivered exactly once
        assert len(completed) == 1
        assert failed == []
        assert "wx-user-7" in completed[0].payload["result"]
        assert "wechat" in completed[0].payload["result"]

    async def test_once_task_delivery_failure_ends_failed(self):
        """A raising dispatcher is settled by the scheduler as FAILED."""
        scheduler_bus = EventBus()
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

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

    async def test_prompt_task_full_chain_single_completed_with_reply(self):
        """Full chain: prompt once task → on_prompt_task runs the runner → the
        reply lands in the COMPLETED payload.result; no channel copy for web."""
        scheduler_bus = EventBus()
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

        runner = _PromptRunner(REPLY)
        dispatcher = DeliveryDispatcher(channels={}, prompt_runner=runner)
        scheduler = TaskScheduler(bus=scheduler_bus)
        task = _task(
            id="prompt-1",
            mode="prompt",
            scheduled_time=datetime.now() - timedelta(seconds=1),
        )
        await scheduler.add_task(task)

        await scheduler.start(
            on_due_task=dispatcher.on_due_task, on_prompt_task=dispatcher.on_prompt_task
        )
        try:
            settled = await _wait_for_status(scheduler, "prompt-1", TaskStatus.COMPLETED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.COMPLETED
        assert runner.seen == ["prompt-1"]
        assert len(completed) == 1
        assert completed[0].payload["result"] == REPLY
        assert "duration_ms" in completed[0].payload
        assert failed == []

    async def test_prompt_im_task_full_chain_sends_reply_via_channel(self):
        """Full chain: prompt wechat task → runner reply → send_message(reply)."""
        scheduler_bus = EventBus()
        completed: list[TaskEvent] = []
        failed: list[TaskEvent] = []
        scheduler_bus.subscribe(TaskEventType.COMPLETED, completed.append)
        scheduler_bus.subscribe(TaskEventType.FAILED, failed.append)

        channel = FakeChannel(last_user_id="wx-user-7")
        runner = _PromptRunner(REPLY)
        dispatcher = DeliveryDispatcher(channels={"wechat": channel}, prompt_runner=runner)
        scheduler = TaskScheduler(bus=scheduler_bus)
        task = _task(
            id="prompt-3",
            mode="prompt",
            channel=DeliveryChannel.WECHAT,
            scheduled_time=datetime.now() - timedelta(seconds=1),
        )
        await scheduler.add_task(task)

        await scheduler.start(
            on_due_task=dispatcher.on_due_task, on_prompt_task=dispatcher.on_prompt_task
        )
        try:
            settled = await _wait_for_status(scheduler, "prompt-3", TaskStatus.COMPLETED)
        finally:
            await scheduler.stop()

        assert settled.status is TaskStatus.COMPLETED
        assert channel.sent == [("wx-user-7", REPLY)]  # the reply, not the content
        assert len(completed) == 1
        assert completed[0].payload["result"] == REPLY
        assert failed == []
