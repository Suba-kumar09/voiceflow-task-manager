"""In-process login throttling.

Limits repeated failed logins per username and per client IP within a sliding window.
v1 runs a single backend process, so in-memory state is sufficient; a multi-process
deployment must move this to PostgreSQL or Redis (recorded in docs/decisions.md).
"""

import threading
import time
from collections import defaultdict, deque


class LoginThrottle:
    def __init__(self, max_failures: int, window_seconds: float, clock=time.monotonic) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self._window:
            q.popleft()
        return q

    def is_blocked(self, *keys: str) -> bool:
        now = self._clock()
        with self._lock:
            return any(len(self._prune(k, now)) >= self._max for k in keys)

    def record_failure(self, *keys: str) -> None:
        now = self._clock()
        with self._lock:
            for k in keys:
                self._prune(k, now).append(now)

    def hit(self, key: str) -> bool:
        """Count one event; False if the key is already at its limit (used as a rate limit)."""
        now = self._clock()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= self._max:
                return False
            q.append(now)
            return True

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._failures.pop(k, None)
