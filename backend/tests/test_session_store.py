from datetime import datetime, timedelta, timezone

import pytest

from app.clock import TestClock as InjectableTestClock
from app.session_store import InMemorySessionStore


@pytest.mark.asyncio
async def test_create_and_validate_returns_user_id(store, clock):
    token = await store.create("operator", clock.now())
    assert await store.validate(token, clock.now(), renew_idle=False) == "operator"


@pytest.mark.asyncio
async def test_read_validation_does_not_renew_idle_expiry(store, clock):
    token = await store.create("operator", clock.now())
    clock.advance(minutes=29)
    assert await store.validate(token, clock.now(), renew_idle=False) == "operator"
    clock.advance(minutes=2)
    assert await store.validate(token, clock.now(), renew_idle=False) is None


@pytest.mark.asyncio
async def test_validation_rejects_exactly_at_idle_expiry(store, clock):
    token = await store.create("operator", clock.now())
    clock.advance(minutes=30)
    assert await store.validate(token, clock.now(), renew_idle=False) is None


@pytest.mark.asyncio
async def test_explicit_interaction_renews_idle_but_not_absolute(store, clock):
    token = await store.create("operator", clock.now())
    absolute = clock.now() + timedelta(hours=12)
    clock.advance(minutes=29)
    assert await store.validate(token, clock.now(), renew_idle=True) == "operator"
    clock.advance(minutes=29)
    assert await store.validate(token, clock.now(), renew_idle=False) == "operator"
    clock.set(absolute + timedelta(seconds=1))
    assert await store.validate(token, clock.now(), renew_idle=True) is None


@pytest.mark.asyncio
async def test_validation_rejects_exactly_at_absolute_expiry(store, clock):
    token = await store.create("operator", clock.now())
    clock.advance(hours=12)
    assert await store.validate(token, clock.now(), renew_idle=True) is None


@pytest.mark.asyncio
async def test_invalidate_rejects_existing_token(store, clock):
    token = await store.create("operator", clock.now())
    await store.invalidate(token)
    assert await store.validate(token, clock.now(), renew_idle=False) is None


@pytest.mark.asyncio
async def test_restart_invalidates_tokens(store, clock):
    token = await store.create("operator", clock.now())
    restarted = InMemorySessionStore(
        idle=timedelta(minutes=30), absolute=timedelta(hours=12), secret="test-secret"
    )
    assert await restarted.validate(token, clock.now(), renew_idle=False) is None


@pytest.mark.asyncio
async def test_malformed_and_tampered_tokens_are_rejected(store, clock):
    token = await store.create("operator", clock.now())
    for invalid in ("", "not-a-token", token + "x", token.replace(".", "", 1)):
        assert await store.validate(invalid, clock.now(), renew_idle=False) is None


@pytest.mark.asyncio
async def test_same_length_signature_tampering_is_rejected(store, clock):
    token = await store.create("operator", clock.now())
    nonce, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{nonce}.{replacement}{signature[1:]}"
    assert len(tampered) == len(token)
    assert await store.validate(tampered, clock.now(), renew_idle=False) is None


def test_test_clock_normalizes_aware_times_to_utc():
    clock = InjectableTestClock(datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1))))
    assert clock.now() == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_test_clock_rejects_naive_times():
    with pytest.raises(ValueError, match="timezone-aware"):
        InjectableTestClock(datetime(2026, 1, 1))


@pytest.mark.asyncio
async def test_idle_deadline_is_capped_by_absolute_deadline(store, clock):
    capped_store = InMemorySessionStore(
        idle=timedelta(hours=2), absolute=timedelta(hours=3), secret="test-secret"
    )
    token = await capped_store.create("operator", clock.now())
    clock.advance(hours=1, minutes=59)
    assert await capped_store.validate(token, clock.now(), renew_idle=True) == "operator"
    clock.advance(hours=1, minutes=1, seconds=1)
    assert await capped_store.validate(token, clock.now(), renew_idle=False) is None
