"""Subagent manager for creating and managing subagents."""

from __future__ import annotations

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
