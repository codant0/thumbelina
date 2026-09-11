"""src/thumbelina/api/permission_broker.py — interrupt 审批请求与 WS 响应的桥（spec §5.3/§5.4）。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Pending:
    request_id: str
    conversation_id: str | None
    payload: dict[str, Any]
    future: asyncio.Future[list[dict[str, Any]]]
    created_at: float = field(default_factory=time.monotonic)
    timeout_handle: asyncio.TimerHandle | None = None


def _deny_all(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"call_id": c.get("call_id", ""), "approved": False} for c in payload.get("calls", [])]


class PermissionBroker:
    """按 request_id 结算；接受任意连接的响应；超时按全拒结算（spec §9 审批超时）。"""

    def __init__(self, timeout_seconds: float = 600.0) -> None:
        self._timeout = timeout_seconds
        self._pending: dict[str, _Pending] = {}
        self._early: dict[str, list[dict[str, Any]]] = {}  # 响应早于 wait 注册的缓存

    def register(self, conversation_id: str | None, payload: dict[str, Any]) -> str:
        request_id = payload.get("request_id") or f"perm-{time.monotonic_ns()}"
        payload = {**payload, "request_id": request_id}
        fut: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()
        pending = _Pending(request_id, conversation_id, payload, fut)
        if self._timeout > 0:
            pending.timeout_handle = asyncio.get_running_loop().call_later(
                self._timeout, self._on_timeout, request_id
            )
        self._pending[request_id] = pending
        return request_id

    def _on_timeout(self, request_id: str) -> None:
        pending = self._pending.get(request_id)
        if pending is not None and not pending.future.done():
            pending.future.set_result(_deny_all(pending.payload))

    async def wait(self, request_id: str) -> list[dict[str, Any]]:
        pending = self._pending.get(request_id)
        if pending is None:
            return self._early.pop(request_id, [])
        if request_id in self._early:  # 响应早到
            self._settle(pending, self._early.pop(request_id))
        try:
            return await pending.future
        finally:
            self._discard(request_id)

    def resolve(self, request_id: str, decisions: list[dict[str, Any]]) -> bool:
        pending = self._pending.get(request_id)
        if pending is None:
            return False  # 未知 request_id：不缓存（避免孤儿累积）
        if pending.future.done():
            return False
        self._settle(pending, list(decisions or []))
        return True

    def _settle(self, pending: _Pending, decisions: list[dict[str, Any]]) -> None:
        if pending.timeout_handle is not None:
            pending.timeout_handle.cancel()
        if not pending.future.done():
            pending.future.set_result(decisions)

    def pending_for(self, conversation_id: str | None) -> dict[str, Any] | None:
        for p in self._pending.values():
            if p.conversation_id == conversation_id and not p.future.done():
                return {"request_id": p.request_id, "calls": p.payload.get("calls", [])}
        return None

    def snapshot(self, conversation_id: str | None) -> dict[str, Any] | None:
        return self.pending_for(conversation_id)

    def clear_conversation(self, conversation_id: str | None) -> None:
        stale = [rid for rid, p in self._pending.items() if p.conversation_id == conversation_id]
        for rid in stale:
            self._discard(rid)

    def _discard(self, request_id: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is not None and pending.timeout_handle is not None:
            pending.timeout_handle.cancel()
        self._early.pop(request_id, None)
