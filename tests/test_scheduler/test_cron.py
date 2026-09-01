"""Tests for the cron trigger (design §6)."""

from __future__ import annotations

from datetime import datetime

import pytest

from thumbelina.scheduler.cron import CronTrigger, validate_cron


class TestNextAfterBasics:
    """next_after computes the next fire time from a local naive start."""

    def test_every_five_minutes_from_0902(self):
        """``*/5 * * * *`` from 09:02 fires at 09:05."""
        trigger = CronTrigger("*/5 * * * *")

        nxt = trigger.next_after(datetime(2026, 8, 30, 9, 2, 0))
        assert nxt == datetime(2026, 8, 30, 9, 5, 0)

    def test_daily_at_9_crosses_day(self):
        """``0 9 * * *`` from 10:00 fires at 09:00 the next day."""
        trigger = CronTrigger("0 9 * * *")

        nxt = trigger.next_after(datetime(2026, 8, 30, 10, 0, 0))
        assert nxt == datetime(2026, 8, 31, 9, 0, 0)

    def test_day_31_lands_on_january_31(self):
        """``0 0 31 * *`` from mid-January fires on Jan 31."""
        trigger = CronTrigger("0 0 31 * *")

        nxt = trigger.next_after(datetime(2026, 1, 15, 0, 0, 0))
        assert nxt == datetime(2026, 1, 31, 0, 0, 0)

    def test_day_31_skips_february(self):
        """``0 0 31 * *`` after Jan 31 jumps over February to Mar 31."""
        trigger = CronTrigger("0 0 31 * *")

        nxt = trigger.next_after(datetime(2026, 1, 31, 0, 0, 0))
        assert nxt == datetime(2026, 3, 31, 0, 0, 0)

    def test_day_31_from_mid_february(self):
        """``0 0 31 * *`` from within February lands on Mar 31."""
        trigger = CronTrigger("0 0 31 * *")

        nxt = trigger.next_after(datetime(2026, 2, 10, 12, 0, 0))
        assert nxt == datetime(2026, 3, 31, 0, 0, 0)

    def test_day_31_skips_30_day_months(self):
        """``0 0 31 * *`` from April 1 skips April (30 days) to May 31."""
        trigger = CronTrigger("0 0 31 * *")

        nxt = trigger.next_after(datetime(2026, 4, 1, 0, 0, 0))
        assert nxt == datetime(2026, 5, 31, 0, 0, 0)

    def test_result_is_local_naive(self):
        """Fire times are naive datetimes (local-naive convention, no DST)."""
        trigger = CronTrigger("*/5 * * * *")

        nxt = trigger.next_after(datetime(2026, 8, 30, 9, 2, 0))
        assert nxt.tzinfo is None


class TestStrictlyAfter:
    """next_after is strictly greater than the given instant."""

    def test_start_on_fire_time_not_swallowed(self):
        """A start exactly on 09:00 yields tomorrow's 09:00, not today's."""
        trigger = CronTrigger("0 9 * * *")

        nxt = trigger.next_after(datetime(2026, 8, 30, 9, 0, 0))
        assert nxt == datetime(2026, 8, 31, 9, 0, 0)

    def test_five_minute_boundary_not_swallowed(self):
        """A start exactly on 09:05 yields 09:10 for ``*/5``."""
        trigger = CronTrigger("*/5 * * * *")

        nxt = trigger.next_after(datetime(2026, 8, 30, 9, 5, 0))
        assert nxt == datetime(2026, 8, 30, 9, 10, 0)

    def test_next_after_now_is_strictly_future(self):
        """next_after(now) with the wall clock is strictly greater than now."""
        now = datetime.now().replace(microsecond=0)
        nxt = CronTrigger("* * * * *").next_after(now)

        assert nxt > now


class TestDescriptors:
    """@descriptors are accepted and behave like their expanded form."""

    def test_daily_equals_expanded_form(self):
        """@daily fires identically to ``0 0 * * *``."""
        start = datetime(2026, 8, 30, 7, 30, 0)

        assert CronTrigger("@daily").next_after(start) == datetime(2026, 8, 31, 0, 0, 0)
        assert CronTrigger("@daily").next_after(start) == CronTrigger("0 0 * * *").next_after(start)

    @pytest.mark.parametrize(
        "expr",
        ["@hourly", "@daily", "@midnight", "@weekly", "@monthly", "@yearly"],
    )
    def test_descriptor_accepted_and_future(self, expr):
        """All six supported descriptors parse and yield a future fire time."""
        start = datetime(2026, 8, 30, 9, 0, 0)

        assert CronTrigger(expr).next_after(start) > start


class TestInvalidExpressions:
    """Malformed expressions raise ValueError carrying the original text."""

    @pytest.mark.parametrize(
        "expr",
        [
            "0 0 9 * * *",  # 6 fields — seconds unsupported
            "* * *",  # too few fields
            "",  # empty string
            "not a cron",  # garbage words
            "garbage",  # single token
        ],
    )
    def test_constructor_raises_value_error(self, expr):
        with pytest.raises(ValueError):
            CronTrigger(expr)

    def test_message_contains_original_expression(self):
        with pytest.raises(ValueError) as excinfo:
            CronTrigger("0 9 * * * *")

        assert "0 9 * * * *" in str(excinfo.value)

    def test_message_mentions_invalid_cron(self):
        with pytest.raises(ValueError) as excinfo:
            CronTrigger("")

        assert "Invalid cron expression" in str(excinfo.value)


class TestValidateCron:
    """validate_cron returns None for valid, an error message for invalid."""

    @pytest.mark.parametrize(
        "expr",
        ["*/5 * * * *", "0 9 * * *", "0 0 31 * *", "@daily", "@weekly", "  0 9 * * *  "],
    )
    def test_valid_returns_none(self, expr):
        assert validate_cron(expr) is None

    def test_invalid_returns_message_not_raise(self):
        message = validate_cron("* * *")

        assert isinstance(message, str)
        assert message

    def test_invalid_message_contains_expression(self):
        message = validate_cron("0 0 9 * * *")

        assert message is not None
        assert "0 0 9 * * *" in message


class TestDescribe:
    """describe() returns the expression as the trigger's display form."""

    def test_returns_expression_verbatim(self):
        assert CronTrigger("*/5 * * * *").describe() == "*/5 * * * *"

    def test_descriptor_preserved(self):
        assert CronTrigger("@daily").describe() == "@daily"


class TestCroniterMissing:
    """croniter 缺失时的优雅降级（monkeypatch 模拟 ImportError 场景）：
    validate_cron 拒绝一切表达式并给出安装提示，CronTrigger 抛 ValueError——
    上游（工具 Error: 文案 / API 422 / recover 跳过水合）据此降级，而不是
    让 import 崩掉整个服务。"""

    def test_validate_cron_rejects_everything_with_hint(self, monkeypatch):
        import thumbelina.scheduler.cron as cron_module

        monkeypatch.setattr(cron_module, "CRONITER_AVAILABLE", False)
        message = validate_cron("*/5 * * * *")

        assert message is not None
        assert "croniter is not installed" in message

    def test_cron_trigger_raises_with_hint(self, monkeypatch):
        import thumbelina.scheduler.cron as cron_module

        monkeypatch.setattr(cron_module, "CRONITER_AVAILABLE", False)
        with pytest.raises(ValueError, match="croniter is not installed"):
            CronTrigger("*/5 * * * *")
