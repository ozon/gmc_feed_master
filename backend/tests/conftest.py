import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from pytest_postgresql import factories
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi.testclient import TestClient

from app.clock import TestClock
from app.config import Settings
from app.main import create_app
from app.session_store import InMemorySessionStore


os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("INITIAL_USERNAME", "test-user")
os.environ.setdefault("INITIAL_PASSWORD", "test-password")

_ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "registry" / "attributes.json"

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _server_params() -> dict:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// dialect")
    try:
        parts = urlsplit(value)
    except ValueError:
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL via asyncpg")
    if parts.query:
        pytest.fail("TEST_DATABASE_URL must not contain query parameters")
    return {
        "host": parts.hostname or "localhost",
        "port": parts.port or 5432,
        "user": parts.username or "postgres",
        "password": parts.password or "",
    }


def _load_alembic_schema(**kwargs):
    """Populate the plugin's template database with the full migration chain."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    password = quote(kwargs.get("password") or "", safe="")
    url = (
        f"postgresql+asyncpg://{kwargs['user']}:{password}"
        f"@{kwargs['host']}:{kwargs['port']}/{kwargs['dbname']}"
    )
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    # alembic's env.py disposes its own engine before returning, so no
    # connections hold the template open when the plugin clones it.


_server = _server_params()

gmc_postgres_noproc = factories.postgresql_noproc(
    host=_server["host"],
    port=_server["port"],
    user=_server["user"],
    password=_server["password"],
    load=[_load_alembic_schema],
)

gmc_database = factories.postgresql("gmc_postgres_noproc")


def _asyncpg_url(info: psycopg.ConnectionInfo) -> str:
    password = quote(info.password or "", safe="")
    return (
        f"postgresql+asyncpg://{info.user}:{password}"
        f"@{info.host}:{info.port}/{info.dbname}"
    )


@pytest.fixture
def isolated_database_url(request):
    _server_params()
    connection = request.getfixturevalue("gmc_database")
    return _asyncpg_url(connection.info)


@pytest.fixture
def artifact_path():
    return _ARTIFACT_PATH


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
def client(settings, store, clock):
    return TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver",
    )
