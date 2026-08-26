import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin, PluginConfig, PluginData
from app.staging.config_resolver import resolve_config_bundle

pytestmark = pytest.mark.asyncio


def _make(url):
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    plugin = Plugin(
        name="labelizer",
        version="1.0.0",
        manifest={
            "id": "labelizer",
            "config_scope": ["global", "client"],
            "data_scope": "client",
        },
    )
    session.add(plugin)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US feed", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    pipeline = ModulePipeline(
        feed_source_id=feed_source.id, name="pipe", version="1", definition={}
    )
    session.add(pipeline)
    await session.flush()
    feed_source.active_pipeline_id = pipeline.id
    instance = ModuleInstance(
        pipeline_id=pipeline.id,
        plugin_id=plugin.id,
        position=0,
        name="lbl",
        configuration={"slot": "custom_label_0"},
    )
    session.add(instance)
    session.add_all([
        PluginConfig(plugin_id=plugin.id, scope="global", key="dims",
                     config={"min_price": "10"}),
        PluginConfig(plugin_id=plugin.id, scope="client", client_id=client.id,
                     key="dims", config={"min_price": "20"}),
        PluginData(plugin_id=plugin.id, scope="client", client_id=client.id,
                   key="ids", data={"list": ["1"]}),
    ])
    await session.flush()
    return client, plugin, feed_source


async def test_bundle_resolves_instances_and_merge(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, _, feed_source = await _seed(session)
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["pipeline"] == {"name": "pipe", "version": "1"}
    entry = bundle["instances"][0]
    assert entry["position"] == 0
    assert entry["plugin"] == "labelizer"
    assert entry["plugin_version"] == "1.0.0"
    assert entry["instance_config"] == {"slot": "custom_label_0"}
    assert entry["resolved_config"] == {"min_price": "20"}
    assert entry["resolved_data"] == {"list": ["1"]}
    await engine.dispose()


async def test_bundle_without_active_pipeline_is_stable(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
            session.add(feed_source)
            await session.flush()
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle == {"pipeline": None, "instances": []}
    await engine.dispose()


async def test_client_scope_of_other_client_is_ignored(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, plugin, feed_source = await _seed(session)
            other = Client(name="Other")
            session.add(other)
            await session.flush()
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="client", client_id=other.id,
                key="dims", config={"min_price": "999"},
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["instances"][0]["resolved_config"] == {"min_price": "20"}
    await engine.dispose()


async def test_undeclared_feed_source_scope_never_applies(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, plugin, feed_source = await _seed(session)
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="feed_source",
                feed_source_id=feed_source.id, key="dims",
                config={"min_price": "999"},
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["instances"][0]["resolved_config"] == {"min_price": "20"}
    await engine.dispose()


async def test_declared_feed_source_scope_wins(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            plugin = Plugin(
                name="labelizer",
                version="1.0.0",
                manifest={
                    "id": "labelizer",
                    "config_scope": ["global", "client", "feed_source"],
                    "data_scope": "client",
                },
            )
            session.add(plugin)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id, name="US feed", source_format="tsv"
            )
            session.add(feed_source)
            await session.flush()
            pipeline = ModulePipeline(
                feed_source_id=feed_source.id, name="pipe", version="1", definition={}
            )
            session.add(pipeline)
            await session.flush()
            feed_source.active_pipeline_id = pipeline.id
            session.add(ModuleInstance(
                pipeline_id=pipeline.id,
                plugin_id=plugin.id,
                position=0,
                name="lbl",
                configuration={},
            ))
            session.add_all([
                PluginConfig(plugin_id=plugin.id, scope="global", key="dims",
                             config={"min_price": "10"}),
                PluginConfig(plugin_id=plugin.id, scope="client",
                             client_id=client.id, key="dims",
                             config={"min_price": "20"}),
                PluginConfig(plugin_id=plugin.id, scope="feed_source",
                             feed_source_id=feed_source.id, key="dims",
                             config={"min_price": "30"}),
            ])
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["instances"][0]["resolved_config"] == {"min_price": "30"}
    await engine.dispose()
