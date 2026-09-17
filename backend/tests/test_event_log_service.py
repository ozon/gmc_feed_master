import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.event_log import audit, record_event
from app.models.event_log import EventLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    f = async_sessionmaker(engine, expire_on_commit=False)
    yield f
    await engine.dispose()


async def test_record_event_inserts_row(factory):
    async with factory() as session, session.begin():
        await record_event(
            session,
            category="client_error",
            level="error",
            source="frontend",
            message="boom",
            context={"route": "/logs"},
            request_id="req-1",
        )
    async with factory() as session:
        row = (await session.execute(select(EventLog))).scalar_one()
        assert row.category == "client_error"
        assert row.context == {"route": "/logs"}
        assert row.request_id == "req-1"


async def test_audit_pulls_actor_from_contextvars(factory):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        actor="operator", actor_role="admin", request_id="req-9", run_id=7
    )
    async with factory() as session, session.begin():
        await audit(session, "login success", target_type="user", target_id="operator")
    structlog.contextvars.clear_contextvars()

    async with factory() as session:
        row = (await session.execute(select(EventLog))).scalar_one()
        assert row.category == "audit"
        assert row.actor == "operator"
        assert row.actor_role == "admin"
        assert row.request_id == "req-9"
        assert row.run_id == 7
        assert row.context["target_type"] == "user"
        assert row.context["target_id"] == "operator"
