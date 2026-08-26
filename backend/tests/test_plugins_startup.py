"""Tests for plugin discovery startup wiring via the app lifespan (Task 4)."""

import json  # noqa: F401  (re-exported helper contract)
import textwrap  # noqa: F401

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import create_app
from app.models.plugin import Plugin
from tests.test_plugins_discovery import MANIFEST, write_plugin

pytestmark = pytest.mark.asyncio


def _all_route_paths(app):
    paths = []

    def add(prefix, route):
        path = getattr(route, "path", None)
        if path is not None:
            paths.append(prefix + path)

    for route in app.routes:
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original is not None and context is not None:
            prefix = getattr(context, "prefix", "")
            for sub in original.routes:
                add(prefix, sub)
        else:
            add("", route)
    return paths


async def test_lifespan_discovers_registers_and_mounts(
    tmp_path, settings, isolated_database_url
):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    code = """
        from fastapi import APIRouter

        class Plugin:
            def process(self, product, config, data, ctx):
                return product
            def register_routes(self, router: APIRouter) -> APIRouter:
                router.add_api_route("/status", lambda: {"ok": True})
                return router
    """
    write_plugin(tmp_path / "upper", manifest=MANIFEST, code=code)

    app = create_app(
        settings=settings,
        db_session_factory=factory,
        plugins_dir=tmp_path,
    )

    async with app.router.lifespan_context(app):
        assert app.state.plugin_registry["example_upper"] is not None
        assert "/plugins/example_upper/status" in _all_route_paths(app)

    async with factory() as session:
        row = (
            await session.execute(select(Plugin).where(Plugin.name == "example_upper"))
        ).scalar_one()
        assert row.version == MANIFEST["version"]
        assert row.enabled is False
    await engine.dispose()


async def test_create_app_without_settings_or_plugins_dir_leaves_state_none(
    isolated_database_url,
):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(db_session_factory=factory)
    assert app.state.plugins_dir is None
    assert app.state.plugin_registry == {}
    await engine.dispose()


async def test_create_app_falls_back_to_settings_plugins_dir(settings, isolated_database_url):
    from pathlib import Path

    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(settings=settings, db_session_factory=factory)
    assert app.state.plugins_dir == Path(settings.plugins_dir)
    await engine.dispose()
