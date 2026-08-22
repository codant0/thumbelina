"""轨迹记录器与 agent 主链路集成测试(设计文档 §3.4/§6)。

证明真实的 ``run()`` 通过 ``begin_turn → record_user → record_context →
record_assistant`` 在仓库中落下一轮完整的 user/context/assistant 事件。
LLM 使用与 ``tests/test_agent/test_graph.py`` 相同的无网络 mock provider。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from thumbelina.agent.graph import ThumbelinaAgent
from thumbelina.repository.manager import RepositoryManager


def _create_mock_provider():
    """无网络的 mock LLM provider(与 tests/test_agent/test_graph.py 一致)。"""
    mock_provider = MagicMock()
    # MagicMock(而非 AsyncMock)使 bind_tools() 返回模型自身,图总是绑定工具。
    mock_provider.chat_model = MagicMock()
    mock_provider.chat_model.ainvoke = AsyncMock(return_value=AIMessage(content="你好,小拇指仙!"))
    mock_provider.chat_model.bind_tools.return_value = mock_provider.chat_model
    return mock_provider


@pytest.fixture
def manager(tmp_path) -> RepositoryManager:
    m = RepositoryManager(f"sqlite:///{tmp_path}/trajectory.db")
    yield m
    m.close()


async def test_run_records_user_context_assistant_turn(manager: RepositoryManager):
    """一次真实 run() 应经 __init__ 自建记录器写入一轮三段式轨迹事件。"""
    conv_id = await manager.create_conversation(name="轨迹会话")
    # 走真实 __init__ 接线:repository_manager 传入后 agent 自行创建
    # TrajectoryRecorder(manager)。
    agent = ThumbelinaAgent(llm_provider=_create_mock_provider(), repository_manager=manager)
    agent.current_conversation_id = conv_id

    result = await agent.run("hello")

    assert result == "你好,小拇指仙!"
    page = await manager.get_trajectory_page(conv_id, page=1, page_size=20)
    assert page["total_turns"] == 1
    assert len(page["turns"]) == 1
    events = page["turns"][0]["events"]
    assert [e["event_type"] for e in events] == ["user", "context", "assistant"]
    assert events[0]["payload"]["content"] == "hello"
    assert events[1]["payload"]["items"] == []
    assert events[2]["payload"]["content"] == "你好,小拇指仙!"
    # 事件里携带的轮次 id 与序列号保持递增
    assert events[0]["seq"] == 0
    assert events[1]["seq"] == 1
    assert events[2]["seq"] == 2
    assert len({e["turn_id"] for e in events}) == 1


async def test_run_records_llm_usage_from_response_metadata(manager: RepositoryManager):
    """run() 应从最终响应的 response_metadata 提取用量并落库 llm_usage。"""
    conv_id = await manager.create_conversation(name="用量会话")
    provider = _create_mock_provider()
    provider.chat_model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="好",
            response_metadata={
                "model": "deepseek-chat",
                "token_usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 45,
                    "prompt_cache_hit_tokens": 900,
                    "prompt_cache_miss_tokens": 300,
                },
            },
        )
    )
    agent = ThumbelinaAgent(llm_provider=provider, repository_manager=manager)
    agent.current_conversation_id = conv_id

    await agent.run("hi")

    page = await manager.get_trajectory_page(conv_id, page=1, page_size=20)
    events = page["turns"][0]["events"]
    assert [e["event_type"] for e in events] == ["user", "context", "llm_usage", "assistant"]
    payload = events[2]["payload"]
    assert payload["cache_hit_tokens"] == 900
    assert payload["cache_miss_tokens"] == 300
    assert payload["prompt_tokens"] == 1200
    assert payload["model"] == "deepseek-chat"
