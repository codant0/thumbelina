"""Tests for rate limiter."""

from __future__ import annotations

import pytest

from thumbelina.security.rate_limit import RateLimiter


@pytest.fixture
def limiter():
    """Create a RateLimiter."""
    return RateLimiter(max_requests=3, window_seconds=60)


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_limiter_class_exists(self):
        """RateLimiter should be importable."""
        assert RateLimiter is not None

    def test_limiter_creates_instance(self):
        """Should create a RateLimiter."""
        l = RateLimiter(max_requests=10, window_seconds=60)
        assert l is not None

    def test_allow_request(self, limiter):
        """Should allow requests within limit."""
        assert limiter.is_allowed("user-1") is True

    def test_deny_exceeded_requests(self, limiter):
        """Should deny requests exceeding limit."""
        for _ in range(3):
            limiter.is_allowed("user-1")

        assert limiter.is_allowed("user-1") is False

    def test_different_keys_independent(self, limiter):
        """Different keys should have independent limits."""
        for _ in range(3):
            limiter.is_allowed("user-1")

        assert limiter.is_allowed("user-2") is True

    def test_reset_key(self, limiter):
        """Should be able to reset a key."""
        for _ in range(3):
            limiter.is_allowed("user-1")

        limiter.reset("user-1")
        assert limiter.is_allowed("user-1") is True

    def test_get_remaining(self, limiter):
        """Should return remaining requests."""
        assert limiter.get_remaining("user-1") == 3

        limiter.is_allowed("user-1")
        assert limiter.get_remaining("user-1") == 2
