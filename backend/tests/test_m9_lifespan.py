import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.pipeline.reconcile import INTERRUPTED_MESSAGE
from app.pipeline.scheduler import (
    INGESTION_PURGE_JOB_ID,
    SYSTEM_PURGE_JOB_ID,
    job_id,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_env(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
        export_dir=str(tmp_path / "exports"),
    )
    yield factory, settings, tmp_path
    await engine.dispose()


async def _seed_feed(factory, cron_expression=None):
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="xml",
                source_url="https://example.com/feed.xml",
                cron_expression=cron_expression,
            )
            session.add(feed_source)
            await session.flush()
            return feed_source.id


async def test_lifespan_starts_scheduler_registers_jobs_and_shuts_down(app_env):
    factory, settings, tmp_path = app_env
    fs_id = await _seed_feed(factory, cron_expression="0 * * * *")
    app = create_app(
        settings=settings,
        db_session_factory=factory,
        plugins_dir=tmp_path / "plugins-empty",
    )
    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler_service
        assert scheduler._scheduler.running
        job = scheduler._scheduler.get_job(job_id(fs_id))
        assert job is not None
        assert job.max_instances == 2
        assert scheduler._scheduler.get_job(SYSTEM_PURGE_JOB_ID) is not None
        assert scheduler._scheduler.get_job(INGESTION_PURGE_JOB_ID) is not None
    assert not app.state.scheduler_service._scheduler.running


async def test_lifespan_reconciles_orphaned_runs(app_env):
    factory, settings, tmp_path = app_env
    fs_id = await _seed_feed(factory)
    async with factory() as session:
        async with session.begin():
            session.add(IngestionRun(feed_source_id=fs_id, status="running"))
            session.add(IngestionRun(feed_source_id=fs_id, status="pending"))
            session.add(IngestionRun(feed_source_id=fs_id, status="success"))
    app = create_app(
        settings=settings,
        db_session_factory=factory,
        plugins_dir=tmp_path / "plugins-empty",
    )
    async with app.router.lifespan_context(app):
        pass
    async with factory() as session:
        runs = list(
            (await session.execute(select(IngestionRun).order_by(IngestionRun.id))).scalars()
        )
    assert [run.status for run in runs] == ["error", "error", "success"]
    assert runs[0].error_message == INTERRUPTED_MESSAGE
    assert runs[0].completed_at is not None
    assert runs[2].error_message is None
