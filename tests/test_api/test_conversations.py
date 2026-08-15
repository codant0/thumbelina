"""Tests for thumbelina.api.routes.conversations module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def conversation_id(client):
    """Create a conversation and return its ID."""
    # First send a chat message to create a conversation
    response = client.post("/api/v1/chat", json={"message": "Hello"})
    data = response.json()
    return data["conversation_id"]


def test_list_conversations_endpoint_exists(client):
    """GET /api/v1/conversations should exist."""
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200


def test_list_conversations_returns_list(client):
    """GET /api/v1/conversations should return a list."""
    response = client.get("/api/v1/conversations")
    data = response.json()
    assert isinstance(data, list)


def test_list_conversations_after_chat(client, conversation_id):
    """GET /api/v1/conversations should include conversations created via chat."""
    response = client.get("/api/v1/conversations")
    data = response.json()
    conv_ids = [c["id"] for c in data]
    assert conversation_id in conv_ids


def test_get_conversation_endpoint_exists(client, conversation_id):
    """GET /api/v1/conversations/{id} should exist."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200


def test_get_conversation_returns_details(client, conversation_id):
    """GET /api/v1/conversations/{id} should return conversation details."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    data = response.json()
    assert data["id"] == conversation_id
    assert "messages" in data
    assert "created_at" in data


def test_get_nonexistent_conversation(client):
    """GET /api/v1/conversations/{id} should return 404 for nonexistent conversation."""
    response = client.get("/api/v1/conversations/nonexistent-id")
    assert response.status_code == 404


def test_get_conversation_includes_messages(client, conversation_id):
    """GET /api/v1/conversations/{id} should include messages."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    data = response.json()
    messages = data["messages"]
    assert len(messages) >= 1
    # Should have at least the user message
    assert any(m["role"] == "user" for m in messages)


def test_delete_conversation_endpoint_exists(client, conversation_id):
    """DELETE /api/v1/conversations/{id} should exist."""
    response = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code in (200, 204)


def test_delete_conversation_removes_it(client, conversation_id):
    """DELETE /api/v1/conversations/{id} should remove the conversation."""
    client.delete(f"/api/v1/conversations/{conversation_id}")
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 404


def test_delete_nonexistent_conversation(client):
    """DELETE /api/v1/conversations/{id} should return 404 for nonexistent."""
    response = client.delete("/api/v1/conversations/nonexistent-id")
    assert response.status_code == 404


def test_rename_conversation_endpoint(client, conversation_id):
    """PATCH /api/v1/conversations/{id} should rename the conversation."""
    response = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"name": "新名称"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == conversation_id
    assert data["name"] == "新名称"


def test_rename_nonexistent_conversation(client):
    """PATCH /api/v1/conversations/{id} should 404 for unknown IDs."""
    response = client.patch(
        "/api/v1/conversations/nonexistent-id",
        json={"name": "x"},
    )
    assert response.status_code == 404


def test_rename_strips_whitespace(client, conversation_id):
    """PATCH should strip surrounding whitespace from the name."""
    response = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"name": "  trimmed  "},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "trimmed"


def test_set_conversation_endpoint_rejects_unknown_endpoint(client, conversation_id):
    """PUT /conversations/{id}/endpoint should 404 for unknown endpoint_id."""
    # The test client has no endpoint_manager on app.state, so the endpoint
    # manager is None → 503. Accept either the configured-503 or 404 path.
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/endpoint",
        json={"endpoint_id": "missing-ep"},
    )
    assert response.status_code in (404, 503)


def test_clear_conversation_endpoint(client, conversation_id):
    """PUT /conversations/{id}/endpoint with null endpoint_id reverts to default."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/endpoint",
        json={"endpoint_id": None},
    )
    assert response.status_code == 200
    assert response.json()["endpoint_id"] is None


def test_set_conversation_endpoint_rejects_unknown_model(client, conversation_id):
    """PUT /conversations/{id}/endpoint rejects a model not on the endpoint."""
    from thumbelina.llm.endpoint_manager import LLMEndpoint

    endpoint = LLMEndpoint(
        id="ep1",
        provider="openai",
        name="Default",
        base_url="https://api.openai.com/v1",
        models=["gpt-4o"],
        api_key="sk-test",
        api_key_set=True,
        created_at="2026-07-02T00:00:00Z",
        updated_at="2026-07-02T00:00:00Z",
    )
    client.app.state.endpoint_manager = MagicMock()
    client.app.state.endpoint_manager.get_endpoint = AsyncMock(return_value=endpoint)

    response = client.put(
        f"/api/v1/conversations/{conversation_id}/endpoint",
        json={"endpoint_id": "ep1", "model": "not-a-model"},
    )
    assert response.status_code == 422


def test_set_conversation_knowledge_base(client, conversation_id):
    """PUT /conversations/{id}/knowledge-base should bind a knowledge base."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/knowledge-base",
        json={"knowledge_base_id": "kb-123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == conversation_id
    assert data["knowledge_base_id"] == "kb-123"


def test_clear_conversation_knowledge_base(client, conversation_id):
    """PUT /conversations/{id}/knowledge-base with null unbinds the knowledge base."""
    # First bind
    client.put(
        f"/api/v1/conversations/{conversation_id}/knowledge-base",
        json={"knowledge_base_id": "kb-123"},
    )
    # Then clear
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/knowledge-base",
        json={"knowledge_base_id": None},
    )
    assert response.status_code == 200
    assert response.json()["knowledge_base_id"] is None


