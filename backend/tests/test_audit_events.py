import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.event_log import EventLog
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(EventLog))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=isolated_database_url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def _audit_messages(factory):
    async with factory() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.category == "audit").order_by(EventLog.id)
            )
        ).scalars().all()
        return [r.message for r in rows]


async def test_login_success_and_failure_are_audited(settings_app):
    app, factory = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
    assert (
        await client.post(
            "/auth/login", json={"username": "operator", "password": "wrong"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/auth/login", json={"username": "operator", "password": "admin-pass"}
        )
    ).status_code == 200
    await client.aclose()
    messages = await _audit_messages(factory)
    assert "auth.login.failure" in messages
    assert "auth.login.success" in messages


async def test_user_create_is_audited_with_actor(settings_app):
    app, factory = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
    await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )
    created = await client.post(
        "/admin/users",
        json={"username": "newuser", "password": "pw", "role": "user", "client_ids": []},
    )
    assert created.status_code == 201
    await client.aclose()

    async with factory() as session:
        row = (
            await session.execute(
                select(EventLog).where(EventLog.message == "user.create")
            )
        ).scalar_one()
        assert row.actor == "operator"
        assert row.actor_role == "admin"
        assert row.context["target_type"] == "user"


async def test_user_create_audit_failure_rolls_back(settings_app, monkeypatch):
    app, factory = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver/api")
    await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )

    async def _failing_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("app.routes.admin.audit", _failing_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await client.post(
            "/admin/users",
            json={
                "username": "atomic",
                "password": "pw",
                "role": "user",
                "client_ids": [],
            },
        )
    await client.aclose()

    async with factory() as session:
        row = (
            await session.execute(select(User).where(User.username == "atomic"))
        ).scalar_one_or_none()
        assert row is None
