"""Tiny in-process rate limiter with leaky-bucket semantics.

Scope
-----
Single-worker only, just like the SSE hub — multi-worker deployments would
need to share state via Redis. That's fine here because the limiter is
aimed at brute-force login attempts, which can be rate-capped per-IP
*before* the request reaches Python (via nginx limit_req) in a production
setup. This module is a belt-and-braces for development/self-host.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    """Allow ``capacity`` events per ``window_seconds`` per bucket key."""

    capacity: int
    window_seconds: float


class SlidingWindowLimiter:
    def __init__(self, limit: RateLimit) -> None:
        self.limit = limit
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str) -> bool:
        """Return True if the event is allowed; False if throttled."""
        now = time.monotonic()
        cutoff = now - self.limit.window_seconds
        async with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit.capacity:
                return False
            bucket.append(now)
            return True

    async def seconds_until_retry(self, key: str) -> float:
        """How long the caller should wait before trying again."""
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits[key]
            if not bucket or len(bucket) < self.limit.capacity:
                return 0.0
            return max(0.0, self.limit.window_seconds - (now - bucket[0]))

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


# Public singletons used from routes.
LOGIN_FAILURE_LIMITER = SlidingWindowLimiter(RateLimit(capacity=10, window_seconds=60))
"""10 failed logins per IP per minute before we start returning 429."""
