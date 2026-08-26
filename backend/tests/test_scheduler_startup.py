import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    yield factory, isolated_database_url
    await engine.dispose()


async def test_startup_registers_valid_cron_jobs(db):
    factory, url = db
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            session.add(FeedSource(client_id=client.id, name="Scheduled", source_format="xml", cron_expression="0 * * * *"))
            session.add(FeedSource(client_id=client.id, name="Manual", source_format="xml"))

    settings = Settings(_env_file=None, session_secret="test-s", initial_username="operator", initial_password="pw", database_url=url)
    app = create_app(settings=settings, db_session_factory=factory)

    async with app.router.lifespan_context(app):
        assert hasattr(app.state, "lock_registry")
        assert hasattr(app.state, "pipeline_runner")
        assert hasattr(app.state, "scheduler_service")
        async with factory() as session:
            result = await session.execute(select(FeedSource))
            sources = {fs.name: fs for fs in result.scalars()}
        assert app.state.scheduler_service.has_job(sources["Scheduled"].id)
        assert not app.state.scheduler_service.has_job(sources["Manual"].id)


async def test_startup_skips_invalid_cron(db):
    factory, url = db
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            session.add(FeedSource(client_id=client.id, name="Bad", source_format="xml", cron_expression="not-cron"))
            session.add(FeedSource(client_id=client.id, name="Good", source_format="xml", cron_expression="15 3 * * *"))

    settings = Settings(_env_file=None, session_secret="test-s", initial_username="operator", initial_password="pw", database_url=url)
    app = create_app(settings=settings, db_session_factory=factory)

    async with app.router.lifespan_context(app):
        async with factory() as session:
            result = await session.execute(select(FeedSource))
            sources = {fs.name: fs for fs in result.scalars()}
        assert not app.state.scheduler_service.has_job(sources["Bad"].id)
        assert app.state.scheduler_service.has_job(sources["Good"].id)


async def test_app_without_db_has_no_scheduler():
    from app.session_store import InMemorySessionStore
    from datetime import timedelta

    store = InMemorySessionStore(idle=timedelta(minutes=30), absolute=timedelta(hours=12), secret="test-s")
    settings = Settings(_env_file=None, session_secret="test-s", initial_username="u", initial_password="p")
    app = create_app(settings=settings, session_store=store)
    assert not hasattr(app.state, "scheduler_service") or getattr(app.state, "scheduler_service", None) is None

    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.get("/health")
    assert resp.status_code == 200
