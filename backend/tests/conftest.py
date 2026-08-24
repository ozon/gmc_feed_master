import os
import asyncio
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest
import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fastapi.testclient import TestClient

from app.clock import TestClock
from app.config import Settings
from app.main import create_app
from app.session_store import InMemorySessionStore


os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("INITIAL_USERNAME", "test-user")
os.environ.setdefault("INITIAL_PASSWORD", "test-password")


@pytest.fixture
def clock():
    return TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def store():
    from datetime import timedelta

    return InMemorySessionStore(
        idle=timedelta(minutes=30), absolute=timedelta(hours=12), secret="test-secret"
    )


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="correct",
    )


@pytest.fixture
def isolated_database_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// dialect")
    parts = urlsplit(value)
    database_name = f"m1_test_{uuid.uuid4().hex}"
    admin_url = urlunsplit(("postgresql", parts.netloc, "/postgres", parts.query, ""))

    async def create_database():
        connection = await asyncpg.connect(admin_url)
        try:
            await connection.execute(f'CREATE DATABASE "{database_name}"')
        finally:
            await connection.close()

    asyncio.run(create_database())
    isolated = urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, ""))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", isolated)
    command.upgrade(config, "head")
    try:
        yield isolated
    finally:
        async def drop_database():
            connection = await asyncpg.connect(admin_url)
            try:
                await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            finally:
                await connection.close()

        asyncio.run(drop_database())


@pytest.fixture
def client(settings, store, clock):
    return TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver",
    )
