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
    assert page1["turns"][0]["legacy"] is False
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