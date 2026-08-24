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
        pytest.skip("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
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


async def test_postgres_session_logout_and_revocation_generation(postgres_store):
    first = await postgres_store.create("operator", now())
    second = await postgres_store.create("operator", now())
    async with postgres_store._session_factory() as session:
        async with session.begin():
            user = (await session.execute(select(User).where(User.username == "operator").with_for_update())).scalar_one()
            user.revocation_generation += 1
    assert await postgres_store.validate(first, now(), renew_idle=False) is None
    assert await postgres_store.validate(second, now(), renew_idle=False) is None
