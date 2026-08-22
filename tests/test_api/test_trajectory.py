"""轨迹 API 测试(设计文档 §4)。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thumbelina.api.routes.trajectory import router
from thumbelina.repository.manager import RepositoryManager


@pytest.fixture
def trajectory_client(tmp_path: Path):
    manager = RepositoryManager(f"sqlite:///{tmp_path}/trajectory.db")
    app = FastAPI()
    app.state.repository_manager = manager
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client, manager
    manager.close()


async def _seed_events(manager: RepositoryManager, conv_id: str) -> None:
    base = datetime(2026, 8, 20, 10, 0, 0)
    for i, turn in enumerate(["t1", "t2", "t3"]):
        await manager.add_trajectory_events(
            conv_id,
            [
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
            ],
        )


async def test_404_unknown_conversation(trajectory_client):
    client, _ = trajectory_client
    res = client.get("/api/v1/trajectory/unknown-id")
    assert res.status_code == 404


async def test_trajectory_pagination_newest_first(trajectory_client):
    client, manager = trajectory_client
    conv_id = await manager.create_conversation(name="会话A")
    await _seed_events(manager, conv_id)

    res = client.get(f"/api/v1/trajectory/{conv_id}?page=1&page_size=2")
    assert res.status_code == 200
    data = res.json()
    assert "legacy" not in data
    assert data["conversation_name"] == "会话A"
    assert data["total_turns"] == 3
    assert [t["turn_id"] for t in data["turns"]] == ["t3", "t2"]
    assert data["turns"][0]["events"][0]["payload"] == {"content": "msg-2"}

    res2 = client.get(f"/api/v1/trajectory/{conv_id}?page=2&page_size=2")
    assert [t["turn_id"] for t in res2.json()["turns"]] == ["t1"]


async def test_message_fallback_synthesis(trajectory_client):
    """无轨迹事件的会话:仅合成 user/assistant 文本轮次,无 legacy 标记。"""
    client, manager = trajectory_client
    conv_id = await manager.create_conversation(name="旧会话")
    await manager.add_message(conv_id, "user", "你好")
    await manager.add_message(conv_id, "assistant", "在的")

    res = client.get(f"/api/v1/trajectory/{conv_id}")
    assert res.status_code == 200
    data = res.json()
    assert "legacy" not in data
    assert data["total_turns"] == 1
    turn = data["turns"][0]
    assert "legacy" not in turn
    assert [e["event_type"] for e in turn["events"]] == ["user", "assistant"]
    assert turn["events"][0]["payload"] == {"content": "你好"}


async def test_validation_errors(trajectory_client):
    client, _ = trajectory_client
    res = client.get("/api/v1/trajectory/x?page=0")
    assert res.status_code == 422
    res = client.get("/api/v1/trajectory/x?page_size=101")
    assert res.status_code == 422


async def test_cache_stats_endpoint(trajectory_client):
    """GET /trajectory/cache-stats 返回聚合的缓存命中统计。"""
    client, manager = trajectory_client
    conv_id = await manager.create_conversation(name="统计会话")
    await manager.add_trajectory_events(
        conv_id,
        [
            {
                "turn_id": "t1",
                "seq": 0,
                "event_type": "llm_usage",
                "payload": json.dumps({"cache_hit_tokens": 900, "cache_miss_tokens": 300}),
                "created_at": datetime(2026, 8, 21, 10, 0, 0),
            },
            {
                "turn_id": "t2",
                "seq": 0,
                "event_type": "llm_usage",
                "payload": json.dumps({"cache_hit_tokens": 100, "cache_miss_tokens": 500}),
                "created_at": datetime(2026, 8, 21, 10, 1, 0),
            },
        ],
    )

    resp = client.get("/api/v1/trajectory/cache-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hit_tokens"] == 1000
    assert data["miss_tokens"] == 800
    assert data["turns"] == 2
