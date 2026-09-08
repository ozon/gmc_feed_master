import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.session import Session
from app.models.user import User
from app.models.user_client import UserClient
from app.persistence.users import seed_initial_user
from app.security.passwords import hash_password


@pytest_asyncio.fixture
async def scope_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(UserClient))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            acme = Client(name="Acme")
            other = Client(name="Other Corp")
            session.add_all([acme, other])
            await session.flush()
            session.add(FeedSource(client_id=acme.id, name="Acme Feed", source_format="xml",
                                   source_url="https://acme.example/feed.xml"))
            session.add(FeedSource(client_id=other.id, name="Other Feed", source_format="xml",
                                   source_url="https://other.example/feed.xml"))
            bob = User(username="bob", password_hash=hash_password("bob-pass"), role="user")
            session.add(bob)
            await session.flush()
            session.add(UserClient(user_id=bob.id, client_id=acme.id))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_client(scope_app):
    app, _ = scope_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def bob_client(scope_app):
    app, _ = scope_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "bob", "password": "bob-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_user_sees_only_assigned_client(scope_app, bob_client):
    response = await bob_client.get("/clients")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["Acme"]


@pytest.mark.asyncio
async def test_admin_sees_all_clients(scope_app, admin_client):
    response = await admin_client.get("/clients")
    assert response.status_code == 200
    names = sorted(c["name"] for c in response.json())
    assert names == ["Acme", "Other Corp"]


@pytest.mark.asyncio
async def test_user_dashboard_summary_filtered(scope_app, bob_client):
    response = await bob_client.get("/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body["clients"]] == ["Acme"]
    assert body["counts"]["clients"] == 1
    assert body["counts"]["feed_sources"] == 1


@pytest.mark.asyncio
async def test_unassigned_client_routes_404(scope_app, bob_client, admin_client):
    other_id = [c["id"] for c in (await admin_client.get("/clients")).json()
                if c["name"] == "Other Corp"][0]
    assert (await bob_client.get(f"/clients/{other_id}/feed-sources")).status_code == 404
    assert (await bob_client.put(
        f"/clients/{other_id}", json={"name": "Hacked"}
    )).status_code == 404
    assert (await bob_client.delete(f"/clients/{other_id}")).status_code == 404


@pytest.mark.asyncio
async def test_assigned_client_crud_is_admin_only(scope_app, bob_client, admin_client):
    acme_id = [c["id"] for c in (await admin_client.get("/clients")).json()
               if c["name"] == "Acme"][0]
    assert (await bob_client.post(
        "/clients", json={"name": "Bob Corp"}
    )).status_code == 403
    assert (await bob_client.put(
        f"/clients/{acme_id}", json={"name": "Renamed"}
    )).status_code == 403
    assert (await bob_client.delete(f"/clients/{acme_id}")).status_code == 403


@pytest.mark.asyncio
async def test_unassigned_feed_source_routes_404(scope_app, bob_client, admin_client):
    feeds = (await admin_client.get("/dashboard/summary")).json()["clients"]
    other_feed_id = [f["id"] for c in feeds if c["name"] == "Other Corp"
                     for f in c["feed_sources"]][0]
    assert (await bob_client.get(f"/feed-sources/{other_feed_id}")).status_code == 404
    assert (await bob_client.get(
        f"/feed-sources/{other_feed_id}/ingestion-runs"
    )).status_code == 404
    assert (await bob_client.post(
        f"/feed-sources/{other_feed_id}/export-token/rotate"
    )).status_code == 404


@pytest.mark.asyncio
async def test_assigned_feed_source_routes_allowed(scope_app, bob_client, admin_client):
    feeds = (await admin_client.get("/dashboard/summary")).json()["clients"]
    acme_feed_id = [f["id"] for c in feeds if c["name"] == "Acme"
                    for f in c["feed_sources"]][0]
    assert (await bob_client.get(f"/feed-sources/{acme_feed_id}")).status_code == 200
    assert (await bob_client.get(
        f"/feed-sources/{acme_feed_id}/ingestion-runs"
    )).status_code == 200


@pytest.mark.asyncio
async def test_plugin_preview_body_scope_enforced(scope_app, bob_client, admin_client):
    app, _ = scope_app
    feeds = (await admin_client.get("/dashboard/summary")).json()["clients"]
    other_feed_id = [f["id"] for c in feeds if c["name"] == "Other Corp"
                     for f in c["feed_sources"]][0]
    acme_feed_id = [f["id"] for c in feeds if c["name"] == "Acme"
                    for f in c["feed_sources"]][0]
    # Plugin preview routes take feed_source_id in the BODY — router-level
    # path/query enforcement cannot see them; the routes must check scope.
    # Lifespan mounts the plugin routes (assigned → 200 proves they exist).
    async with app.router.lifespan_context(app):
        assert (await bob_client.post("/plugins/filter/preview", json={
            "feed_source_id": acme_feed_id, "conditions": [],
        })).status_code == 200
        assert (await bob_client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": acme_feed_id, "rules": [], "slotIds": {},
        })).status_code == 200
        assert (await bob_client.post("/plugins/filter/preview", json={
            "feed_source_id": other_feed_id, "conditions": [],
        })).status_code == 404
        assert (await bob_client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": other_feed_id, "rules": [], "slotIds": {},
        })).status_code == 404
