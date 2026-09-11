from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai import PromptTemplate
from app.models.client import Client
from app.persistence.cascade import delete_client_cascade


@pytest_asyncio.fixture
async def session(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_client(session, name: str) -> int:
    client = Client(name=name)
    session.add(client)
    await session.flush()
    return client.id


def _template(**overrides) -> PromptTemplate:
    base = {
        "task_type": "policy_check", "client_id": None, "version": 1, "name": "Default",
        "system_prompt": "Check: {{title}}", "user_prompt": "{{title}} {{description}}",
        "variables": ["title", "description"], "is_active": True, "created_by": "operator",
    }
    base.update(overrides)
    return PromptTemplate(**base)


@pytest.mark.asyncio
async def test_prompt_template_round_trip(session):
    async with session.begin():
        session.add(_template())
    async with session.begin():
        row = (await session.execute(select(PromptTemplate))).scalar_one()
        assert row.version == 1
        assert row.variables == ["title", "description"]
        assert row.client_id is None
        assert row.is_active is True


@pytest.mark.asyncio
async def test_two_active_global_templates_rejected(session):
    async with session.begin():
        session.add(_template(version=1, is_active=True))
    async with session.begin():
        session.add(_template(version=2, is_active=True))
        with pytest.raises(IntegrityError):
            await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_global_and_client_active_coexist(session):
    async with session.begin():
        client_id = await _seed_client(session, "acme")
        session.add(_template(version=1, is_active=True))
        session.add(_template(version=1, client_id=client_id, is_active=True))
    async with session.begin():
        rows = list((await session.execute(select(PromptTemplate))).scalars())
        assert len(rows) == 2
        assert all(r.is_active for r in rows)


@pytest.mark.asyncio
async def test_version_unique_per_scope(session):
    async with session.begin():
        client_id = await _seed_client(session, "acme")
        session.add(_template(version=1))
    async with session.begin():
        # same version in a different scope is fine
        session.add(_template(version=1, client_id=client_id))
    async with session.begin():
        # same version in the same scope is not
        session.add(_template(version=1, is_active=False))
        with pytest.raises(IntegrityError):
            await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_client_cascade_deletes_client_scoped_templates_only(session):
    async with session.begin():
        acme_id = await _seed_client(session, "acme")
        session.add(_template(version=1, is_active=True))  # global
        session.add(_template(version=1, client_id=acme_id, is_active=True))
    await delete_client_cascade(session, acme_id)
    await session.commit()
    rows = list((await session.execute(select(PromptTemplate))).scalars())
    assert len(rows) == 1
    assert rows[0].client_id is None
