import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.clock import TestClock as InjectableTestClock
from app.models.session import Session
from app.models.user import User
from app.persistence.sessions import PostgresSessionStore, _token_hash


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def postgres_store(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
            session.add(User(username="operator", password_hash="not-used"))
    yield PostgresSessionStore(factory, timedelta(minutes=30), timedelta(hours=12), "test-secret")
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
    await engine.dispose()


def now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_postgres_session_survives_store_restart_and_stores_only_hash(postgres_store):
    token = await postgres_store.create("operator", now())
    restarted = PostgresSessionStore(postgres_store._session_factory, timedelta(minutes=30), timedelta(hours=12), "test-secret")
    assert await restarted.validate(token, now(), renew_idle=False) == "operator"
    async with postgres_store._session_factory() as session:
        row = (await session.execute(select(Session))).scalar_one()
        assert row.token_hash == _token_hash(token)
        assert token not in row.token_hash


async def test_postgres_session_revocation_generation_invalidates_all_sessions(postgres_store):
    first = await postgres_store.create("operator", now())
    second = await postgres_store.create("operator", now())
    async with postgres_store._session_factory() as session:
        async with session.begin():
            user = (await session.execute(select(User).where(User.username == "operator").with_for_update())).scalar_one()
            user.revocation_generation += 1
    assert await postgres_store.validate(first, now(), renew_idle=False) is None
    assert await postgres_store.validate(second, now(), renew_idle=False) is None


async def test_postgres_explicit_interaction_renews_idle_only(postgres_store):
    token = await postgres_store.create("operator", now())
    at_29_minutes = now() + timedelta(minutes=29)
    assert await postgres_store.validate(token, at_29_minutes, renew_idle=True) == "operator"
    assert await postgres_store.validate(
        token, at_29_minutes + timedelta(minutes=29), renew_idle=False
    ) == "operator"
    assert await postgres_store.validate(
        token, at_29_minutes + timedelta(minutes=31), renew_idle=False
    ) is None


async def test_postgres_read_does_not_renew_idle(postgres_store):
    token = await postgres_store.create("operator", now())
    assert await postgres_store.validate(token, now() + timedelta(minutes=29), renew_idle=False) == "operator"
    assert await postgres_store.validate(token, now() + timedelta(minutes=30), renew_idle=False) is None


async def test_postgres_rejects_exact_idle_expiry(postgres_store):
    token = await postgres_store.create("operator", now())
    assert await postgres_store.validate(token, now() + timedelta(minutes=30), renew_idle=True) is None


async def test_postgres_rejects_exact_absolute_expiry(postgres_store):
    token = await postgres_store.create("operator", now())
    assert await postgres_store.validate(token, now() + timedelta(hours=12), renew_idle=True) is None


async def test_postgres_absolute_expiry_is_hard_cap_during_near_boundary_renewal(postgres_store):
    clock = InjectableTestClock(now())
    absolute_expiry = clock.now() + timedelta(hours=12)
    token = await postgres_store.create("operator", clock.now())

    for _ in range(24):
        clock.advance(minutes=29)
        assert await postgres_store.validate(token, clock.now(), renew_idle=True) == "operator"
    clock.advance(minutes=23, seconds=59)
    assert await postgres_store.validate(token, clock.now(), renew_idle=True) == "operator"

    async with postgres_store._session_factory() as session:
        row = (await session.execute(select(Session))).scalar_one()
        assert row.absolute_expires_at == absolute_expiry
        assert row.idle_expires_at == absolute_expiry

    clock.set(absolute_expiry)
    assert await postgres_store.validate(token, clock.now(), renew_idle=True) is None

    after_token = await postgres_store.create("operator", clock.now())
    clock.advance(hours=12, seconds=1)
    assert await postgres_store.validate(after_token, clock.now(), renew_idle=True) is None


async def test_postgres_rejects_malformed_and_tampered_tokens(postgres_store):
    token = await postgres_store.create("operator", now())
    nonce, signature = token.split(".")
    tampered = f"{nonce}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    for invalid in ("", "not-a-token", token + "x", token.replace(".", "", 1), tampered):
        assert await postgres_store.validate(invalid, now(), renew_idle=False) is None


async def test_postgres_direct_invalidate_rejects_token(postgres_store):
    token = await postgres_store.create("operator", now())
    await postgres_store.invalidate(token)
    assert await postgres_store.validate(token, now(), renew_idle=False) is None
