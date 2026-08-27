"""M1 milestone acceptance test.

Verifies the complete M1 gate: PostgreSQL schema migrations, persisted auth
with Argon2id, password-change session revocation, and registry artifact
integrity.
"""

import json
import subprocess
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user


EXPECTED_TABLES = {
    "users",
    "sessions",
    "clients",
    "feed_sources",
    "ingestion_runs",
    "staging_products",
    "staging_history",
    "quality_findings",
    "plugins",
    "plugin_configs",
    "plugin_data",
    "module_pipelines",
    "module_instances",
    "export_runs",
    "export_versions",
    "image_dimensions",
}


@pytest_asyncio.fixture
async def m1_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "old")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="old",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")


@pytest.mark.asyncio
async def test_m1_acceptance(m1_app, isolated_database_url):
    app, _ = m1_app

    # --- Schema verification ---
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: {
                    t
                    for t in inspect(sync_conn).get_table_names()
                    if t != "alembic_version"
                }
            )
    finally:
        await engine.dispose()
    assert tables == EXPECTED_TABLES

    # --- Password change revokes every session ---
    first = await _client(app)
    second = await _client(app)
    assert (await first.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200
    assert (await second.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 200

    response = await first.post(
        "/auth/password",
        json={"current_password": "old", "new_password": "new"},
    )
    assert response.status_code == 200

    # Both pre-change sessions are invalidated
    assert (await first.get("/auth/me")).status_code == 401
    assert (await second.get("/auth/me")).status_code == 401

    # Old password no longer works
    old_client = await _client(app)
    assert (await old_client.post("/auth/login", json={"username": "operator", "password": "old"})).status_code == 401

    # New password works
    fresh = await _client(app)
    assert (await fresh.post("/auth/login", json={"username": "operator", "password": "new"})).status_code == 200

    await first.aclose()
    await second.aclose()
    await old_client.aclose()
    await fresh.aclose()


@pytest.mark.asyncio
async def test_m1_registry_artifact_is_fresh():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/registry_check.py",
            "--source", "../gmc_def.md",
            "--output", "registry/attributes.json",
            "--check",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"registry check failed: {result.stderr}"
    data = json.loads((__import__("pathlib").Path("registry/attributes.json")).read_text())
    assert data["version"] == 1
    assert data["source_fingerprint"]
    assert list(data["attributes"]) == sorted(data["attributes"])
