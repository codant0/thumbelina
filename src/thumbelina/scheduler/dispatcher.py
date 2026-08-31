"""Delivery dispatcher — the sole delivery entry point for due tasks.

Registered as the scheduler's ``on_due_task`` callback (design §5.2/§5.3,
decision D5 inline-await): when a task fires, the dispatcher hands its
content to the channel selected by ``task.channel``.  For IM channels
(``wechat``/``qq``) that is a :class:`~thumbelina.channels.base.Channel`
send to the channel's most recent user.  For ``web`` there is nothing to
send here — see the T7-R1 ruling below.

``mode="prompt"`` tasks are orchestrated through :meth:`on_prompt_task`
(design §5.4, wired as the scheduler's ``on_prompt_task`` callback): the
prompt runner (a Task 13 closure that runs the agent and writes the reply
into the conversation) produces the reply, and the dispatcher additionally
sends that **reply** through IM channels as a channel copy.  The scheduler
alone settles COMPLETED/FAILED and emits the events — the dispatcher only
returns the reply (the scheduler puts it in the COMPLETED payload
``result``) or raises (the scheduler catches and settles FAILED with
``payload.error=str(exc)``).  Per the task-5 ruling it never emits on the
bus, prompt mode included.

Review ruling T7-R1 (fix round 1, recorded in the task ledger): **web
渠道交付 = 事件管线本身**.  T8 assembles a WebPushHook observer that
subscribes to every :class:`~thumbelina.scheduler.models.TaskEventType`
and broadcasts each event to the frontend via
``broadcast_chat_message`` — so every event reaches the frontend exactly
once, as the canonical event (event-log id, ``duration_ms`` in payload).
The scheduler's COMPLETED event already carries the receipt this method
returns (``payload.result``).  The dispatcher therefore neither builds
COMPLETED frames nor takes a ``web_push`` callback: an earlier
``web_push`` constructor parameter (and its fabricated-frame path) was
removed by this ruling — do not restore it, a direct push here would
double every web event.  (Design §5.3's ``DeliveryDispatcher(channels=…,
web_push=…, bus=bus)`` sketch is superseded; T8 wires
``DeliveryDispatcher(channels=…, bus=bus)``.)

Delivery contract (task-5 review ruling, still in force): success →
return a receipt string; failure → raise :class:`DeliveryError` (or
re-raise the channel's own exception untouched); the scheduler catches it,
settles the ``task.failed`` verdict and records
``payload.error=str(exc)``.  The dispatcher never emits on the bus.

See ``docs/plans/2026-08-30-event-timer-tasks-design.md`` (§5.1 dispatcher
row, §8.2 WebSocket frame) and D7 for the channel semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from thumbelina.channels.base import Channel
from thumbelina.scheduler.events import EventBus
from thumbelina.scheduler.models import DeliveryChannel, ScheduledTask

__all__ = ["DeliveryDispatcher", "DeliveryError"]

# Receipt for web tasks (the scheduler copies the return value into the
# COMPLETED payload ``result``, so their wording is part of the contract).
_WEB_RECEIPT = "delivered via web event pipeline"

# A prompt runner turns a prompt-mode task into a reply string (design
# §5.4); the app wires a closure that runs the agent and writes the reply
# into the conversation.
PromptRunner = Callable[[ScheduledTask], Awaitable[str]]


class DeliveryError(RuntimeError):
    """Raised when a due task cannot be delivered through its channel.

    Deliberately a :class:`RuntimeError`: the scheduler's ``_fire_task``
    catches it generically and turns the message into the ``task.failed``
    payload ``error`` (``"channel not available"``, ``"no recent user on
    channel"``, ``"mode not supported yet"``, ``"unknown channel: …"``).
    """


class DeliveryDispatcher:
    """Deliver due-task content through the task's channel.

    Parameters
    ----------
    channels:
        IM channel table keyed by channel name (``"wechat"``/``"qq"``).
        A task naming a channel missing from the table fails delivery
        (``"channel not available"``) — the service does not degrade
        silently (design §5.3).  ``web`` tasks need no entry: their
        delivery is the event pipeline itself (T7-R1, see module
        docstring).
    bus:
        Retained as the future prompt-mode extension point (design §13).
        **Never used for emission**: per the review rulings the scheduler
        alone emits COMPLETED/FAILED (task-5 ruling), and web delivery is
        the event pipeline itself (T7-R1), so this parameter is inert
        today.
    """

    def __init__(
        self,
        channels: dict[str, Channel],
        bus: EventBus | None = None,
        prompt_runner: PromptRunner | None = None,
    ) -> None:
        self._channels = dict(channels)
        # Inert by ruling; kept so T8/prompt-mode wiring needs no change.
        self._bus = bus
        # §5.4: turns a prompt-mode task into a reply.  A task arrives with
        # mode="prompt" and no runner → DeliveryError("prompt runner not
        # configured"), settled by the scheduler as FAILED.
        self._prompt_runner = prompt_runner

    async def on_due_task(self, task: ScheduledTask) -> str:
        """Deliver ``task``'s content through its channel.

        The scheduler's single ``on_due_task`` callback (D5 inline await).
        ``mode="prompt"`` tasks are not handled here — they go through
        :meth:`on_prompt_task` (design §5.4).

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
            # prompt mode is reserved for on_prompt_task (design §5.4).
            raise DeliveryError("mode not supported")
        try:
            channel = DeliveryChannel(task.channel)
        except ValueError:
            raise DeliveryError(f"unknown channel: {task.channel}") from None
        if channel is DeliveryChannel.WEB:
            # Ruling T7-R1: web delivery IS the event pipeline.  The
            # scheduler's COMPLETED event (payload.result = this receipt,
            # plus duration_ms) is broadcast exactly once by the WebPushHook
            # observer (T8); a direct push here would double every event.
            return _WEB_RECEIPT
        return await self._deliver_im(task, channel, task.content)

    async def on_prompt_task(self, task: ScheduledTask) -> str:
        """Orchestrate a prompt-mode task (design §5.4, sole prompt path).

        The prompt runner (wired by the app in Task 13) executes the task
        content and returns the reply; the dispatcher additionally sends
        that reply through the task's IM channel as a channel copy — the
        notify path sends ``task.content``, the prompt path sends the
        **reply** (the conversation already holds the answer, the channel
        gets a copy).  ``web`` tasks get no channel copy: the event
        pipeline (COMPLETED event with ``payload.result=reply``) is their
        delivery, per T7-R1.

        Returns
        -------
        str
            The runner's reply; the scheduler puts it into the COMPLETED
            event payload ``result``.

        Raises
        ------
        DeliveryError
            For a non-prompt mode, a missing ``prompt_runner``, an unknown
            channel value, a channel missing from the table, or a channel
            without a recent user.  The runner's own exception propagates
            unchanged.  This method never emits events — the scheduler is
            the sole settlement/emission authority.
        """
        if task.mode != "prompt":
            raise DeliveryError("mode not supported")
        if self._prompt_runner is None:
            raise DeliveryError("prompt runner not configured")
        reply = await self._prompt_runner(task)
        try:
            channel = DeliveryChannel(task.channel)
        except ValueError:
            raise DeliveryError(f"unknown channel: {task.channel}") from None
        if channel is not DeliveryChannel.WEB:
            await self._deliver_im(task, channel, reply)
        return reply

    async def _deliver_im(self, task: ScheduledTask, channel: DeliveryChannel, text: str) -> str:
        """Send *text* to the channel's most recent user (D7)."""
        channel_impl = self._channels.get(channel.value)
        if channel_impl is None:
            raise DeliveryError("channel not available")
        user_id = channel_impl.last_user_id
        if not user_id:
            raise DeliveryError("no recent user on channel")
        # A send failure propagates untouched: the scheduler is the sole
        # verdict authority (catches → FAILED / cron retry, payload.error).
        await channel_impl.send_message(user_id, text)
        return f"delivered via {channel.value} to user {user_id}"
