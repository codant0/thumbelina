"""Tests for thumbelina.repository.repository module."""

from __future__ import annotations

import pytest

from thumbelina.repository.repository import ConversationRepository


@pytest.fixture
def repo():
    """Create a repository with in-memory SQLite database."""
    return ConversationRepository("sqlite:///:memory:")


class TestConversationRepository:
    """Tests for the ConversationRepository class."""

    def test_repository_class_exists(self):
        """ConversationRepository should be importable."""
        from thumbelina.repository.repository import ConversationRepository

        assert ConversationRepository is not None

    def test_repository_requires_db_url(self):
        """ConversationRepository should accept a database URL."""
        repo = ConversationRepository("sqlite:///:memory:")
        assert repo is not None

    @pytest.mark.asyncio
    async def test_create_conversation(self, repo: ConversationRepository):
        """Should be able to create a conversation."""
        conversation_id = await repo.create_conversation()
        assert conversation_id is not None
        assert isinstance(conversation_id, str)
        assert len(conversation_id) > 0

    @pytest.mark.asyncio
    async def test_create_multiple_conversations(self, repo: ConversationRepository):
        """Should be able to create multiple conversations."""
        id1 = await repo.create_conversation()
        id2 = await repo.create_conversation()

        assert id1 != id2

    @pytest.mark.asyncio
    async def test_add_message(self, repo: ConversationRepository):
        """Should be able to add a message to a conversation."""
        conversation_id = await repo.create_conversation()

        await repo.add_message(
            conversation_id=conversation_id,
            role="user",
            content="Hello, world!",
        )

    @pytest.mark.asyncio
    async def test_add_message_to_nonexistent_conversation(self, repo: ConversationRepository):
        """Should raise error when adding message to non-existent conversation."""
        with pytest.raises(ValueError, match="Conversation not found"):
            await repo.add_message(
                conversation_id="nonexistent-id",
                role="user",
                content="Hello",
            )

    @pytest.mark.asyncio
    async def test_get_messages_empty(self, repo: ConversationRepository):
        """Should return empty list for conversation with no messages."""
        conversation_id = await repo.create_conversation()
        messages = await repo.get_messages(conversation_id)

        assert messages == []

    @pytest.mark.asyncio
    async def test_get_messages(self, repo: ConversationRepository):
        """Should return messages in order."""
        conversation_id = await repo.create_conversation()

        await repo.add_message(
            conversation_id=conversation_id,
            role="user",
            content="First message",
        )
        await repo.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Second message",
        )

        messages = await repo.get_messages(conversation_id)

        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "First message"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Second message"

    @pytest.mark.asyncio
    async def test_get_messages_returns_dicts(self, repo: ConversationRepository):
        """Messages should be returned as dictionaries."""
        conversation_id = await repo.create_conversation()

        await repo.add_message(
            conversation_id=conversation_id,
            role="user",
            content="Test message",
        )

        messages = await repo.get_messages(conversation_id)
        message = messages[0]

        assert isinstance(message, dict)
        assert "id" in message
        assert "conversation_id" in message
        assert "role" in message
        assert "content" in message
        assert "created_at" in message

    @pytest.mark.asyncio
    async def test_get_messages_from_nonexistent_conversation(self, repo: ConversationRepository):
        """Should raise error for non-existent conversation."""
        with pytest.raises(ValueError, match="Conversation not found"):
            await repo.get_messages("nonexistent-id")

    @pytest.mark.asyncio
    async def test_get_conversations_empty(self, repo: ConversationRepository):
        """Should return empty list when no conversations exist."""
        conversations = await repo.get_conversations()

        assert conversations == []

    @pytest.mark.asyncio
    async def test_get_conversations(self, repo: ConversationRepository):
        """Should return list of conversations."""
        id1 = await repo.create_conversation()
        id2 = await repo.create_conversation()

        conversations = await repo.get_conversations()

        assert len(conversations) == 2
        conversation_ids = {c["id"] for c in conversations}
        assert id1 in conversation_ids
        assert id2 in conversation_ids

    @pytest.mark.asyncio
    async def test_get_conversations_returns_dicts(self, repo: ConversationRepository):
        """Conversations should be returned as dictionaries."""
        await repo.create_conversation()

        conversations = await repo.get_conversations()
        conversation = conversations[0]

        assert isinstance(conversation, dict)
        assert "id" in conversation
        assert "created_at" in conversation
        assert "updated_at" in conversation

    @pytest.mark.asyncio
    async def test_get_conversation(self, repo: ConversationRepository):
        """Should be able to get a single conversation by ID."""
        conversation_id = await repo.create_conversation()

        conversation = await repo.get_conversation(conversation_id)

        assert conversation is not None
        assert conversation["id"] == conversation_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation(self, repo: ConversationRepository):
        """Should return None for non-existent conversation."""
        conversation = await repo.get_conversation("nonexistent-id")

        assert conversation is None

    @pytest.mark.asyncio
    async def test_delete_conversation(self, repo: ConversationRepository):
        """Should be able to delete a conversation."""
        conversation_id = await repo.create_conversation()

        await repo.add_message(
            conversation_id=conversation_id,
            role="user",
            content="Test message",
        )

        result = await repo.delete_conversation(conversation_id)

        assert result is True

        conversation = await repo.get_conversation(conversation_id)
        assert conversation is None

        # After deletion, getting messages should raise an error
        with pytest.raises(ValueError, match="Conversation not found"):
            await repo.get_messages(conversation_id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation(self, repo: ConversationRepository):
        """Should return False when deleting non-existent conversation."""
        result = await repo.delete_conversation("nonexistent-id")

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_messages(self, repo: ConversationRepository):
        """Should remove all messages but keep the conversation."""
        conversation_id = await repo.create_conversation()
        await repo.add_message(conversation_id=conversation_id, role="user", content="a")
        await repo.add_message(conversation_id=conversation_id, role="assistant", content="b")
        await repo.set_summary(conversation_id, "stale summary")

        result = await repo.clear_messages(conversation_id)

        assert result is True
        assert await repo.get_messages(conversation_id) == []
        conversation = await repo.get_conversation(conversation_id)
        assert conversation is not None
        assert conversation["summary"] is None

    @pytest.mark.asyncio
    async def test_clear_messages_nonexistent_conversation(self, repo: ConversationRepository):
        """Should return False when clearing messages of a non-existent conversation."""
        result = await repo.clear_messages("nonexistent-id")

        assert result is False

    @pytest.mark.asyncio
    async def test_message_order(self, repo: ConversationRepository):
        """Messages should be returned in creation order."""
        conversation_id = await repo.create_conversation()

        for i in range(5):
            await repo.add_message(
                conversation_id=conversation_id,
                role="user",
                content=f"Message {i}",
            )

        messages = await repo.get_messages(conversation_id)

        assert len(messages) == 5
        for i, message in enumerate(messages):
            assert message["content"] == f"Message {i}"


class TestConversationRenameAndEndpoint:
    """Tests for rename_conversation and set_conversation_endpoint."""

    @pytest.mark.asyncio
    async def test_rename_conversation(self, repo: ConversationRepository):
        """rename_conversation should update the name."""
        cid = await repo.create_conversation()
        ok = await repo.rename_conversation(cid, "我的会话")
        assert ok is True
        conv = await repo.get_conversation(cid)
        assert conv["name"] == "我的会话"

    @pytest.mark.asyncio
    async def test_rename_nonexistent_returns_false(self, repo: ConversationRepository):
        """rename_conversation should return False for unknown IDs."""
        assert await repo.rename_conversation("nope", "x") is False

    @pytest.mark.asyncio
    async def test_rename_exposed_in_list(self, repo: ConversationRepository):
        """Renamed conversations should expose the name via get_conversations."""
        cid = await repo.create_conversation()
        await repo.rename_conversation(cid, "列表名")
        convs = await repo.get_conversations()
        target = next(c for c in convs if c["id"] == cid)
        assert target["name"] == "列表名"

    @pytest.mark.asyncio
    async def test_set_conversation_endpoint(self, repo: ConversationRepository):
        """set_conversation_endpoint should persist endpoint_id."""
        cid = await repo.create_conversation()
        assert await repo.set_conversation_endpoint(cid, "ep-1") is True
        conv = await repo.get_conversation(cid)
        assert conv["endpoint_id"] == "ep-1"

    @pytest.mark.asyncio
    async def test_clear_conversation_endpoint(self, repo: ConversationRepository):
        """Passing None should clear the endpoint_id."""
        cid = await repo.create_conversation()
        await repo.set_conversation_endpoint(cid, "ep-1")
        assert await repo.set_conversation_endpoint(cid, None) is True
        conv = await repo.get_conversation(cid)
        assert conv["endpoint_id"] is None

    @pytest.mark.asyncio
    async def test_set_endpoint_nonexistent_returns_false(self, repo: ConversationRepository):
        """set_conversation_endpoint should return False for unknown IDs."""
        assert await repo.set_conversation_endpoint("nope", "ep-1") is False


class TestConversationKnowledgeBase:
    """Tests for set_conversation_knowledge_base."""

    @pytest.mark.asyncio
    async def test_set_conversation_knowledge_base(self, repo: ConversationRepository):
        """set_conversation_knowledge_base should persist knowledge_base_id."""
        cid = await repo.create_conversation()
        assert await repo.set_conversation_knowledge_base(cid, "kb-1") is True
        conv = await repo.get_conversation(cid)
        assert conv["knowledge_base_id"] == "kb-1"

    @pytest.mark.asyncio
    async def test_clear_conversation_knowledge_base(self, repo: ConversationRepository):
        """Passing None should clear the knowledge_base_id."""
        cid = await repo.create_conversation()
        await repo.set_conversation_knowledge_base(cid, "kb-1")
        assert await repo.set_conversation_knowledge_base(cid, None) is True
        conv = await repo.get_conversation(cid)
        assert conv["knowledge_base_id"] is None

    @pytest.mark.asyncio
    async def test_set_knowledge_base_nonexistent_returns_false(self, repo: ConversationRepository):
        """set_conversation_knowledge_base should return False for unknown IDs."""
        assert await repo.set_conversation_knowledge_base("nope", "kb-1") is False

    @pytest.mark.asyncio
    async def test_knowledge_base_exposed_in_list(self, repo: ConversationRepository):
        """Knowledge base ID should be visible via get_conversations."""
        cid = await repo.create_conversation()
        await repo.set_conversation_knowledge_base(cid, "kb-list")
        convs = await repo.get_conversations()
        target = next(c for c in convs if c["id"] == cid)
        assert target["knowledge_base_id"] == "kb-list"

    @pytest.mark.asyncio
    async def test_knowledge_base_exposed_in_get_all_with_messages(
        self, repo: ConversationRepository
    ):
        """Knowledge base ID should be visible via get_all_conversations_with_messages."""
        cid = await repo.create_conversation()
        await repo.set_conversation_knowledge_base(cid, "kb-all")
        convs = await repo.get_all_conversations_with_messages()
        target = next(c for c in convs if c["id"] == cid)
        assert target["knowledge_base_id"] == "kb-all"

    @pytest.mark.asyncio
    async def test_new_conversation_has_null_knowledge_base(self, repo: ConversationRepository):
        """A newly created conversation should have knowledge_base_id=None."""
        cid = await repo.create_conversation()
        conv = await repo.get_conversation(cid)
        assert conv["knowledge_base_id"] is None


class TestConversationRole:
    """Tests for set_conversation_role."""

    @pytest.mark.asyncio
    async def test_set_conversation_role(self, repo: ConversationRepository):
        """set_conversation_role should persist the role."""
        cid = await repo.create_conversation()
        assert await repo.set_conversation_role(cid, "coder") is True
        conv = await repo.get_conversation(cid)
        assert conv["role"] == "coder"

    @pytest.mark.asyncio
    async def test_clear_conversation_role(self, repo: ConversationRepository):
        """Passing None should clear the role."""
        cid = await repo.create_conversation()
        await repo.set_conversation_role(cid, "coder")
        assert await repo.set_conversation_role(cid, None) is True
        conv = await repo.get_conversation(cid)
        assert conv["role"] is None

    @pytest.mark.asyncio
    async def test_set_role_nonexistent_returns_false(self, repo: ConversationRepository):
        """set_conversation_role should return False for unknown IDs."""
        assert await repo.set_conversation_role("nope", "coder") is False

    @pytest.mark.asyncio
    async def test_role_exposed_in_list(self, repo: ConversationRepository):
        """The role should be visible via get_conversations."""
        cid = await repo.create_conversation()
        await repo.set_conversation_role(cid, "assistant")
        convs = await repo.get_conversations()
        target = next(c for c in convs if c["id"] == cid)
        assert target["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_role_exposed_in_get_all_with_messages(self, repo: ConversationRepository):
        """The role should be visible via get_all_conversations_with_messages."""
        cid = await repo.create_conversation()
        await repo.set_conversation_role(cid, "coder")
        convs = await repo.get_all_conversations_with_messages()
        target = next(c for c in convs if c["id"] == cid)
        assert target["role"] == "coder"

    @pytest.mark.asyncio
    async def test_new_conversation_has_null_role(self, repo: ConversationRepository):
        """A newly created conversation should have role=None (global default)."""
        cid = await repo.create_conversation()
        conv = await repo.get_conversation(cid)
        assert conv["role"] is None
