import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.base import Base
from app.models.session import Session
from app.models.user import User
from app.persistence.sessions import PostgresSessionStore, _token_hash


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def postgres_store():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the asyncpg driver")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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
