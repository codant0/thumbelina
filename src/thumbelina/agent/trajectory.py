"""轨迹记录器(设计文档 §3.4/§3.5)。

把每个对话轮次的用户消息、上下文注入、工具调用/结果、助手响应
静默写入 trajectory_events。任何失败仅记 warning,绝不干扰对话主流程。
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 65536


class TrajectoryRecorder:
    """按轮次累积并异步落盘轨迹事件。

    ``begin_turn`` 开启新轮次;此后每次 ``record_*`` 立即写一条事件
    (seq 递增保证轮次内顺序)。会话 id 为 None 或 manager 不提供
    ``add_trajectory_events`` 时整体降级为空操作。
    """

    def __init__(self, repository_manager) -> None:
        self._manager = repository_manager
        self._conversation_id: str | None = None
        self._turn_id: str | None = None
        self._seq = 0

    @property
    def enabled(self) -> bool:
        return self._manager is not None and hasattr(self._manager, "add_trajectory_events")

    def begin_turn(self, conversation_id: str | None) -> None:
        self._conversation_id = conversation_id
        self._turn_id = str(uuid4()) if conversation_id else None
        self._seq = 0

    async def record_user(self, content: str) -> None:
        await self._record("user", {"content": content})

    async def record_context(self, items: list[dict[str, str]]) -> None:
        await self._record("context", {"items": items})

    async def record_tool_call(self, tool: str, args: object, call_id: str) -> None:
        await self._record("tool_call", {"tool": tool, "args": args, "call_id": call_id})

    async def record_tool_result(self, call_id: str, content: str, is_error: bool) -> None:
        await self._record(
            "tool_result", {"call_id": call_id, "content": content, "is_error": is_error}
        )

    async def record_assistant(self, content: str, reasoning: str | None = None) -> None:
        await self._record("assistant", {"content": content, "reasoning": reasoning})

    async def _record(self, event_type: str, payload: dict) -> None:
        if not self.enabled or self._turn_id is None or not self._conversation_id:
            return
        try:
            serialized = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            serialized = json.dumps({"error": "serialize_failed"})
        if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            serialized = json.dumps(
                {"truncated": True, "preview": serialized[:2000]}, ensure_ascii=False
            )
        event = {
            "turn_id": self._turn_id,
            "seq": self._seq,
            "event_type": event_type,
            "payload": serialized,
        }
        self._seq += 1
        try:
            await self._manager.add_trajectory_events(self._conversation_id, [event])
        except Exception:
            logger.warning("Failed to record trajectory event", exc_info=True)