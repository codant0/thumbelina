"""TrajectoryRecorder 单元测试(设计文档 §3.4/§3.5)。"""
from __future__ import annotations

import json

from thumbelina.agent.trajectory import MAX_PAYLOAD_BYTES, TrajectoryRecorder


class FakeManager:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def add_trajectory_events(self, conversation_id: str, events: list[dict]) -> None:
        self.events.extend(events)


async def test_turn_events_sequenced():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_user("你好")
    await recorder.record_context([{"kind": "memory", "content": "记忆摘要"}])
    await recorder.record_tool_call("search", {"q": "x"}, "call-1")
    await recorder.record_tool_result("call-1", "结果", is_error=False)
    await recorder.record_assistant("好的", reasoning="思考")

    assert [e["event_type"] for e in manager.events] == [
        "user",
        "context",
        "tool_call",
        "tool_result",
        "assistant",
    ]
    assert [e["seq"] for e in manager.events] == [0, 1, 2, 3, 4]
    assert all(e["turn_id"] == manager.events[0]["turn_id"] for e in manager.events)
    assert json.loads(manager.events[2]["payload"])["tool"] == "search"


async def test_disabled_without_manager_method():
    class EmptyManager:
        pass

    recorder = TrajectoryRecorder(EmptyManager())
    recorder.begin_turn("conv-1")
    await recorder.record_user("你好")
    assert recorder.enabled is False


async def test_records_nothing_without_begin_turn():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    await recorder.record_user("你好")
    assert manager.events == []


async def test_truncates_oversized_payload():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_user("x" * (MAX_PAYLOAD_BYTES * 2))
    payload = json.loads(manager.events[0]["payload"])
    assert payload.get("truncated") is True
    assert "preview" in payload


async def test_serialize_failure_falls_back():
    class BadObject:
        def __str__(self) -> str:  # type: ignore[override]
            raise RuntimeError("boom")

    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_tool_call("boom", {"arg": BadObject()}, "call-1")
    payload = json.loads(manager.events[0]["payload"])
    assert payload == {"error": "serialize_failed"}