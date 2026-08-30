"""Tests for scheduler domain models (design §3/§4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import pytest

from thumbelina.scheduler import models
from thumbelina.scheduler.models import (
    DeliveryChannel,
    ScheduledTask,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    TriggerKind,
)


class TestTaskStatus:
    """TaskStatus covers the legacy four values plus the D10 additions."""

    def test_is_strenum(self):
        """TaskStatus should be a string enum."""
        assert issubclass(TaskStatus, StrEnum)

    def test_legacy_members_unchanged(self):
        """The four legacy members keep their exact values."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_new_members(self):
        """FAILED/PAUSED/MISSED exist with lowercase values."""
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.PAUSED == "paused"
        assert TaskStatus.MISSED == "missed"

    def test_member_set(self):
        """The enum exposes exactly the seven designed members."""
        assert {s.name for s in TaskStatus} == {
            "PENDING",
            "RUNNING",
            "COMPLETED",
            "CANCELLED",
            "FAILED",
            "PAUSED",
            "MISSED",
        }
        assert len(TaskStatus) == 7

    def test_values_are_lowercase(self):
        """Every member value is the lowercase form of its name."""
        for status in TaskStatus:
            assert status.value == status.name.lower()


class TestTriggerKind:
    """TriggerKind models once vs cron triggers."""

    def test_member_set(self):
        """The enum exposes exactly ONCE and CRON."""
        assert {t.name: t.value for t in TriggerKind} == {"ONCE": "once", "CRON": "cron"}


class TestDeliveryChannel:
    """DeliveryChannel models web/wechat/qq delivery."""

    def test_member_set(self):
        """The enum exposes exactly WEB, WECHAT and QQ."""
        assert {c.name: c.value for c in DeliveryChannel} == {
            "WEB": "web",
            "WECHAT": "wechat",
            "QQ": "qq",
        }


class TestTaskEventType:
    """TaskEventType models the structured task lifecycle events."""

    def test_member_set(self):
        """The enum exposes exactly the six designed event types."""
        assert {e.name: e.value for e in TaskEventType} == {
            "CREATED": "task.created",
            "DUE": "task.due",
            "COMPLETED": "task.completed",
            "FAILED": "task.failed",
            "MISSED": "task.missed",
            "CANCELLED": "task.cancelled",
        }

    def test_values_are_dotted(self):
        """Every event value is namespaced under ``task.``."""
        for event_type in TaskEventType:
            assert event_type.value.startswith("task.")


class TestScheduledTaskCompat:
    """v1 construction stays v1-equivalent (brief compat assertion)."""

    def test_two_arg_construction(self):
        """ScheduledTask(description=..., scheduled_time=...) yields an
        ONCE/web/PENDING/notify task like v1."""
        dt = datetime(2026, 8, 30, 9, 0, 0)
        task = ScheduledTask(description="x", scheduled_time=dt)

        assert task.trigger is TriggerKind.ONCE
        assert task.channel is DeliveryChannel.WEB
        assert task.status is TaskStatus.PENDING
        assert task.mode == "notify"
        assert task.scheduled_time == dt

    def test_v1_fields_keep_defaults(self):
        """The six v1 fields keep their v1 defaults."""
        dt = datetime(2026, 8, 30, 9, 0, 0)
        task = ScheduledTask(id="t1", description="Test", scheduled_time=dt)

        assert task.id == "t1"
        assert task.description == "Test"
        assert task.scheduled_time == dt
        assert task.status is TaskStatus.PENDING
        assert task.result is None
        assert task.condition is None

    def test_id_auto_generated(self):
        """id should default to a uuid4 string."""
        task = ScheduledTask(description="x")
        assert uuid.UUID(task.id)  # raises if not a valid UUID

    def test_scheduled_time_defaults_to_now(self):
        """scheduled_time should default to the current time (v1 behavior)."""
        before = datetime.now()
        task = ScheduledTask(description="x")
        after = datetime.now()

        assert task.scheduled_time is not None
        assert before <= task.scheduled_time <= after

    def test_new_fields_default(self):
        """All v2 fields carry designed defaults."""
        task = ScheduledTask(description="x")

        assert task.trigger is TriggerKind.ONCE
        assert task.cron_expr is None
        assert task.next_run is None
        assert task.last_run is None
        assert task.channel is DeliveryChannel.WEB
        assert task.content == ""
        assert task.mode == "notify"
        assert task.result is None
        assert task.error is None
        assert task.source == "agent"
        assert task.conversation_id is None
        assert task.created_at is not None
        assert task.updated_at is not None

    def test_cron_task_scheduled_time_can_be_none(self):
        """scheduled_time is nullable for CRON tasks (design §4)."""
        task = ScheduledTask(
            description="x",
            trigger=TriggerKind.CRON,
            cron_expr="*/5 * * * *",
            scheduled_time=None,
        )

        assert task.trigger is TriggerKind.CRON
        assert task.cron_expr == "*/5 * * * *"
        assert task.scheduled_time is None

    def test_condition_still_stored(self):
        """condition field semantics unchanged (v1 condition tasks)."""
        task = ScheduledTask(
            description="Watch file",
            scheduled_time=datetime(2026, 8, 30, 9, 0, 0),
            condition="file_changed:/tmp/data.csv",
        )
        assert task.condition == "file_changed:/tmp/data.csv"


