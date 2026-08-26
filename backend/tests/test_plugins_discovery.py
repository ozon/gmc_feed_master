"""Tests for plugin discovery, registration, and mounting (Task 4)."""

import json
import textwrap

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin
from app.plugins.discovery import Candidate, collect_router, discover, register_candidates

pytestmark = pytest.mark.asyncio

MANIFEST = {
    "id": "example_upper",
    "name": "Example Upper",
    "version": "1.0.0",
    "extension_point": "pipeline_module",
    "config_schema": {"type": "object"},
    "data_schema": {"type": "object"},
}

PLUGIN_CODE = """
    class Plugin:
        def process(self, product, config, data, ctx):
            return product
"""


def write_plugin(
    directory,
    manifest=None,
    code=PLUGIN_CODE,
    filename="plugin.py",
):
    directory.mkdir(parents=True, exist_ok=True)
    doc = MANIFEST.copy() if manifest is None else manifest
    (directory / "plugin.json").write_text(json.dumps(doc))
    if code is not None:
        (directory / filename).write_text(textwrap.dedent(code))


class TestDiscoverUnit:
    def test_missing_dir_returns_no_candidates_and_no_reasons(self, tmp_path):
        candidates, reasons = discover(tmp_path / "does_not_exist")
        assert candidates == []
        assert reasons == []

    def test_valid_plugin_discovered_as_non_core(self, tmp_path):
        write_plugin(tmp_path / "upper")
        candidates, reasons = discover(tmp_path)
        assert reasons == []
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.manifest.id == "example_upper"
        assert candidate.directory == tmp_path / "upper"
        assert candidate.core is False
        assert candidate.router is None
        assert callable(candidate.instance.process)

    def test_core_subdirectory_sets_core_flag(self, tmp_path):
        write_plugin(tmp_path / "core" / "labelizer", manifest=dict(MANIFEST, id="labelizer"))
        write_plugin(tmp_path / "third_party")
        candidates, _ = discover(tmp_path)
        by_id = {c.manifest.id: c for c in candidates}
        assert by_id["example_upper"].core is False
        assert by_id["labelizer"].core is True

    def test_directory_without_plugin_json_is_skipped(self, tmp_path):
        (tmp_path / "scratch").mkdir()
        write_plugin(tmp_path / "upper")
        candidates, reasons = discover(tmp_path)
        assert reasons == []
        assert [c.manifest.id for c in candidates] == ["example_upper"]

    def test_invalid_manifest_rejected_with_reason(self, tmp_path):
        bad = dict(MANIFEST)
        del bad["version"]
        write_plugin(tmp_path / "broken", manifest=bad)
        write_plugin(tmp_path / "upper")
        candidates, reasons = discover(tmp_path)
        assert len(candidates) == 1
        assert len(reasons) == 1
        assert "version" in reasons[0]

    def test_loader_failure_rejected_with_reason(self, tmp_path):
        write_plugin(tmp_path / "no_module", code=None)
        candidates, reasons = discover(tmp_path)
        assert candidates == []
        assert len(reasons) == 1
        assert "no_module" in reasons[0] or "plugin.py" in reasons[0]

    @pytest.mark.parametrize("path", ["/config", "/data", "/config/thing", "/data/x/y"])
    def test_reserved_route_paths_reject_candidate(self, tmp_path, path):
        code = f"""
            from fastapi import APIRouter

            class Plugin:
                def process(self, product, config, data, ctx):
                    return product
                def register_routes(self, router):
                    router.add_api_route({path!r}, lambda: {{}})
        """
        write_plugin(tmp_path / "sneaky", code=code)
        candidates, reasons = discover(tmp_path)
        assert candidates == []
        assert len(reasons) == 1

    @pytest.mark.parametrize("path", ["/configs", "/database"])
    def test_similar_but_unreserved_paths_are_accepted(self, tmp_path, path):
        code = f"""
            from fastapi import APIRouter

            class Plugin:
                def process(self, product, config, data, ctx):
                    return product
                def register_routes(self, router):
                    router.add_api_route({path!r}, lambda: {{}})
        """
        write_plugin(tmp_path / "fine", code=code)
        candidates, reasons = discover(tmp_path)
        assert reasons == []
        assert len(candidates) == 1
        assert candidates[0].router is not None


