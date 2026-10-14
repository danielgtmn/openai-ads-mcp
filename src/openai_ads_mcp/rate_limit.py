"""In-process sliding-window limiters for the Ads API quotas.

The Advertiser API allows 600 requests per minute per endpoint and 1,200
requests per minute overall, counted per ad account and per IP address. This
limiter is per process. A 429 from the API is still retried with backoff.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class SlidingWindowLimiter:
    """Allow at most ``max_requests`` acquisitions per key inside ``window_seconds``."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1.")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive.")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> None:
        while True:
            async with self._lock:
                now = self._clock()
                events = self._events.setdefault(key, deque())
                cutoff = now - self.window_seconds
                while events and events[0] <= cutoff:
                    events.popleft()
                if len(events) < self.max_requests:
                    events.append(now)
                    return
                wait = self.window_seconds - (now - events[0])
            await self._sleep(max(wait, 0.0))
