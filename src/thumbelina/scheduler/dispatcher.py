"""Delivery dispatcher — the sole delivery entry point for due tasks.

Registered as the scheduler's ``on_due_task`` callback (design §5.2/§5.3,
decision D5 inline-await): when a task fires, the dispatcher hands its
content to the channel selected by ``task.channel`` — ``web`` goes to the
injected WebSocket push callback, ``wechat``/``qq`` go to the matching
:class:`~thumbelina.channels.base.Channel`'s most recent user.

Review ruling (recorded in the task ledger, amending the original brief):
COMPLETED/FAILED events are emitted **solely by the scheduler** — the
dispatcher neither subscribes to the bus nor emits on it (a second
emission would double-fire every observer).  The delivery contract is
therefore:

- success → return a receipt string; the scheduler records it in the
  ``task.completed`` payload ``result``;
- failure → raise :class:`DeliveryError` (or re-raise the channel's own
  exception untouched); the scheduler catches it, settles the
  ``task.failed`` verdict and records ``payload.error=str(exc)``.

See ``docs/plans/2026-08-30-event-timer-tasks-design.md`` (§5.1 dispatcher
row, §8.2 WebSocket frame) and D7 for the channel semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from thumbelina.channels.base import Channel
from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TaskEventType,
)

__all__ = ["DeliveryDispatcher", "DeliveryError", "WebPush"]

# Injected WebSocket broadcast callback; T8 wires
# ``api.websocket.broadcast_chat_message`` here at assembly time.
WebPush = Callable[[dict[str, Any]], Awaitable[None]]

# Receipts (the scheduler copies the return value into the COMPLETED
# payload ``result``, so their wording is part of the delivery contract).
_WEB_PUSH_DELIVERED = "web push delivered"
_WEB_PUSH_SKIPPED = "web push skipped: no web_push callback wired"


class DeliveryError(RuntimeError):
    """Raised when a due task cannot be delivered through its channel.

    Deliberately a :class:`RuntimeError`: the scheduler's ``_fire_task``
    catches it generically and turns the message into the ``task.failed``
    payload ``error`` (``"channel not available"``, ``"no recent user on
    channel"``, ``"mode not supported yet"``, ``"unknown channel"``).
    """


def _plain(value: Any) -> str:
    """Plain string for a StrEnum member (or an already-plain string)."""
    return value.value if isinstance(value, StrEnum) else str(value)


def _frame_body(event: TaskEvent) -> dict[str, Any]:
    """Serialize a TaskEvent into the §8.2 ``task_event`` frame body."""
    return {
        "id": event.id,
        "type": event.type.value,
        "task_id": event.task_id,
        "fired_at": event.fired_at.isoformat(),
        "trigger": _plain(event.trigger),
        "channel": _plain(event.channel),
        "content": event.content,
        "payload": event.payload,
    }


class DeliveryDispatcher:
    """Deliver due-task content through the task's channel.

    Parameters
    ----------
    channels:
        IM channel table keyed by channel name (``"wechat"``/``"qq"``).
        A task naming a channel missing from the table fails delivery
        (``"channel not available"``) — the service does not degrade
        silently (design §5.3).
    web_push:
        Async callback receiving ``{"task_event": …}`` frames (§8.2);
        T8 injects ``broadcast_chat_message``.  ``None`` means the
        frontend push is not wired — a web delivery is then a successful
        skip, not a failure.
    bus:
        Retained as the future prompt-mode extension point (design §13).
        **Never used for emission**: per the review ruling the scheduler
        alone emits COMPLETED/FAILED, so this parameter is inert today.
    """

    def __init__(
        self,
        channels: dict[str, Channel],
        web_push: WebPush | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._channels = dict(channels)
        self._web_push = web_push
        # Inert by ruling; kept so T8/prompt-mode wiring needs no change.
        self._bus = bus

    async def on_due_task(self, task: ScheduledTask) -> str:
        """Deliver ``task``'s content through its channel.

        The scheduler's single ``on_due_task`` callback (D5 inline await).

        Returns
        -------
        str
            A delivery receipt; the scheduler puts it into the
            COMPLETED event payload ``result``.

        Raises
        ------
        DeliveryError
            For an unsupported mode, an unknown channel value, a channel
            missing from the table, or a channel without a recent user.
            Any exception raised by ``Channel.send_message`` propagates
            unchanged — in every failure case the scheduler catches and
            settles the FAILED verdict; this method never emits events.
        """
        if task.mode != "notify":
            # prompt mode is a reserved extension point (design §1.3/§13).
            raise DeliveryError("mode not supported yet")
        try:
            channel = DeliveryChannel(task.channel)
        except ValueError:
            raise DeliveryError("unknown channel") from None
        if channel is DeliveryChannel.WEB:
            return await self._deliver_web(task, channel)
        return await self._deliver_im(task, channel)

    async def _deliver_web(self, task: ScheduledTask, channel: DeliveryChannel) -> str:
        """Push the COMPLETED task_event frame to the frontend (§8.2)."""
        if self._web_push is None:
            # Frontend not wired (T8 assembles broadcast_chat_message):
            # nothing to deliver to, nothing failed — a successful skip.
            return _WEB_PUSH_SKIPPED
        receipt = _WEB_PUSH_DELIVERED
        event = TaskEvent(
            type=TaskEventType.COMPLETED,
            task_id=task.id,
            trigger=task.trigger,
            channel=channel,
            content=task.content,
            payload={"result": receipt},
        )
        await self._web_push({"task_event": _frame_body(event)})
        return receipt

    async def _deliver_im(self, task: ScheduledTask, channel: DeliveryChannel) -> str:
        """Send the content to the channel's most recent user (D7)."""
        channel_impl = self._channels.get(channel.value)
        if channel_impl is None:
            raise DeliveryError("channel not available")
        user_id = channel_impl.last_user_id
        if not user_id:
            raise DeliveryError("no recent user on channel")
        # A send failure propagates untouched: the scheduler is the sole
        # verdict authority (catches → FAILED / cron retry, payload.error).
        await channel_impl.send_message(user_id, task.content)
        return f"delivered via {channel.value} to user {user_id}"
