"""Subagent manager for creating and managing subagents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from thumbelina.llm.base import LLMProvider
from thumbelina.subagents.base import Subagent, SubagentEvent, SubagentStatus

logger = logging.getLogger(__name__)


SubagentListener = Callable[[SubagentEvent], Awaitable[None]]


def _iso(dt: datetime | None) -> str | None:
    """Format a datetime as ISO-8601 with timezone, ``None`` for unset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


class SubagentManager:
    """Manager for creating and managing subagents.

    Parameters
    ----------
    llm_provider:
        The LLM provider for subagent execution.
    max_agents:
        Maximum number of concurrent subagents.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        max_agents: int = 5,
    ) -> None:
        self.llm_provider = llm_provider
        self.max_agents = max_agents
        self._agents: dict[str, Subagent] = {}
        # Listeners receive a SubagentEvent at every status transition.
        # They may be sync or async coroutines; async listeners are scheduled
        # as tasks so a slow subscriber cannot block the manager's loop.
        self._listeners: list[SubagentListener] = []

    def add_listener(self, fn: SubagentListener) -> Callable[[], None]:
        """Register a lifecycle listener. Returns an unsubscribe callable."""
        self._listeners.append(fn)

        def _unsubscribe() -> None:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

        return _unsubscribe

    async def _emit(
        self,
        agent: Subagent,
        event_type: SubagentEvent.__dataclass_fields__[type].type,  # type: ignore[attr-defined]
    ) -> None:
        """Notify all listeners of a subagent status transition.

        Listener exceptions are swallowed at the dispatch boundary so a
        single misbehaving subscriber cannot break the manager.
        """
        event = SubagentEvent(
            type=event_type,
            id=agent.id,
            task=agent.task,
            status=agent.status,
            result=agent.result,
            error=agent.error,
            started_at=_iso(agent.started_at),
            finished_at=_iso(agent.finished_at),
        )
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    # Fire-and-forget so we never block the manager's loop
                    # or the calling tool coroutine on a slow subscriber.
                    asyncio.create_task(result)
            except Exception:
                logger.warning("Subagent listener raised", exc_info=True)

    async def create_agent(self, task: str) -> Subagent:
        """Create a new subagent.

        Parameters
        ----------
        task:
            Description of the task for the agent to execute.

        Returns
        -------
        Subagent
            The created subagent.

        Raises
        ------
        RuntimeError
            If maximum number of agents is reached.
        """
        if len(self._agents) >= self.max_agents:
            raise RuntimeError(f"Maximum number of agents ({self.max_agents}) reached")

        agent = Subagent(task=task)
        self._agents[agent.id] = agent
        return agent

    async def run_agent(self, agent_id: str) -> None:
        """Start executing a subagent asynchronously.

        The agent executes the task via the LLM provider in a background
        coroutine.  Status transitions: PENDING → RUNNING → COMPLETED/FAILED.

        Parameters
        ----------
        agent_id:
            ID of the agent to run.

        Raises
        ------
        ValueError
            If the agent does not exist or is not in PENDING state.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id!r}")
        if agent.status != SubagentStatus.PENDING:
            raise ValueError(
                f"Agent {agent_id!r} cannot be run: current status is {agent.status.value}"
            )

        agent.status = SubagentStatus.RUNNING
        agent.started_at = datetime.now(UTC)
        asyncio.create_task(self._execute(agent))

    async def _execute(self, agent: Subagent) -> None:
        """Internal: execute the agent's task via LLM and store the result."""
        await self._emit(agent, "subagent.started")
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a subagent executing a specific task. "
                        "Complete the task concisely and return only the result."
                    ),
                },
                {"role": "user", "content": agent.task},
            ]
            result = await self.llm_provider.chat(messages)
            agent.result = result
            agent.status = SubagentStatus.COMPLETED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.completed")
        except asyncio.CancelledError:
            agent.status = SubagentStatus.CANCELLED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.cancelled")
            raise
        except Exception as exc:
            logger.warning("Subagent %s failed: %s", agent.id, exc)
            agent.error = str(exc)
            agent.status = SubagentStatus.FAILED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.failed")

    async def get_agent(self, agent_id: str) -> Subagent | None:
        """Get a subagent by ID."""
        return self._agents.get(agent_id)

    async def list_agents(self) -> list[Subagent]:
        """List all subagents."""
        return list(self._agents.values())

    async def cancel_agent(self, agent_id: str) -> bool:
        """Cancel a subagent.

        Parameters
        ----------
        agent_id:
            ID of the agent to cancel.

        Returns
        -------
        bool
            True if cancelled, False if not found.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return False

        # Only flip status if the agent is still running; terminal states
        # are preserved so we don't lie about a completed run. The asyncio
        # task running the LLM call is not currently tracked, so we don't
        # attempt to interrupt it here — the cancel_event-style behaviour
        # belongs to a future enhancement.
        if agent.status in (SubagentStatus.PENDING, SubagentStatus.RUNNING):
            agent.status = SubagentStatus.CANCELLED
            agent.finished_at = datetime.now(UTC)
            await self._emit(agent, "subagent.cancelled")
        return True