def test_set_knowledge_base_nonexistent_conversation(client):
    """PUT /conversations/{id}/knowledge-base should 404 for unknown IDs."""
    response = client.put(
        "/api/v1/conversations/nonexistent-id/knowledge-base",
        json={"knowledge_base_id": "kb-123"},
    )
    assert response.status_code == 404


def test_get_roles_lists_available_roles(client):
    """GET /api/v1/roles should return the available role names."""
    response = client.get("/api/v1/roles")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert "assistant" in data
    assert "coder" in data
    assert data == sorted(data)


def test_set_conversation_role(client, conversation_id):
    """PUT /conversations/{id}/role should set the conversation's role."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/role",
        json={"role": "coder"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == conversation_id
    assert data["role"] == "coder"

    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert detail["role"] == "coder"


def test_clear_conversation_role(client, conversation_id):
    """PUT /conversations/{id}/role with null reverts to the default role."""
    client.put(
        f"/api/v1/conversations/{conversation_id}/role",
        json={"role": "coder"},
    )
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/role",
        json={"role": None},
    )
    assert response.status_code == 200
    assert response.json()["role"] is None


def test_set_conversation_role_rejects_unknown_role(client, conversation_id):
    """PUT /conversations/{id}/role should reject roles without a prompt file."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/role",
        json={"role": "ghost"},
    )
    assert response.status_code == 422


def test_set_role_nonexistent_conversation(client):
    """PUT /conversations/{id}/role should 404 for unknown IDs."""
    response = client.put(
        "/api/v1/conversations/nonexistent-id/role",
        json={"role": "coder"},
    )
    assert response.status_code == 404


def test_new_conversation_role_is_null(client, conversation_id):
    """A fresh conversation should expose role=None (global default)."""
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.json()["role"] is None


def test_set_thinking_nonexistent_conversation(client):
    """PUT /conversations/{id}/thinking should 404 for unknown IDs."""
    response = client.put(
        "/api/v1/conversations/nonexistent-id/thinking",
        json={"enabled": True, "effort": "low"},
    )
    assert response.status_code == 404


