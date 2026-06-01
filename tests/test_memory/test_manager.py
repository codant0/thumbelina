"""Tests for thumbelina.memory.manager module."""

from __future__ import annotations

import pytest

from thumbelina.memory.manager import MemoryManager


@pytest.fixture
def manager():
    """Create a MemoryManager with in-memory SQLite database."""
    return MemoryManager("sqlite:///:memory:")


class TestMemoryManager:
    """Tests for the MemoryManager class."""

    def test_manager_class_exists(self):
        """MemoryManager should be importable."""
        from thumbelina.memory.manager import MemoryManager

        assert MemoryManager is not None

    def test_manager_requires_db_url(self):
        """MemoryManager should accept a database URL."""
        manager = MemoryManager("sqlite:///:memory:")
        assert manager is not None

    def test_manager_has_repository(self, manager: MemoryManager):
        """MemoryManager should have a repository."""
        assert hasattr(manager, "repository")
        assert manager.repository is not None

    @pytest.mark.asyncio
    async def test_create_conversation(self, manager: MemoryManager):
        """Should be able to create a conversation."""
        conversation_id = await manager.create_conversation()

        assert conversation_id is not None
        assert isinstance(conversation_id, str)
        assert len(conversation_id) > 0

    @pytest.mark.asyncio
    async def test_add_message(self, manager: MemoryManager):
        """Should be able to add a message to a conversation."""
        conversation_id = await manager.create_conversation()

        await manager.add_message(
            conversation_id=conversation_id,
            role="user",
            content="Hello, world!",
        )

    @pytest.mark.asyncio
    async def test_add_message_to_nonexistent_conversation(self, manager: MemoryManager):
        """Should raise error when adding message to non-existent conversation."""
        with pytest.raises(ValueError, match="Conversation not found"):
            await manager.add_message(
                conversation_id="nonexistent-id",
                role="user",
                content="Hello",
            )

    @pytest.mark.asyncio
    async def test_get_messages(self, manager: MemoryManager):
        """Should be able to get messages from a conversation."""
        conversation_id = await manager.create_conversation()

        await manager.add_message(
            conversation_id=conversation_id,
            role="user",
            content="Hello",
        )
        await manager.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Hi there!",
        )

        messages = await manager.get_messages(conversation_id)

        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there!"

    @pytest.mark.asyncio
    async def test_get_messages_empty(self, manager: MemoryManager):
        """Should return empty list for conversation with no messages."""
        conversation_id = await manager.create_conversation()
        messages = await manager.get_messages(conversation_id)

        assert messages == []

    @pytest.mark.asyncio
    async def test_get_conversations_empty(self, manager: MemoryManager):
        """Should return empty list when no conversations exist."""
        conversations = await manager.get_conversations()

        assert conversations == []

    @pytest.mark.asyncio
    async def test_get_conversations(self, manager: MemoryManager):
        """Should return list of conversations."""
        id1 = await manager.create_conversation()
        id2 = await manager.create_conversation()

        conversations = await manager.get_conversations()

        assert len(conversations) == 2
        conversation_ids = {c["id"] for c in conversations}
        assert id1 in conversation_ids
        assert id2 in conversation_ids

    @pytest.mark.asyncio
    async def test_get_conversation(self, manager: MemoryManager):
        """Should be able to get a single conversation by ID."""
        conversation_id = await manager.create_conversation()

        conversation = await manager.get_conversation(conversation_id)

        assert conversation is not None
        assert conversation["id"] == conversation_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation(self, manager: MemoryManager):
        """Should return None for non-existent conversation."""
        conversation = await manager.get_conversation("nonexistent-id")

        assert conversation is None

    @pytest.mark.asyncio
    async def test_delete_conversation(self, manager: MemoryManager):
        """Should be able to delete a conversation."""
        conversation_id = await manager.create_conversation()

        await manager.add_message(
            conversation_id=conversation_id,
            role="user",
            content="Test message",
        )

        result = await manager.delete_conversation(conversation_id)

        assert result is True

        conversation = await manager.get_conversation(conversation_id)
        assert conversation is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation(self, manager: MemoryManager):
        """Should return False when deleting non-existent conversation."""
        result = await manager.delete_conversation("nonexistent-id")

        assert result is False

    @pytest.mark.asyncio
    async def test_full_conversation_flow(self, manager: MemoryManager):
        """Should support a full conversation flow."""
        # Create conversation
        conversation_id = await manager.create_conversation()

        # Add user message
        await manager.add_message(
            conversation_id=conversation_id,
            role="user",
            content="What is Python?",
        )

        # Add assistant response
        await manager.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Python is a programming language.",
        )

        # Get messages
        messages = await manager.get_messages(conversation_id)

        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What is Python?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Python is a programming language."

    @pytest.mark.asyncio
    async def test_multiple_conversations(self, manager: MemoryManager):
        """Should support multiple independent conversations."""
        # Create two conversations
        conv1_id = await manager.create_conversation()
        conv2_id = await manager.create_conversation()

        # Add messages to first conversation
        await manager.add_message(
            conversation_id=conv1_id,
            role="user",
            content="Hello in conv1",
        )

        # Add messages to second conversation
        await manager.add_message(
            conversation_id=conv2_id,
            role="user",
            content="Hello in conv2",
        )

        # Verify messages are separate
        messages1 = await manager.get_messages(conv1_id)
        messages2 = await manager.get_messages(conv2_id)

        assert len(messages1) == 1
        assert len(messages2) == 1
        assert messages1[0]["content"] == "Hello in conv1"
        assert messages2[0]["content"] == "Hello in conv2"
