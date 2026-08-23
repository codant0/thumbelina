"""TrajectoryRepository 与 RepositoryManager 轨迹方法测试(设计文档 §3)。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from thumbelina.repository.manager import RepositoryManager


@pytest.fixture
def manager(tmp_path) -> RepositoryManager:
    m = RepositoryManager(f"sqlite:///{tmp_path}/trajectory.db")
    yield m
    m.close()


async def _seed(manager: RepositoryManager, conv_id: str) -> None:
    """三个轮次 t1(最早)/t2/t3(最新),每轮 user+assistant 两个事件。"""
    base = datetime(2026, 8, 20, 10, 0, 0)
    for i, turn in enumerate(["t1", "t2", "t3"]):
        events = [
            {
                "turn_id": turn,
                "seq": 0,
                "event_type": "user",
                "payload": json.dumps({"content": f"msg-{i}"}),
                "created_at": base + timedelta(minutes=i),
            },
            {
                "turn_id": turn,
                "seq": 1,
                "event_type": "assistant",
                "payload": json.dumps({"content": f"reply-{i}"}),
                "created_at": base + timedelta(minutes=i, seconds=5),
            },
        ]
        await manager.add_trajectory_events(conv_id, events)


async def test_has_trajectory(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    assert await manager.has_trajectory(conv_id) is False
    await manager.add_trajectory_events(
        conv_id,
        [{"turn_id": "t1", "seq": 0, "event_type": "user", "payload": "{}"}],
    )
    assert await manager.has_trajectory(conv_id) is True


async def test_page_newest_first_with_pagination(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    await _seed(manager, conv_id)

    page1 = await manager.get_trajectory_page(conv_id, page=1, page_size=2)
    assert page1["total_turns"] == 3
    assert [t["turn_id"] for t in page1["turns"]] == ["t3", "t2"]
    assert "legacy" not in page1["turns"][0]
    assert [e["event_type"] for e in page1["turns"][0]["events"]] == ["user", "assistant"]
    assert page1["turns"][0]["events"][0]["payload"] == {"content": "msg-2"}

    page2 = await manager.get_trajectory_page(conv_id, page=2, page_size=2)
    assert [t["turn_id"] for t in page2["turns"]] == ["t1"]


async def test_events_ordered_by_seq(manager: RepositoryManager):
    conv_id = await manager.create_conversation(name="会话A")
    await manager.add_trajectory_events(
        conv_id,
        [
            {"turn_id": "t1", "seq": 1, "event_type": "assistant", "payload": "{}"},
            {"turn_id": "t1", "seq": 0, "event_type": "user", "payload": "{}"},
        ],
    )
    page = await manager.get_trajectory_page(conv_id, page=1, page_size=10)
    assert [e["event_type"] for e in page["turns"][0]["events"]] == ["user", "assistant"]


async def test_cache_stats_aggregates_llm_usage(manager: RepositoryManager):
    """跨会话聚合最近 limit 条 llm_usage 的缓存命中 token。"""
    conv_a = await manager.create_conversation(name="会话A")
    conv_b = await manager.create_conversation(name="会话B")
    base = datetime(2026, 8, 21, 10, 0, 0)

    def usage(turn: str, hit: int, miss: int, minute: int) -> dict:
        return {
            "turn_id": turn,
            "seq": 0,
            "event_type": "llm_usage",
            "payload": json.dumps(
                {
                    "model": "m",
                    "prompt_tokens": hit + miss,
                    "cache_hit_tokens": hit,
                    "cache_miss_tokens": miss,
                }
            ),
            "created_at": base + timedelta(minutes=minute),
        }

    await manager.add_trajectory_events(
        conv_a, [usage("a1", 900, 300, 1), usage("a2", 100, 500, 2)]
    )
    # 缺少缓存字段的事件不计入汇总
    await manager.add_trajectory_events(
        conv_b,
        [
            usage("b1", 0, 0, 0),  # 排在最早,不干扰 limit 断言
            {
                "turn_id": "b2",
                "seq": 0,
                "event_type": "llm_usage",
                "payload": json.dumps({"model": "m"}),
                "created_at": base + timedelta(minutes=4),
            },
        ],
    )

    stats = await manager.get_cache_stats()
    assert stats["hit_tokens"] == 1000
    assert stats["miss_tokens"] == 800
    assert stats["turns"] == 3

    # limit 生效:最近 2 条为 b2(无缓存字段)与 a2(100/500)
    stats2 = await manager.get_cache_stats(limit=2)
    assert stats2["hit_tokens"] == 100
    assert stats2["miss_tokens"] == 500
    assert stats2["turns"] == 1

    # 按会话过滤:只统计该会话自身的事件
    stats_a = await manager.get_cache_stats(conversation_id=conv_a)
    assert stats_a["hit_tokens"] == 1000
    assert stats_a["miss_tokens"] == 800
    assert stats_a["turns"] == 2
    stats_b = await manager.get_cache_stats(conversation_id=conv_b)
    assert stats_b["hit_tokens"] == 0
    assert stats_b["miss_tokens"] == 0
    assert stats_b["turns"] == 1
    # 无任何 llm_usage 事件的会话返回全零
    conv_c = await manager.create_conversation(name="会话C")
    stats_c = await manager.get_cache_stats(conversation_id=conv_c)
    assert stats_c == {"hit_tokens": 0, "miss_tokens": 0, "turns": 0}
