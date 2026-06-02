"""Subagent manager for creating and managing subagents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from thumbelina.llm.base import LLMProvider
from thumbelina.subagents.base import Subagent, SubagentStatus

logger = logging.getLogger(__name__)


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
            raise RuntimeError(
                f"Maximum number of agents ({self.max_agents}) reached"
            )

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
        asyncio.create_task(self._execute(agent))

    async def _execute(self, agent: Subagent) -> None:
        """Internal: execute the agent's task via LLM and store the result."""
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
        except asyncio.CancelledError:
            agent.status = SubagentStatus.CANCELLED
            raise
        except Exception as exc:
            logger.warning("Subagent %s failed: %s", agent.id, exc)
            agent.error = str(exc)
            agent.status = SubagentStatus.FAILED

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

        agent.status = SubagentStatus.CANCELLED
        return True
