from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

import httpx


class CallOutcome(Enum):
    OK = "ok"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"


class _ClockLike(Protocol):
    def now(self) -> datetime: ...


def _utcnow(clock: _ClockLike | None) -> datetime:
    if clock is not None:
        return clock.now()
    return datetime.now(timezone.utc)


class CircuitBreaker:
    """In-process, per-provider-config circuit breaker.

    closed -> open: `failure_threshold` failures within `window_s`
    open -> half-open: `cooldown_s` elapsed
    half-open -> closed: one successful probe
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_s: int = 60,
        cooldown_s: int = 30,
        clock: _ClockLike | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._window_s = window_s
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures: deque[datetime] = deque()
        self._opened_at: datetime | None = None
        self._half_open = False

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def allow_call(self) -> bool:
        if self._opened_at is None:
            return True
        elapsed = (_utcnow(self._clock) - self._opened_at).total_seconds()
        if elapsed >= self._cooldown_s:
            self._half_open = True
            return True  # probe
        return False

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None
        self._half_open = False

    def record_failure(self) -> None:
        now = _utcnow(self._clock)
        self._failures.append(now)
        cutoff = now.timestamp() - self._window_s
        while self._failures and self._failures[0].timestamp() < cutoff:
            self._failures.popleft()
        if self._half_open or len(self._failures) >= self._failure_threshold:
            self._opened_at = now
            self._half_open = False


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter: float = 0.25

    def delay_for_attempt(self, attempt: int) -> float:
        """1-based attempt -> delay before that attempt's retry (exp backoff + jitter)."""
        delay = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        spread = delay * self.jitter
        return max(0.0, delay + random.uniform(-spread, spread))


def classify_failure(exc: Exception) -> tuple[CallOutcome, bool]:
    """Classify a provider exception into (outcome, retryable)."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return CallOutcome.RATE_LIMITED, True
        if status >= 500:
            return CallOutcome.SERVER_ERROR, True
        return CallOutcome.CLIENT_ERROR, False
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return CallOutcome.TIMEOUT, True
    return CallOutcome.CLIENT_ERROR, False
