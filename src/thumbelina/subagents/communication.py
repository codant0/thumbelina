"""Communication layer for subagents."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class MessageQueue:
    """Async message queue for inter-agent communication."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(
            asyncio.Queue
        )

    async def send(self, to: str, content: str, sender: str = "") -> None:
        """Send a message to an agent.

        Parameters
        ----------
        to:
            ID of the recipient agent.
        content:
            Message content.
        sender:
            ID of the sending agent.
        """
        await self._queues[to].put({"from": sender, "content": content})

    async def receive(self, agent_id: str) -> dict[str, Any] | None:
        """Receive a message for an agent.

        Parameters
        ----------
        agent_id:
            ID of the agent to receive messages for.

        Returns
        -------
        dict[str, Any] | None
            The next message, or None if queue is empty.
        """
        queue = self._queues.get(agent_id)
        if not queue or queue.empty():
            return None
        return await queue.get()

    async def broadcast(self, sender: str, content: str) -> None:
        """Broadcast a message to all agents.

        Parameters
        ----------
        sender:
            ID of the sending agent.
        content:
            Message content.
        """
        for agent_id in self._queues:
            if agent_id != sender:
                await self.send(agent_id, content, sender)

    async def size(self, agent_id: str) -> int:
        """Get the number of pending messages for an agent."""
        queue = self._queues.get(agent_id)
        return queue.qsize() if queue else 0


class SharedState:
    """Shared state for inter-agent communication."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any:
        """Get a value from shared state."""
        async with self._lock:
            return self._store.get(key)

    async def set(self, key: str, value: Any) -> None:
        """Set a value in shared state."""
        async with self._lock:
            self._store[key] = value

    async def delete(self, key: str) -> bool:
        """Delete a value from shared state."""
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def keys(self) -> list[str]:
        """List all keys in shared state."""
        async with self._lock:
            return list(self._store.keys())
