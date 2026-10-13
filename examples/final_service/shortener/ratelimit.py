"""In-process token-bucket rate limiter. Single-node only; see design notes for trade-offs."""
from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucketLimiter:
    def __init__(self, per_minute: int, burst: int | None = None,
                 clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000) -> None:
        self._rate = per_minute / 60.0
        self._capacity = float(burst if burst is not None else per_minute)
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - last) * self._rate)
            allowed = tokens >= 1.0
            self._buckets[key] = (tokens - 1.0 if allowed else tokens, now)
            if len(self._buckets) > self._max_keys:  # bound memory under key-churn attacks
                oldest = sorted(self._buckets, key=lambda k: self._buckets[k][1])
                for k in oldest[: len(oldest) // 2]:
                    del self._buckets[k]
            return allowed


def client_key(request) -> str:
    return request.client.host if request.client else "unknown"
