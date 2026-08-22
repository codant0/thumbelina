"""TrajectoryEvent 模型建表与字段测试(设计文档 §3.1)。"""
from __future__ import annotations

from sqlalchemy import inspect as sa_inspect

from thumbelina.repository.db import create_db_engine, init_db


def test_trajectory_events_table_created(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path}/trajectory.db")
    session_factory = init_db(engine)

    inspector = sa_inspect(engine)
    assert "trajectory_events" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("trajectory_events")}
    assert cols == {
        "id",
        "conversation_id",
        "turn_id",
        "seq",
        "event_type",
        "payload",
        "created_at",
    }

    from thumbelina.repository.models import TrajectoryEvent

    with session_factory() as session:
        event = TrajectoryEvent(
            conversation_id="conv-1",
            turn_id="turn-1",
            seq=0,
            event_type="user",
            payload='{"content": "hello"}',
        )
        session.add(event)
        session.commit()
        row = session.get(TrajectoryEvent, event.id)
        assert row.turn_id == "turn-1"
        assert row.seq == 0
        assert row.event_type == "user"

    engine.dispose()