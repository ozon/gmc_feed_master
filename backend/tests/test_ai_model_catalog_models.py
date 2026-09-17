from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai import AiModelCatalog, AiModelCatalogSync


@pytest_asyncio.fixture
async def db_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _row(model_id: str) -> AiModelCatalog:
    return AiModelCatalog(
        vendor="openai",
        model_id=model_id,
        display_name=model_id.rsplit("/", 1)[-1],
        mode="chat",
        context_window=128000,
        max_output_tokens=16384,
        input_price_per_mtok=Decimal("2.500000"),
        output_price_per_mtok=Decimal("10.000000"),
        supports_vision=True,
        supports_function_calling=True,
    )


@pytest.mark.asyncio
async def test_catalog_round_trip(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(_row("openai/gpt-4o"))
        session.add(AiModelCatalogSync(id=1, source="bundled"))
    async with db_factory() as session:
        row = (await session.execute(select(AiModelCatalog))).scalar_one()
        assert row.model_id == "openai/gpt-4o"
        assert row.mode == "chat"
        assert row.supports_vision is True
        sync = await session.get(AiModelCatalogSync, 1)
        assert sync is not None
        assert sync.source == "bundled"


@pytest.mark.asyncio
async def test_catalog_model_id_is_unique(db_factory) -> None:
    async with db_factory() as session, session.begin():
        session.add(_row("openai/gpt-4o"))
    with pytest.raises(IntegrityError):
        async with db_factory() as session, session.begin():
            session.add(_row("openai/gpt-4o"))
