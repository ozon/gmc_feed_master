from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import Settings


def async_database_url(settings: Settings) -> str:
    return settings.async_database_url


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(async_database_url(settings))


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = getattr(request.state, "db_session_factory", None)
    if factory is None:
        factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session
