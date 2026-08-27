"""M6 acceptance gate — plugin host verified."""

import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin, PluginConfig
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.pipeline import LockRegistry, default_steps
from app.pipeline.runner import PipelineRunner
from app.plugins.contract import contract_violations
from app.plugins.discovery import Candidate, discover, discover_and_mount, register_candidates
from registry.loader import load_registry


pytestmark = pytest.mark.asyncio

FIXTURE_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "example_plugin"

FEED_TSV = (
    b"sku\ttitle\tean\n"
    b"A1\tRed Shirt\t1234567890123\n"
    b"drop-me\tBlue Hat\t9876543210987\n"
)


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None, _client=None):
        return self.data


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
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
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, engine, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_client_and_feed(factory):
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration={},
            )
            session.add(feed_source)
            await session.flush()
            return client.id, feed_source.id


# ── Scenario 1 ──────────────────────────────────────────────────────────────


async def test_dummy_plugin_passes_contract_without_core_changes(app_factory):
    _, factory, _, settings = app_factory

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        shutil.copytree(FIXTURE_PLUGIN_DIR, tmp_plugins / "example_plugin")

        app = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app.router.lifespan_context(app):
            pass

        async with factory() as session:
            result = await session.execute(select(Plugin))
            plugins = list(result.scalars())

        assert len(plugins) == 1
        plugin = plugins[0]
        assert plugin.name == "example_upper"
        assert plugin.enabled is False

        candidates, rejected = discover(tmp_plugins)
        assert len(candidates) == 1
        assert rejected == []
        violations = contract_violations(candidates[0])
        assert violations == []


# ── Scenario 2 ──────────────────────────────────────────────────────────────


async def test_discovery_is_idempotent_across_restarts(app_factory):
    _, factory, _, settings = app_factory

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        shutil.copytree(FIXTURE_PLUGIN_DIR, tmp_plugins / "example_plugin")

        app = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app.router.lifespan_context(app):
            pass

        async with factory() as session:
            result = await session.execute(select(Plugin))
            plugin = result.scalars().one()
            assert plugin.name == "example_upper"
            assert plugin.version == "1.0.0"
            assert plugin.enabled is False

        async with factory() as session:
            async with session.begin():
                plugin = (await session.execute(select(Plugin))).scalars().one()
                plugin.enabled = True
                await session.flush()

        manifest_path = tmp_plugins / "example_plugin" / "plugin.json"
        import json
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "1.1.0"
        manifest_path.write_text(json.dumps(manifest))

        app2 = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app2.router.lifespan_context(app2):
            pass

        async with factory() as session:
            result = await session.execute(select(Plugin))
            plugins = list(result.scalars())
        assert len(plugins) == 1
        plugin = plugins[0]
        assert plugin.name == "example_upper"
        assert plugin.version == "1.1.0"
        assert plugin.enabled is True


# ── Scenario 3 ──────────────────────────────────────────────────────────────


