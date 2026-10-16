"""Tiny thread-safe sliding-window limiter (M2).

Keeps a free-tier requests-per-minute limit from turning into a stream of 429s.
`max_per_minute <= 0` disables it.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_per_minute: int, clock=time.monotonic, sleep=time.sleep):
        self.max = max_per_minute
        self._clock, self._sleep = clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until one more call is allowed. Returns the seconds spent waiting."""
        if self.max <= 0:
            return 0.0
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= 60.0:
                    self._stamps.popleft()
                if len(self._stamps) < self.max:
                    self._stamps.append(now)
                    return waited
                wait = 60.0 - (now - self._stamps[0])
            self._sleep(wait)  # sleep outside the lock
            waited += wait
