"""Rate limiter for API requests."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    """Simple rate limiter using sliding window (thread-safe).

    Parameters
    ----------
    max_requests:
        Maximum number of requests per window.
    window_seconds:
        Time window in seconds.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _clean_old_requests(self, key: str) -> None:
        """Remove requests outside the window (caller must hold lock)."""
        cutoff = time.time() - self.window_seconds
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]
        if not self._requests[key]:
            del self._requests[key]

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed.

        Parameters
        ----------
        key:
            Identifier for the client (e.g., user ID, IP).

        Returns
        -------
        bool
            True if request is allowed, False if rate limit exceeded.
        """
        with self._lock:
            self._clean_old_requests(key)
            if len(self._requests.get(key, [])) >= self.max_requests:
                return False
            self._requests[key].append(time.time())
            return True

    def get_remaining(self, key: str) -> int:
        """Get remaining requests for a key.

        Parameters
        ----------
        key:
            Identifier for the client.

        Returns
        -------
        int
            Number of remaining requests.
        """
        with self._lock:
            self._clean_old_requests(key)
            return max(0, self.max_requests - len(self._requests.get(key, [])))

    def reset(self, key: str) -> None:
        """Reset the rate limit for a key.

        Parameters
        ----------
        key:
            Identifier for the client.
        """
        with self._lock:
            self._requests.pop(key, None)
