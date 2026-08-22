"""TrajectoryRecorder 单元测试(设计文档 §3.4/§3.5)。"""

from __future__ import annotations

import json

from thumbelina.agent.trajectory import (
    MAX_PAYLOAD_BYTES,
    TrajectoryRecorder,
    normalize_llm_usage,
)


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


class RaisingManager(FakeManager):
    async def add_trajectory_events(self, conversation_id: str, events: list[dict]) -> None:
        raise RuntimeError("db down")


async def test_write_failure_does_not_raise():
    """写入失败绝不向调用方传播(设计文档 §6:"绝不破坏聊天")。"""
    recorder = TrajectoryRecorder(RaisingManager())
    recorder.begin_turn("conv-1")
    await recorder.record_user("你好")  # must not raise
    await recorder.record_assistant("好")
    # 写入虽失败,但轮次与序列号状态仍按正常流程推进
    assert recorder.enabled is True


async def test_record_llm_usage():
    manager = FakeManager()
    recorder = TrajectoryRecorder(manager)
    recorder.begin_turn("conv-1")
    await recorder.record_llm_usage({"model": "mock", "prompt_tokens": 10, "cache_hit_tokens": 8})
    assert manager.events[0]["event_type"] == "llm_usage"
    assert json.loads(manager.events[0]["payload"])["cache_hit_tokens"] == 8


def test_normalize_llm_usage_deepseek_style():
    usage = normalize_llm_usage(
        {
            "model": "deepseek-chat",
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
            },
        }
    )
    assert usage == {
        "model": "deepseek-chat",
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "cache_hit_tokens": 80,
        "cache_miss_tokens": 20,
    }


def test_normalize_llm_usage_openai_details_style():
    usage = normalize_llm_usage(
        {
            "token_usage": {
                "prompt_tokens": 90,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 60},
            }
        }
    )
    assert usage == {
        "prompt_tokens": 90,
        "completion_tokens": 5,
        "cache_hit_tokens": 60,
        "cache_miss_tokens": 30,
    }


def test_normalize_llm_usage_anthropic_style():
    usage = normalize_llm_usage(
        {"usage": {"input_tokens": 200, "output_tokens": 30, "cache_read_input_tokens": 150}}
    )
    assert usage == {
        "prompt_tokens": 200,
        "completion_tokens": 30,
        "cache_hit_tokens": 150,
        "cache_miss_tokens": 50,
    }


def test_normalize_llm_usage_empty_and_garbage():
    assert normalize_llm_usage(None) == {}
    assert normalize_llm_usage({}) == {}
    assert normalize_llm_usage({"token_usage": "nope"}) == {}
