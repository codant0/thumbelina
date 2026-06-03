"""Tests for the Channel abstract base class."""

from __future__ import annotations

import pytest

from thumbelina.channels.base import Channel


class _ConcreteChannel(Channel):
    """Minimal concrete subclass for testing the ABC."""

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_message(self, user_id: str, text: str) -> None:
        self.sent.append((user_id, text))


def test_channel_cannot_be_instantiated() -> None:
    """Channel is an ABC and cannot be instantiated directly."""
    with pytest.raises(TypeError, match="abstract method"):
        Channel()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_concrete_subclass_start_stop() -> None:
    """A concrete Channel subclass implements start/stop lifecycle."""
    ch = _ConcreteChannel()
    assert not ch.started
    await ch.start()
    assert ch.started
    await ch.stop()
    assert ch.stopped


@pytest.mark.asyncio
async def test_concrete_subclass_send_message() -> None:
    """A concrete Channel subclass records sent messages."""
    ch = _ConcreteChannel()
    await ch.send_message("user1", "hello")
    assert ch.sent == [("user1", "hello")]


@pytest.mark.asyncio
async def test_set_handler() -> None:
    """set_handler stores the callback on the channel."""

    async def handler(user_id: str, text: str) -> str:
        return f"echo: {text}"

    ch = _ConcreteChannel()
    assert ch._handler is None
    ch.set_handler(handler)
    assert ch._handler is handler


@pytest.mark.asyncio
async def test_handler_invocation() -> None:
    """The stored handler can be invoked and returns a response."""

    async def handler(user_id: str, text: str) -> str:
        return f"response to {user_id}: {text}"

    ch = _ConcreteChannel()
    ch.set_handler(handler)
    result = await ch._handler("u1", "hi")
    assert result == "response to u1: hi"
