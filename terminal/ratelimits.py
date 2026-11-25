"""Small in-process token buckets for terminal byte/rate controls.

These buckets protect a single ASGI worker's memory and event loop. Session and
lifecycle decisions remain database-backed and shared across workers.
"""
from __future__ import annotations

import time


class TokenBucket:
    """Fixed-capacity token bucket with continuous refill."""

    def __init__(self, rate: float, burst: int):
        self.rate = max(float(rate), 1.0)
        self.capacity = max(float(burst), self.rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()

    def consume(self, amount: int = 1) -> bool:
        amount = max(0, int(amount))
        if amount == 0:
            return True
        now = time.monotonic()
        self._tokens = min(
            self.capacity,
            self._tokens + (now - self._updated) * self.rate,
        )
        self._updated = now
        if self._tokens < amount:
            return False
        self._tokens -= amount
        return True
