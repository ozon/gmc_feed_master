from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.ai.resilience import (
    CallOutcome,
    CircuitBreaker,
    RetryPolicy,
    classify_failure,
)
from app.clock import TestClock


def _clock() -> TestClock:
    return TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_breaker_opens_after_threshold_failures():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=3, window_s=60, cooldown_s=30, clock=clock)
    assert breaker.allow_call()
    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open
    assert not breaker.allow_call()


def test_breaker_half_open_after_cooldown_then_closes_on_success():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=2, window_s=60, cooldown_s=30, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open
    clock.advance(seconds=31)
    assert breaker.allow_call()  # half-open probe
    breaker.record_success()
    assert not breaker.is_open
    assert breaker.allow_call()


def test_breaker_stays_open_inside_cooldown():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=2, window_s=60, cooldown_s=30, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(seconds=10)
    assert not breaker.allow_call()


def test_breaker_failure_window_expires():
    clock = _clock()
    breaker = CircuitBreaker(failure_threshold=3, window_s=60, cooldown_s=30, clock=clock)
    breaker.record_failure()
    clock.advance(seconds=61)
    breaker.record_failure()
    breaker.record_failure()
    # 3 failures did not accumulate inside a 60s window -> still closed
    assert not breaker.is_open


def test_retry_policy_delay_bounds():
    policy = RetryPolicy(max_attempts=3, base_delay_s=0.5, max_delay_s=8.0, jitter=0.25)
    assert 0.375 <= policy.delay_for_attempt(1) <= 0.625   # 0.5 ± 25%
    assert 0.75 <= policy.delay_for_attempt(2) <= 1.25     # 1.0 ± 25%
    assert 1.5 <= policy.delay_for_attempt(3) <= 2.5       # 2.0 ± 25%


def test_classify_failure_rate_limit_retryable():
    exc = httpx.HTTPStatusError(
        "rate limited", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )
    outcome, retryable = classify_failure(exc)
    assert outcome is CallOutcome.RATE_LIMITED
    assert retryable


def test_classify_failure_timeout_retryable():
    outcome, retryable = classify_failure(httpx.TimeoutException("timed out"))
    assert outcome is CallOutcome.TIMEOUT
    assert retryable


def test_classify_failure_server_error_retryable():
    exc = httpx.HTTPStatusError(
        "boom", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(500),
    )
    outcome, retryable = classify_failure(exc)
    assert outcome is CallOutcome.SERVER_ERROR
    assert retryable


def test_classify_failure_client_error_not_retryable():
    exc = httpx.HTTPStatusError(
        "bad request", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(400),
    )
    outcome, retryable = classify_failure(exc)
    assert outcome is CallOutcome.CLIENT_ERROR
    assert not retryable
