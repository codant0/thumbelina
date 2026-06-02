"""Tests for subagent manager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thumbelina.subagents.manager import SubagentManager
from thumbelina.subagents.base import Subagent, SubagentStatus


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="Task completed")
    return provider


@pytest.fixture
def manager(mock_llm):
    """Create a SubagentManager."""
    return SubagentManager(llm_provider=mock_llm, max_agents=3)


class TestSubagentManager:
    """Tests for the SubagentManager class."""

    def test_manager_class_exists(self):
        """SubagentManager should be importable."""
        assert SubagentManager is not None

    def test_manager_requires_llm_provider(self):
        """Should accept an LLM provider."""
        mock_llm = MagicMock()
        mgr = SubagentManager(llm_provider=mock_llm)
        assert mgr.llm_provider is mock_llm

    def test_manager_default_max_agents(self):
        """Should default to 5 max agents."""
        mock_llm = MagicMock()
        mgr = SubagentManager(llm_provider=mock_llm)
        assert mgr.max_agents == 5

    def test_manager_custom_max_agents(self):
        """Should accept custom max_agents."""
        mock_llm = MagicMock()
        mgr = SubagentManager(llm_provider=mock_llm, max_agents=10)
        assert mgr.max_agents == 10

    @pytest.mark.asyncio
    async def test_create_agent(self, manager):
        """Should create a subagent."""
        agent = await manager.create_agent(task="Test task")

        assert agent is not None
        assert agent.task == "Test task"
        assert agent.status == SubagentStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_agent_respects_limit(self, manager):
        """Should not create more agents than max_agents."""
        for _ in range(3):
            await manager.create_agent(task="Task")

        with pytest.raises(RuntimeError, match="Maximum"):
            await manager.create_agent(task="Too many")

    @pytest.mark.asyncio
    async def test_get_agent(self, manager):
        """Should be able to get an agent by ID."""
        agent = await manager.create_agent(task="Test")
        result = await manager.get_agent(agent.id)

        assert result is not None
        assert result.id == agent.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent(self, manager):
        """Should return None for non-existent agent."""
        result = await manager.get_agent("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_agents(self, manager):
        """Should list all agents."""
        await manager.create_agent(task="Task 1")
        await manager.create_agent(task="Task 2")

        agents = await manager.list_agents()
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, manager):
        """Should return empty list when no agents."""
        agents = await manager.list_agents()
        assert agents == []

    @pytest.mark.asyncio
    async def test_cancel_agent(self, manager):
        """Should be able to cancel an agent."""
        agent = await manager.create_agent(task="Test")
        result = await manager.cancel_agent(agent.id)

        assert result is True
        updated = await manager.get_agent(agent.id)
        assert updated.status == SubagentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, manager):
        """Should return False when cancelling non-existent agent."""
        result = await manager.cancel_agent("nonexistent")
        assert result is False


class TestSubagent:
    """Tests for the Subagent class."""

    def test_subagent_class_exists(self):
        """Subagent should be importable."""
        assert Subagent is not None

    def test_subagent_create(self):
        """Should create a Subagent."""
        agent = Subagent(id="a1", task="Test task")
        assert agent.id == "a1"
        assert agent.task == "Test task"
        assert agent.status == SubagentStatus.PENDING

    def test_subagent_default_status(self):
        """Should default to PENDING status."""
        agent = Subagent(id="a1", task="Test")
        assert agent.status == SubagentStatus.PENDING

    def test_subagent_status_enum(self):
        """SubagentStatus should have expected values."""
        assert SubagentStatus.PENDING == "pending"
        assert SubagentStatus.RUNNING == "running"
        assert SubagentStatus.COMPLETED == "completed"
        assert SubagentStatus.FAILED == "failed"
        assert SubagentStatus.CANCELLED == "cancelled"
