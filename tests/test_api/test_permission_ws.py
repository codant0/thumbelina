"""WS 审批协议测试（Task 12, spec §5.4）。

覆盖 permission_request 广播、permission_response 上行结算、未知 request_id
的 error code 分流、pending 期间的 busy 守卫，以及 pending 快照下行
（``get_pending_approval`` 与 ``switch_conversation`` ack）。

这些测试直接驱动 ``mock_agent.stream``（conftest 的 client fixture）模拟
Task 10 的 ``permission_request`` 事件 + ``approval_waiter`` 阻塞语义，不依赖
真实 LangGraph interrupt —— WS 层契约（帧形状、错误码、守卫顺序）是被测对象。
"""

from __future__ import annotations

import asyncio

from thumbelina.api.permission_broker import PermissionBroker


def _install_approval_stream(client, *, calls=None, request_id="req-1"):
    """让 agent.stream 发一次 permission_request 并阻塞在 approval_waiter。

    返回收集决策的列表：waiter 返回后 stream 把结果映射成 tool_event
    （verdict=allowed/denied），再 done。
    """
    calls = calls or [
        {
            "call_id": "c1",
            "name": "run_shell",
            "args": {"command": "rm -rf /tmp/x"},
            "risk": "dangerous",
            "reason": "dangerous.rm_root",
        }
    ]
    recorded: list[list[dict]] = []

    async def _stream(message, *args, approval_waiter=None, **kwargs):
        payload = {"request_id": request_id, "calls": calls}
        yield {"type": "permission_request", "request_id": request_id, "calls": calls}
        decisions = await approval_waiter(request_id, payload)
        recorded.append(decisions)
        approved = {d.get("call_id"): bool(d.get("approved")) for d in decisions}
        for call in calls:
            yield {
                "type": "tool_start",
                "call_id": call["call_id"],
                "name": call["name"],
                "args": call["args"],
                "args_truncated": False,
                "verdict": "confirmed" if approved.get(call["call_id"]) else "denied",
            }
            yield {
                "type": "tool_end",
                "call_id": call["call_id"],
                "duration_ms": 1,
                "is_error": not approved.get(call["call_id"]),
                "result_preview": "ok" if approved.get(call["call_id"]) else "Error: 权限拒绝",
                "result_truncated": False,
                "verdict": "confirmed" if approved.get(call["call_id"]) else "denied",
            }
        yield {"type": "content", "text": "handled"}

    client.app.state.agent.stream = _stream
    return recorded


def _recv_until(ws, key, max_messages: int = 20) -> tuple[dict, list[dict]]:
    """收帧直到某个顶层键出现，返回（命中帧，全部帧）。"""
    seen: list[dict] = []
    for _ in range(max_messages):
        frame = ws.receive_json()
        seen.append(frame)
        if key in frame:
            return frame, seen
    raise AssertionError(f"frame with key {key!r} not received; got {seen}")


def test_broker_installed_on_app_state(client):
    """lifespan 应装配 PermissionBroker（默认超时 600s）。"""
    broker = client.app.state.permission_broker
    assert isinstance(broker, PermissionBroker)
    assert broker._timeout == 600.0


def test_permission_request_broadcast_and_response(client):
    """permission_request 下行 → permission_response 上行 → 合成拒绝 tool_event。"""
    recorded = _install_approval_stream(client)

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "rm it", "conversation_id": "test-conv-id"})
        frame, _ = _recv_until(ws, "permission_request")
        assert frame["conversation_id"] == "test-conv-id"
        assert frame["permission_request"]["request_id"] == "req-1"
        assert frame["permission_request"]["calls"][0]["call_id"] == "c1"

        ws.send_json(
            {
                "permission_response": {
                    "request_id": "req-1",
                    "decisions": [{"call_id": "c1", "approved": False}],
                }
            }
        )

        done, frames = _recv_until(ws, "done")
        assert done["done"] is True
        tool_events = [f["tool_event"] for f in frames if "tool_event" in f]
        assert tool_events, f"no tool_event frames: {frames}"
        assert all(e.get("verdict") == "denied" for e in tool_events)

    assert recorded == [[{"call_id": "c1", "approved": False}]]


def test_unknown_request_returns_error_code(client):
    """未知 request_id → error 帧带 code，且不影响后续正常消息。"""
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"permission_response": {"request_id": "nope", "decisions": []}})
        frame = ws.receive_json()
        assert frame["code"] == "permission_unknown_request"
        assert "error" in frame

        # 当轮未被终结:后续普通消息照常生成(conftest 默认 stream)。
        ws.send_json({"message": "hello", "conversation_id": "test-conv-id"})
        done, _ = _recv_until(ws, "done")
        assert done["done"] is True


def test_busy_pending_approval(client):
    """pending 审批期间发普通消息 → busy_pending_approval，并仍能收响应。"""
    recorded = _install_approval_stream(client)

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "rm it", "conversation_id": "test-conv-id"})
        _recv_until(ws, "permission_request")

        ws.send_json({"message": "another one", "conversation_id": "test-conv-id"})
        busy = ws.receive_json()
        assert busy["code"] == "busy_pending_approval"
        assert busy["conversation_id"] == "test-conv-id"

        # 主循环仍活着:审批响应照常结算。
        ws.send_json(
            {
                "permission_response": {
                    "request_id": "req-1",
                    "decisions": [{"call_id": "c1", "approved": True}],
                }
            }
        )
        done, _ = _recv_until(ws, "done")
        assert done["done"] is True

    assert recorded == [[{"call_id": "c1", "approved": True}]]


def test_get_pending_approval_snapshot(client):
    """get_pending_approval 与 switch_conversation ack 都带 pending 快照。"""
    _install_approval_stream(client)

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "rm it", "conversation_id": "test-conv-id"})
        _recv_until(ws, "permission_request")

        ws.send_json({"get_pending_approval": "test-conv-id"})
        frame = ws.receive_json()
        assert frame["conversation_id"] == "test-conv-id"
        assert frame["pending_approval"]["request_id"] == "req-1"
        assert frame["pending_approval"]["calls"][0]["call_id"] == "c1"

        ws.send_json({"switch_conversation": "test-conv-id"})
        ack, _ = _recv_until(ws, "conversation_switched")
        assert ack["pending_approval"]["request_id"] == "req-1"

        # 无 pending 的会话查询回 null。
        ws.send_json({"get_pending_approval": "other-conv"})
        empty = ws.receive_json()
        assert empty["pending_approval"] is None

        ws.send_json(
            {
                "permission_response": {
                    "request_id": "req-1",
                    "decisions": [{"call_id": "c1", "approved": False}],
                }
            }
        )
        done, _ = _recv_until(ws, "done")
        assert done["done"] is True


def test_waiter_denies_all_without_broker(client, monkeypatch):
    """无 broker 的防御路径：waiter 直接全拒结算（不挂死）。"""
    from thumbelina.api.websocket import _make_waiter

    waiter = _make_waiter(None, "cid")
    decisions = asyncio.run(
        waiter("req-x", {"request_id": "req-x", "calls": [{"call_id": "c1"}, {"call_id": "c2"}]})
    )
    assert decisions == [
        {"call_id": "c1", "approved": False},
        {"call_id": "c2", "approved": False},
    ]