def _event_kwargs() -> dict[str, object]:
    """Keyword arguments covering every required TaskEvent key."""
    return {
        "type": TaskEventType.COMPLETED,
        "task_id": "task-1",
        "trigger": TriggerKind.ONCE,
        "channel": DeliveryChannel.WEB,
        "content": "hello",
    }


class TestTaskEvent:
    """TaskEvent required keys and defaults (design §3)."""

    def test_required_keys_construction(self):
        """TaskEvent can be built from its required keys alone."""
        event = TaskEvent(
            type=TaskEventType.DUE,
            task_id="task-1",
            trigger=TriggerKind.ONCE,
            channel=DeliveryChannel.WEB,
            content="hello",
        )

        assert event.type is TaskEventType.DUE
        assert event.task_id == "task-1"
        assert event.trigger is TriggerKind.ONCE
        assert event.channel is DeliveryChannel.WEB
        assert event.content == "hello"
        assert event.payload == {}
        assert uuid.UUID(event.id)  # id auto-generated as uuid4
        assert isinstance(event.fired_at, datetime)

    @pytest.mark.parametrize("missing", ["type", "task_id", "trigger", "channel", "content"])
    def test_missing_required_key_raises(self, missing):
        """Omitting any required key raises TypeError."""
        kwargs = _event_kwargs()
        del kwargs[missing]

        with pytest.raises(TypeError):
            TaskEvent(**kwargs)  # type: ignore[arg-type]

    def test_explicit_id_fired_at_payload(self):
        """Explicit id/fired_at/payload round-trip unchanged."""
        fired = datetime(2026, 8, 30, 9, 0, 0)
        event = TaskEvent(
            id="evt-1",
            type=TaskEventType.MISSED,
            task_id="task-1",
            fired_at=fired,
            trigger=TriggerKind.CRON,
            channel=DeliveryChannel.WECHAT,
            content="brief",
            payload={"scheduled_for": "2026-08-30T09:00:00", "policy": "mark"},
        )

        assert event.id == "evt-1"
        assert event.fired_at == fired
        assert event.payload == {"scheduled_for": "2026-08-30T09:00:00", "policy": "mark"}


class TestReExport:
    """scheduler.py re-exports keep the legacy import paths working."""

    def test_scheduler_module_reexports_models(self):
        """from thumbelina.scheduler.scheduler import ScheduledTask, TaskStatus works."""
        from thumbelina.scheduler.scheduler import ScheduledTask, TaskStatus  # noqa: PLC0415

        assert ScheduledTask is models.ScheduledTask
        assert TaskStatus is models.TaskStatus

    def test_legacy_single_name_import(self):
        """from thumbelina.scheduler.scheduler import ScheduledTask works (app.py:57)."""
        from thumbelina.scheduler.scheduler import ScheduledTask  # noqa: PLC0415

        assert ScheduledTask is models.ScheduledTask
