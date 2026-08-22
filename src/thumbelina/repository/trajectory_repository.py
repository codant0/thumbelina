"""Trajectory audit-event repository(设计文档 §3)。

与 :class:`ConversationRepository` 共享同一 engine/SessionLocal,
避免 SQLite 内存库出现两份独立连接池。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from thumbelina.repository.models import TrajectoryEvent
from thumbelina.repository.repository import ConversationRepository

logger = logging.getLogger(__name__)


class TrajectoryRepository:
    """轨迹事件存取：写事件、判断是否存在、按轮次分页倒序读。"""

    def __init__(self, conversation_repository: ConversationRepository) -> None:
        self.engine = conversation_repository.engine
        self.SessionLocal = conversation_repository.SessionLocal

    def _get_session(self) -> Session:
        return self.SessionLocal()

    def _add_events_sync(self, conversation_id: str, events: list[dict[str, Any]]) -> None:
        with self._get_session() as session:
            for e in events:
                kwargs: dict[str, Any] = {
                    "conversation_id": conversation_id,
                    "turn_id": e["turn_id"],
                    "seq": e["seq"],
                    "event_type": e["event_type"],
                    "payload": e["payload"],
                }
                if e.get("created_at") is not None:
                    kwargs["created_at"] = e["created_at"]
                session.add(TrajectoryEvent(**kwargs))
            session.commit()

    async def add_events(self, conversation_id: str, events: list[dict[str, Any]]) -> None:
        return await asyncio.to_thread(self._add_events_sync, conversation_id, events)

    def _has_events_sync(self, conversation_id: str) -> bool:
        with self._get_session() as session:
            row = session.execute(
                select(TrajectoryEvent.id)
                .where(TrajectoryEvent.conversation_id == conversation_id)
                .limit(1)
            ).first()
            return row is not None

    async def has_events(self, conversation_id: str) -> bool:
        return await asyncio.to_thread(self._has_events_sync, conversation_id)

    def _list_turns_sync(
        self, conversation_id: str, page: int, page_size: int
    ) -> tuple[int, list[tuple[str, datetime]]]:
        with self._get_session() as session:
            subq = (
                select(
                    TrajectoryEvent.turn_id,
                    func.min(TrajectoryEvent.created_at).label("started_at"),
                )
                .where(TrajectoryEvent.conversation_id == conversation_id)
                .group_by(TrajectoryEvent.turn_id)
                .subquery()
            )
            total = session.execute(select(func.count()).select_from(subq)).scalar_one()
            rows = session.execute(
                select(subq.c.turn_id, subq.c.started_at)
                .order_by(subq.c.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return total, [(r.turn_id, r.started_at) for r in rows]

    async def list_turns(
        self, conversation_id: str, page: int, page_size: int
    ) -> tuple[int, list[tuple[str, datetime]]]:
        return await asyncio.to_thread(self._list_turns_sync, conversation_id, page, page_size)

    def _get_events_sync(self, turn_ids: list[str]) -> list[dict[str, Any]]:
        if not turn_ids:
            return []
        with self._get_session() as session:
            rows = session.execute(
                select(TrajectoryEvent)
                .where(TrajectoryEvent.turn_id.in_(turn_ids))
                .order_by(TrajectoryEvent.turn_id, TrajectoryEvent.seq)
            ).scalars().all()
        result: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload: Any = json.loads(r.payload)
            except (ValueError, TypeError):
                payload = {"raw": r.payload}
            result.append(
                {
                    "turn_id": r.turn_id,
                    "seq": r.seq,
                    "event_type": r.event_type,
                    "payload": payload,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return result

    async def get_events(self, turn_ids: list[str]) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_events_sync, turn_ids)