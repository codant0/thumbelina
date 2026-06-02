"""Tests for subagent communication layer."""

from __future__ import annotations

import asyncio

import pytest

from thumbelina.subagents.communication import MessageQueue, SharedState


@pytest.fixture
def queue():
    """Create a MessageQueue."""
    return MessageQueue()


@pytest.fixture
def state():
    """Create a SharedState."""
    return SharedState()


class TestMessageQueue:
    """Tests for the MessageQueue class."""

    def test_queue_class_exists(self):
        """MessageQueue should be importable."""
        assert MessageQueue is not None

    def test_queue_creates_instance(self):
        """Should create a MessageQueue."""
        q = MessageQueue()
        assert q is not None

    @pytest.mark.asyncio
    async def test_send_and_receive(self, queue):
        """Should be able to send and receive messages."""
        await queue.send(to="agent-1", content="Hello", sender="agent-2")
        msg = await queue.receive("agent-1")

        assert msg is not None
        assert msg["from"] == "agent-2"
        assert msg["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_receive_empty(self, queue):
        """Should return None when no messages."""
        msg = await queue.receive("agent-1")
        assert msg is None

    @pytest.mark.asyncio
    async def test_multiple_messages(self, queue):
        """Should receive messages in order."""
        await queue.send(to="a1", content="msg1")
        await queue.send(to="a1", content="msg2")

        msg1 = await queue.receive("a1")
        msg2 = await queue.receive("a1")

        assert msg1["content"] == "msg1"
        assert msg2["content"] == "msg2"

    @pytest.mark.asyncio
    async def test_broadcast(self, queue):
        """Should be able to broadcast to all agents."""
        # First send messages to create queues for agents
        await queue.send(to="agent-1", content="init")
        await queue.send(to="agent-2", content="init")
        # Consume them
        await queue.receive("agent-1")
        await queue.receive("agent-2")

        await queue.broadcast("sender", "Hello all")

        msg1 = await queue.receive("agent-1")
        msg2 = await queue.receive("agent-2")

        assert msg1 is not None
        assert msg2 is not None
        assert msg1["content"] == "Hello all"

    @pytest.mark.asyncio
    async def test_queue_size(self, queue):
        """Should track queue size."""
        assert await queue.size("agent-1") == 0

        await queue.send("agent-1", "msg1")
        await queue.send("agent-1", "msg2")

        assert await queue.size("agent-1") == 2

    @pytest.mark.asyncio
    async def test_broadcast_excludes_sender(self, queue):
        """Broadcast should not send to the sender."""
        # Create queues for sender and other
        await queue.send(to="sender", content="init")
        await queue.send(to="other", content="init")
        await queue.receive("sender")
        await queue.receive("other")

        await queue.broadcast("sender", "Hello all")

        # Sender should not receive the broadcast
        msg_sender = await queue.receive("sender")
        assert msg_sender is None

        # Other should receive it
        msg_other = await queue.receive("other")
        assert msg_other is not None
        assert msg_other["content"] == "Hello all"


class TestSharedState:
    """Tests for the SharedState class."""

    def test_state_class_exists(self):
        """SharedState should be importable."""
        assert SharedState is not None

    def test_state_creates_instance(self):
        """Should create a SharedState."""
        s = SharedState()
        assert s is not None

    @pytest.mark.asyncio
    async def test_set_and_get(self, state):
        """Should be able to set and get values."""
        await state.set("key1", "value1")
        result = await state.get("key1")

        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, state):
        """Should return None for non-existent key."""
        result = await state.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite(self, state):
        """Should overwrite existing values."""
        await state.set("key1", "old")
        await state.set("key1", "new")

        result = await state.get("key1")
        assert result == "new"

    @pytest.mark.asyncio
    async def test_delete(self, state):
        """Should be able to delete values."""
        await state.set("key1", "value1")
        result = await state.delete("key1")

        assert result is True
        assert await state.get("key1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, state):
        """Should return False when deleting non-existent key."""
        result = await state.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_keys(self, state):
        """Should list all keys."""
        await state.set("a", 1)
        await state.set("b", 2)

        keys = await state.keys()
        assert set(keys) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_concurrent_set_and_get(self, state):
        """Concurrent set and get should not corrupt data."""
        async def writer(n: int) -> None:
            for i in range(n):
                await state.set(f"key-{i}", i)

        async def reader(n: int) -> list:
            results = []
            for i in range(n):
                val = await state.get(f"key-{i}")
                results.append(val)
            return results

        # Run concurrent writers and readers
        await asyncio.gather(
            writer(50),
            reader(50),
            writer(50),
            reader(50),
        )

        # Verify final state is consistent
        keys = await state.keys()
        assert len(keys) > 0
        for key in keys:
            val = await state.get(key)
            assert val is not None