async def test_end_to_end_execution_through_runner(app_factory):
    _, factory, _, settings = app_factory
    client = await logged_in_client(app_factory)

    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={
            "name": "Main feed",
            "source_format": "tsv",
            "source_url": "http://test.local/feed.tsv",
        },
    )
    assert resp.status_code == 201
    feed_source_id = resp.json()["id"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        shutil.copytree(FIXTURE_PLUGIN_DIR, tmp_plugins / "example_plugin")

        app = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app.router.lifespan_context(app):
            pass

        async with factory() as session:
            async with session.begin():
                plugin = (await session.execute(
                    select(Plugin).where(Plugin.name == "example_upper")
                )).scalars().one()

                config = PluginConfig(
                    plugin_id=plugin.id,
                    scope="global",
                    key="default",
                    config={"suffix": "_sfx"},
                )
                session.add(config)
                await session.flush()

                pipeline = ModulePipeline(
                    feed_source_id=feed_source_id,
                    name="pipe",
                    version="1",
                    definition={},
                )
                session.add(pipeline)
                await session.flush()

                instance = ModuleInstance(
                    pipeline_id=pipeline.id,
                    plugin_id=plugin.id,
                    position=0,
                    name="upper",
                    configuration={},
                )
                session.add(instance)
                await session.flush()

                feed_source = await session.get(FeedSource, feed_source_id)
                feed_source.active_pipeline_id = pipeline.id
                await session.flush()

        plugin_registry: dict[str, Any] = {}
        candidates, _ = discover(tmp_plugins)
        for c in candidates:
            plugin_registry[c.manifest.id] = c.instance

        fetcher = StubFetcher(FEED_TSV)
        registry = load_registry()
        steps = default_steps(fetcher, registry, plugin_registry)
        runner = PipelineRunner(LockRegistry(), factory, list(steps))
        run_id = await runner.execute(feed_source_id)

        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
        assert run.status == "success"
        assert run.statistics.get("plugins", {}).get("processed") == 1
        assert run.statistics.get("plugins", {}).get("dropped") == 1

        async with factory() as session:
            result = await session.execute(
                select(StagingProduct).where(StagingProduct.feed_source_id == feed_source_id)
            )
            rows = {r.product_id: r for r in result.scalars()}

        row_a = rows["A1"]
        assert row_a.processed_data is not None
        assert row_a.excluded is False
        assert row_a.processed_data["title"] == "RED SHIRT"
        assert row_a.processed_data.get("title_suffix") is not None

        row_drop = rows["drop-me"]
        assert row_drop.processed_data is None
        assert row_drop.excluded is True


# ── Scenario 4 ──────────────────────────────────────────────────────────────


async def test_error_isolation_preserves_last_known_good(app_factory):
    _, factory, _, settings = app_factory
    client = await logged_in_client(app_factory)

    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={
            "name": "Main feed",
            "source_format": "tsv",
            "source_url": "http://test.local/feed.tsv",
        },
    )
    assert resp.status_code == 201
    feed_source_id = resp.json()["id"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        shutil.copytree(FIXTURE_PLUGIN_DIR, tmp_plugins / "example_plugin")

        error_plugin_dir = tmp_plugins / "error_plugin"
        error_plugin_dir.mkdir()
        (error_plugin_dir / "plugin.json").write_text(
            '{'
            '"id": "error_on_a1",'
            '"name": "Error on A1",'
            '"version": "1.0.0",'
            '"extension_point": "pipeline_module",'
            '"config_scope": ["global"],'
            '"data_scope": ["global"],'
            '"config_schema": {"type": "object"},'
            '"data_schema": {"type": "object"}'
            '}'
        )
        (error_plugin_dir / "plugin.py").write_text(
            "class Plugin:\n"
            "    def validate_config(self, config):\n"
            "        pass\n"
            "    def process(self, product, config, data, ctx):\n"
            '        if product.get("id") == "A1":\n'
            '            raise ValueError("forced error on A1")\n'
            "        return product\n"
        )

        app = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app.router.lifespan_context(app):
            pass

        async with factory() as session:
            async with session.begin():
                plugin = (await session.execute(
                    select(Plugin).where(Plugin.name == "error_on_a1")
                )).scalars().one()

                pipeline = ModulePipeline(
                    feed_source_id=feed_source_id,
                    name="pipe",
                    version="1",
                    definition={},
                )
                session.add(pipeline)
                await session.flush()

                instance = ModuleInstance(
                    pipeline_id=pipeline.id,
                    plugin_id=plugin.id,
                    position=0,
                    name="err",
                    configuration={},
                )
                session.add(instance)
                await session.flush()

                feed_source = await session.get(FeedSource, feed_source_id)
                feed_source.active_pipeline_id = pipeline.id
                await session.flush()

        plugin_registry: dict[str, Any] = {}
        candidates, _ = discover(tmp_plugins)
        for c in candidates:
            plugin_registry[c.manifest.id] = c.instance

        fetcher = StubFetcher(FEED_TSV)
        registry = load_registry()
        steps = default_steps(fetcher, registry, plugin_registry)
        runner = PipelineRunner(LockRegistry(), factory, list(steps))
        run_id = await runner.execute(feed_source_id)

        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
        assert run.status == "success"
        assert run.failed_count >= 1

        async with factory() as session:
            result = await session.execute(
                select(StagingProduct).where(
                    StagingProduct.feed_source_id == feed_source_id,
                    StagingProduct.product_id == "A1",
                )
            )
            row_a1 = result.scalars().one()

        assert row_a1.processed_data is None
        assert row_a1.excluded is False


# ── Scenario 4b: drop→pass reactivation ─────────────────────────────────────


async def test_drop_then_pass_reactivation(app_factory):
    _, factory, _, settings = app_factory
    client = await logged_in_client(app_factory)

    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={
            "name": "Main feed",
            "source_format": "tsv",
            "source_url": "http://test.local/feed.tsv",
        },
    )
    assert resp.status_code == 201
    feed_source_id = resp.json()["id"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        tmp_plugins.mkdir()
        dropper_dir = tmp_plugins / "conditional_dropper"
        dropper_dir.mkdir()
        (dropper_dir / "plugin.json").write_text(
            '{'
            '"id": "conditional_dropper",'
            '"name": "Conditional Dropper",'
            '"version": "1.0.0",'
            '"extension_point": "pipeline_module",'
            '"config_scope": ["global"],'
            '"data_scope": ["global"],'
            '"config_schema": {"type": "object"},'
            '"data_schema": {"type": "object"}'
            '}'
        )
        (dropper_dir / "plugin.py").write_text(
            "class Plugin:\n"
            "    def validate_config(self, config):\n"
            "        pass\n"
            "    def process(self, product, config, data, ctx):\n"
            '        if product.get("title", "").startswith("X"):\n'
            "            return None\n"
            "        return product\n"
        )

        app = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app.router.lifespan_context(app):
            pass

        async with factory() as session:
            async with session.begin():
                plugin = (await session.execute(
                    select(Plugin).where(Plugin.name == "conditional_dropper")
                )).scalars().one()

                pipeline = ModulePipeline(
                    feed_source_id=feed_source_id,
                    name="pipe",
                    version="1",
                    definition={},
                )
                session.add(pipeline)
                await session.flush()

                instance = ModuleInstance(
                    pipeline_id=pipeline.id,
                    plugin_id=plugin.id,
                    position=0,
                    name="dropper",
                    configuration={},
                )
                session.add(instance)
                await session.flush()

                feed_source = await session.get(FeedSource, feed_source_id)
                feed_source.active_pipeline_id = pipeline.id
                await session.flush()

        plugin_registry: dict[str, Any] = {}
        candidates, _ = discover(tmp_plugins)
        for c in candidates:
            plugin_registry[c.manifest.id] = c.instance

        tsv_run1 = b"sku\ttitle\tean\nA1\tX-dropped\t1234567890123\n"
        fetcher = StubFetcher(tsv_run1)
        registry = load_registry()
        steps = default_steps(fetcher, registry, plugin_registry)
        runner = PipelineRunner(LockRegistry(), factory, list(steps))
        run_id = await runner.execute(feed_source_id)

        async with factory() as session:
            row = (await session.execute(
                select(StagingProduct).where(
                    StagingProduct.feed_source_id == feed_source_id,
                    StagingProduct.product_id == "A1",
                )
            )).scalars().one()
        assert row.excluded is True
        assert row.processed_data is None

        tsv_run2 = b"sku\ttitle\tean\nA1\tY-kept\t1234567890123\n"
        fetcher.data = tsv_run2
        steps2 = default_steps(fetcher, registry, plugin_registry)
        runner2 = PipelineRunner(LockRegistry(), factory, list(steps2))
        run_id2 = await runner2.execute(feed_source_id)

        async with factory() as session:
            row = (await session.execute(
                select(StagingProduct).where(
                    StagingProduct.feed_source_id == feed_source_id,
                    StagingProduct.product_id == "A1",
                )
            )).scalars().one()
        assert row.excluded is False
        assert row.processed_data is not None
        assert row.processed_data["title"] == "Y-kept"


# ── Scenario 5 ──────────────────────────────────────────────────────────────


async def test_toggle_and_config_round_trip_via_api(app_factory):
    _, factory, _, settings = app_factory

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        shutil.copytree(FIXTURE_PLUGIN_DIR, tmp_plugins / "example_plugin")

        app = create_app(settings=settings, db_session_factory=factory, plugins_dir=tmp_plugins)
        async with app.router.lifespan_context(app):
            pass

        client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
        resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
        assert resp.status_code == 200

        resp = await client.get("/plugins")
        assert resp.status_code == 200
        plugins = resp.json()
        assert len(plugins) == 1
        assert plugins[0]["id"] == "example_upper"
        assert plugins[0]["enabled"] is False

        resp = await client.put(
            "/plugins/example_upper/enabled",
            json={"enabled": True},
        )
        assert resp.status_code == 200

        resp = await client.get("/plugins")
        assert resp.status_code == 200
        assert resp.json()[0]["enabled"] is True

        resp = await client.put(
            "/plugins/example_upper/config",
            json={"suffix": "_test"},
        )
        assert resp.status_code == 200

        resp = await client.get("/plugins/example_upper/config")
        assert resp.status_code == 200
        assert resp.json() == {"suffix": "_test"}

        resp = await client.put(
            "/plugins/example_upper/config?feed_source_id=99999",
            json={"suffix": "_test"},
        )
        assert resp.status_code == 422


# ── Scenario 6: meta-gate ──────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("M6_RUN_META_GATE"),
    reason="meta-gate: run standalone with M6_RUN_META_GATE=1",
)
def test_full_suite_serial_and_parallel_green():
    import subprocess
    import sys

    backend_dir = Path(__file__).resolve().parent.parent
    self_test = "tests/test_m6_acceptance.py::test_full_suite_serial_and_parallel_green"
    child_env = {**os.environ, "_M6_META_GATE": "1"}

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-n0", "--tb=short", "-q",
         "--deselect", self_test],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        timeout=900,
        env=child_env,
    )
    assert result.returncode == 0, f"Serial suite failed:\n{result.stdout}\n{result.stderr}"

    result_par = subprocess.run(
        [sys.executable, "-m", "pytest", "--tb=short", "-q",
         "--deselect", self_test],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        timeout=900,
        env=child_env,
    )
    assert result_par.returncode == 0, f"Parallel suite failed:\n{result_par.stdout}\n{result_par.stderr}"

    result_compile = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(backend_dir / "app")],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )
    assert result_compile.returncode == 0, f"compileall failed:\n{result_compile.stdout}"

    result_diff = subprocess.run(
        ["git", "diff", "--check", "--", ":!.superpowers"],
        cwd=str(backend_dir.parent),
        capture_output=True,
        text=True,
    )
    assert result_diff.returncode == 0, f"git diff --check failed:\n{result_diff.stdout}"