class TestCollectRouterUnit:
    def test_returns_none_when_instance_has_no_register_routes(self, tmp_path):
        write_plugin(tmp_path / "plain")
        candidates, _ = discover(tmp_path)
        assert collect_router(candidates[0]) is None

    def test_returns_router_from_register_routes(self, tmp_path):
        code = """
            from fastapi import APIRouter

            class Plugin:
                def process(self, product, config, data, ctx):
                    return product
                def register_routes(self, router: APIRouter) -> APIRouter:
                    router.add_api_route("/status", lambda: {"ok": True})
                    return router
        """
        write_plugin(tmp_path / "routed", code=code)
        candidate = discover(tmp_path)[0][0]
        router = collect_router(candidate)
        assert router is not None
        assert router.routes[-1].path == "/status"


def _make(url):
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class TestRegisterCandidatesIntegration:
    async def test_second_registration_updates_version_and_preserves_enabled(
        self, tmp_path, isolated_database_url
    ):
        engine, factory = _make(isolated_database_url)
        write_plugin(tmp_path / "upper")
        candidates, _ = discover(tmp_path)

        async with factory() as session:
            async with session.begin():
                pk_map = await register_candidates(session, candidates)
        first_pk = pk_map["example_upper"]

        async with factory() as session:
            async with session.begin():
                row = await session.get(Plugin, first_pk)
                row.enabled = True

        bumped = dict(MANIFEST, version="2.0.0")
        write_plugin(tmp_path / "upper", manifest=bumped)
        candidates_v2, _ = discover(tmp_path)
        async with factory() as session:
            async with session.begin():
                pk_map_v2 = await register_candidates(session, candidates_v2)

        assert pk_map_v2["example_upper"] == first_pk
        async with factory() as session:
            rows = (await session.execute(select(Plugin))).scalars().all()
            assert len(rows) == 1
            assert rows[0].version == "2.0.0"
            assert rows[0].manifest["version"] == "2.0.0"
            assert rows[0].enabled is True
            assert rows[0].id == first_pk
        await engine.dispose()

    async def test_insert_defaults_enabled_to_core_flag(
        self, tmp_path, isolated_database_url
    ):
        engine, factory = _make(isolated_database_url)
        write_plugin(tmp_path / "core" / "builtin", manifest=dict(MANIFEST, id="builtin"))
        write_plugin(tmp_path / "third_party")
        candidates, _ = discover(tmp_path)
        async with factory() as session:
            async with session.begin():
                pk_map = await register_candidates(session, candidates)

        async with factory() as session:
            third = await session.get(Plugin, pk_map["example_upper"])
            core = await session.get(Plugin, pk_map["builtin"])
            assert third.enabled is False
            assert core.enabled is True
        await engine.dispose()

    async def test_module_instance_fk_survives_reregistration(
        self, tmp_path, isolated_database_url
    ):
        from app.models.client import Client
        from app.models.feed_source import FeedSource

        engine, factory = _make(isolated_database_url)
        write_plugin(tmp_path / "upper")
        candidates, _ = discover(tmp_path)
        async with factory() as session:
            async with session.begin():
                pk_map = await register_candidates(session, candidates)
                plugin_pk = pk_map["example_upper"]

                client = Client(name="Acme")
                session.add(client)
                await session.flush()
                feed_source = FeedSource(client_id=client.id, name="US feed", source_format="tsv")
                session.add(feed_source)
                await session.flush()
                pipeline = ModulePipeline(
                    feed_source_id=feed_source.id, name="pipe", version="1", definition={}
                )
                session.add(pipeline)
                await session.flush()
                instance = ModuleInstance(
                    pipeline_id=pipeline.id,
                    plugin_id=plugin_pk,
                    position=0,
                    name="lbl",
                    configuration={"slot": "custom_label_0"},
                )
                session.add(instance)

        bumped = dict(MANIFEST, version="9.9.9")
        write_plugin(tmp_path / "upper", manifest=bumped)
        candidates_v2, _ = discover(tmp_path)
        async with factory() as session:
            async with session.begin():
                await register_candidates(session, candidates_v2)

        async with factory() as session:
            refreshed = (
                await session.execute(select(ModuleInstance).where(ModuleInstance.plugin_id == plugin_pk))
            ).scalar_one()
            assert refreshed.name == "lbl"
            parent = await session.get(Plugin, refreshed.plugin_id)
            assert parent is not None
            assert parent.version == "9.9.9"
        await engine.dispose()
