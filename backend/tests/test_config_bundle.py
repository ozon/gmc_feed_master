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


async def test_bundle_excludes_disabled_instances(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, plugin, feed_source = await _seed(session)
            pipeline = await session.get(ModulePipeline, feed_source.active_pipeline_id)
            session.add(ModuleInstance(
                pipeline_id=pipeline.id,
                plugin_id=plugin.id,
                position=1,
                name="lbl-disabled",
                configuration={"slot": "custom_label_1"},
                enabled=False,
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    positions = [i["position"] for i in bundle["instances"]]
    assert positions == [0]  # only the enabled instance is in the bundle
    assert bundle["instances"][0]["instance_config"] == {"slot": "custom_label_0"}
    await engine.dispose()


async def test_bundle_slotrules_union_by_id_matches_frontend(
    isolated_database_url,
):
    # Keep in lockstep with test_config_merge.py and
    # frontend scopeMerge.test.ts (spec §1.2 gate).
    global_rules = [
        {"id": "g1", "name": "Global Mid", "isActive": True,
         "targetSlot": "custom_label_1", "matchField": "id",
         "valueTemplate": "{brand} - Mid"},
        {"id": "g2", "name": "Global Top", "isActive": True,
         "targetSlot": "custom_label_0", "matchField": "id",
         "valueTemplate": "{brand} - Top"},
    ]
    client_rules = [
        {"id": "g1", "name": "Client Mid", "isActive": True,
         "targetSlot": "custom_label_1", "matchField": "brand",
         "valueTemplate": "{brand} - Client"},
        {"id": "c2", "name": "Client Only", "isActive": True,
         "targetSlot": "custom_label_0", "matchField": "id",
         "valueTemplate": "{brand} - ClientOnly"},
        {"id": "c3", "name": "Same Slot As G1", "isActive": True,
         "targetSlot": "custom_label_1", "matchField": "id",
         "valueTemplate": "{brand} - C3"},
    ]
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            plugin = Plugin(
                name="labelizer", version="1.0.0",
                manifest={
                    "id": "labelizer",
                    "config_scope": ["global", "client"],
                    "data_scope": "client",
                    "config_merge": {"slotRules": {
                        "strategy": "union_by_key", "key": "id",
                    }},
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
                feed_source_id=feed_source.id, name="pipe", version="1",
                definition={},
            )
            session.add(pipeline)
            await session.flush()
            feed_source.active_pipeline_id = pipeline.id
            session.add(ModuleInstance(
                pipeline_id=pipeline.id, plugin_id=plugin.id,
                position=0, name="lbl", configuration={},
            ))
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="global", key="default",
                config={"slotRules": global_rules},
            ))
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="client", client_id=client.id,
                key="default", config={"slotRules": client_rules},
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    rules = bundle["instances"][0]["resolved_config"]["slotRules"]
    assert [r["id"] for r in rules] == ["g1", "g2", "c2", "c3"]
    assert [r["name"] for r in rules] == [
        "Client Mid", "Global Top", "Client Only", "Same Slot As G1",
    ]
    await engine.dispose()
