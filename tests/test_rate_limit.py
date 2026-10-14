"""Sliding-window limiter."""

import pytest

from openai_ads_mcp.rate_limit import SlidingWindowLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_limiter_waits_until_the_window_slides() -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(2, 60.0, clock=clock.time, sleep=clock.sleep)

    await limiter.acquire("GET /campaigns")
    await limiter.acquire("GET /campaigns")
    await limiter.acquire("GET /campaigns")

    assert clock.slept == [60.0]
    assert clock.now == 60.0


@pytest.mark.asyncio
async def test_endpoint_keys_are_independent() -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(1, 60.0, clock=clock.time, sleep=clock.sleep)

    await limiter.acquire("GET /campaigns")
    await limiter.acquire("GET /ads")

    assert clock.slept == []