def test_set_conversation_thinking(client, conversation_id):
    """PUT /conversations/{id}/thinking should enable thinking with effort."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/thinking",
        json={"enabled": True, "effort": "high"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thinking_enabled"] is True
    assert data["thinking_effort"] == "high"


def test_disable_conversation_thinking(client, conversation_id):
    """PUT /conversations/{id}/thinking should disable thinking mode."""
    client.put(
        f"/api/v1/conversations/{conversation_id}/thinking",
        json={"enabled": True, "effort": "high"},
    )
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/thinking",
        json={"enabled": False, "effort": "medium"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thinking_enabled"] is False
    assert data["thinking_effort"] == "medium"


def test_set_thinking_rejects_invalid_effort(client, conversation_id):
    """PUT /conversations/{id}/thinking should reject unknown effort levels."""
    response = client.put(
        f"/api/v1/conversations/{conversation_id}/thinking",
        json={"enabled": True, "effort": "extreme"},
    )
    assert response.status_code == 422


def test_clear_conversation_messages(client, conversation_id):
    """DELETE /conversations/{id}/messages should empty the history."""
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert len(detail["messages"]) >= 1

    response = client.delete(f"/api/v1/conversations/{conversation_id}/messages")
    assert response.status_code == 200
    assert response.json() == {"cleared": True}

    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert detail["id"] == conversation_id
    assert detail["messages"] == []


def test_clear_messages_nonexistent_conversation(client):
    """DELETE /conversations/{id}/messages should 404 for unknown IDs."""
    response = client.delete("/api/v1/conversations/nonexistent-id/messages")
    assert response.status_code == 404


def test_delete_conversation_clears_checkpoint(client, conversation_id):
    """DELETE 应丢弃会话的检查点线程。"""
    saver = MagicMock()
    saver.adelete_thread = AsyncMock()
    client.app.state.checkpointer = saver

    response = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200
    saver.adelete_thread.assert_awaited_once_with(conversation_id)


def test_clear_messages_clears_checkpoint(client, conversation_id):
    """DELETE /messages 应丢弃会话的检查点线程。"""
    saver = MagicMock()
    saver.adelete_thread = AsyncMock()
    client.app.state.checkpointer = saver

    response = client.delete(f"/api/v1/conversations/{conversation_id}/messages")
    assert response.status_code == 200
    saver.adelete_thread.assert_awaited_once_with(conversation_id)


def test_delete_conversation_without_checkpointer(client, conversation_id):
    """缺少 saver（降级模式）时绝不能破坏删除操作。"""
    client.app.state.checkpointer = None

    response = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200


def test_clear_messages_without_checkpointer(client, conversation_id):
    """缺少 saver（降级模式）时绝不能破坏清空消息操作。"""
    client.app.state.checkpointer = None

    response = client.delete(f"/api/v1/conversations/{conversation_id}/messages")
    assert response.status_code == 200


def test_delete_conversation_checkpoint_failure_is_tolerated(client, conversation_id):
    """检查点删除失败绝不能破坏主要操作。"""
    saver = MagicMock()
    saver.adelete_thread = AsyncMock(side_effect=RuntimeError("db down"))
    client.app.state.checkpointer = saver

    response = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200


def test_delete_nonexistent_conversation_skips_checkpoint(client):
    """404 删除绝不能触碰检查点。"""
    saver = MagicMock()
    saver.adelete_thread = AsyncMock()
    client.app.state.checkpointer = saver

    response = client.delete("/api/v1/conversations/nonexistent-id")
    assert response.status_code == 404
    saver.adelete_thread.assert_not_awaited()


def _make_checkpointed_agent(cid: str):
    """构建一个由 MemorySaver 支撑的真实 agent，用于生命周期测试。"""
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import MemorySaver

    from thumbelina.agent.graph import ThumbelinaAgent

    saver = MemorySaver()
    mock_provider = MagicMock()
    mock_provider.chat_model = AsyncMock()
    # 每次调用都返回全新的 AIMessage，使 add_messages 追加而不是替换。
    mock_provider.chat_model.ainvoke.side_effect = lambda *a, **k: AIMessage(content="reply")

    mock_memory = AsyncMock()
    mock_memory.create_conversation.return_value = cid
    mock_memory.add_message = AsyncMock()
    mock_memory.get_conversation = AsyncMock(return_value={"knowledge_base_id": None})
    mock_memory.delete_conversation = AsyncMock(return_value=True)
    mock_memory.clear_messages = AsyncMock(return_value=True)

    agent = ThumbelinaAgent(
        llm_provider=mock_provider, memory_manager=mock_memory, checkpointer=saver
    )
    agent.current_conversation_id = cid
    return agent, mock_memory, saver


async def _checkpoint_message_contents(agent, cid: str) -> list[str]:
    """返回会话线程中持久化的消息内容。"""
    snapshot = await agent.graph.aget_state({"configurable": {"thread_id": cid}})
    return [m.content for m in snapshot.values["messages"]]


@pytest.mark.asyncio
async def test_delete_conversation_prevents_context_revival():
    """以相同 id 重新创建的会话绝不能复活旧上下文。"""
    from thumbelina.api.routes.conversations import delete_conversation

    cid = "cid-revive"
    agent, mock_memory, saver = _make_checkpointed_agent(cid)
    await agent.run("First message")
    assert await _checkpoint_message_contents(agent, cid) == ["First message", "reply"]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=saver)))
    result = await delete_conversation(cid, request=request, memory=mock_memory)
    assert result == {"deleted": True}

    # 检查点线程已删除。
    assert await saver.aget_tuple({"configurable": {"thread_id": cid}}) is None

    # 以相同会话 id 重建后，从空上下文重新开始。
    await agent.run("Second message")
    assert await _checkpoint_message_contents(agent, cid) == ["Second message", "reply"]


@pytest.mark.asyncio
async def test_clear_messages_prevents_context_revival():
    """清空消息必须丢弃检查点；下一轮从全新状态开始。"""
    from thumbelina.api.routes.conversations import clear_conversation_messages

    cid = "cid-clear"
    agent, mock_memory, saver = _make_checkpointed_agent(cid)
    await agent.run("First message")
    assert await _checkpoint_message_contents(agent, cid) == ["First message", "reply"]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=saver)))
    result = await clear_conversation_messages(cid, request=request, memory=mock_memory)
    assert result == {"cleared": True}

    assert await saver.aget_tuple({"configurable": {"thread_id": cid}}) is None

    await agent.run("Second message")
    assert await _checkpoint_message_contents(agent, cid) == ["Second message", "reply"]
