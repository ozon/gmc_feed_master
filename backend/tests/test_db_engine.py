import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.engine import (
    async_database_url,
    create_engine,
    create_session_factory,
    get_db_session,
)


def test_database_url_is_converted_to_asyncpg(settings):
    settings.database_url = "postgresql://postgres:postgres@localhost:5432/gmc_feed"

    assert async_database_url(settings) == (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed"
    )


def test_engine_creation_is_lazy(settings):
    engine = create_engine(settings)

    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"


def test_session_factory_does_not_connect_and_does_not_expire_on_commit(settings):
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    session = factory()
    assert isinstance(session, AsyncSession)
    assert session.sync_session.expire_on_commit is False


@pytest.mark.asyncio
async def test_session_dependency_yields_and_closes_session(settings):
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async def receive():
        return {"type": "http.request"}

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []}, receive)
    request.state.db_session_factory = factory

    dependency = get_db_session(request)
    session = await dependency.__anext__()
    assert isinstance(session, AsyncSession)
    assert session.is_active
    await dependency.aclose()
    assert session.in_transaction() is False
