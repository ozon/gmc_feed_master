import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.staging import StagingProduct
from app.pipeline import RunState, StepContext
from app.pipeline.steps import PluginStep, StagingStep

pytestmark = pytest.mark.asyncio


class FactoryAdapter:
    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    session.add(IngestionRun(id=1, feed_source_id=feed_source.id, status="completed"))
    await session.flush()
    return feed_source


def _ctx(factory, feed_source_id, products, bundle=None):
    state = RunState(
        products=list(products),
        client_id=feed_source_id,
        config_bundle=bundle if bundle is not None else {"instances": []},
        product_pks={},
    )
    return StepContext(
        feed_source_id=feed_source_id,
        session_factory=FactoryAdapter(factory),
        logger=logging.getLogger(__name__),
        run_state=state,
        ingestion_run_id=1,
    )


class UpperPlugin:
    def process(self, product, config, data, rctx):
        return {**product, "title": product["title"].upper()}


class MutatingPlugin:
    def __init__(self):
        self.seen_originals = []

    def process(self, product, config, data, rctx):
        self.seen_originals.append(rctx.original_product)
        return {**product, "stage": len(self.seen_originals)}


class DroppingPlugin:
    def process(self, product, config, data, rctx):
        return None


class ExplodingPlugin:
    def process(self, product, config, data, rctx):
        raise RuntimeError("boom")


async def _staged_rows(factory):
    async with factory() as session:
        result = await session.execute(select(StagingProduct))
        return {row.product_id: row for row in result.scalars()}


async def _prepare(factory, products):
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    staging_ctx = _ctx(factory, feed_source.id, products)
    await StagingStep().execute(staging_ctx)
    staged_pks = {
        pid: row.id for pid, row in (await _staged_rows(factory)).items()
    }
    return feed_source, staged_pks


async def _run_plugin_step(factory, feed_source, products, pks, bundle, registry):
    ctx = _ctx(factory, feed_source.id, products, bundle)
    ctx.run_state.product_pks.update(pks)
    result = await PluginStep(registry).execute(ctx)
    rows = await _staged_rows(factory)
    return result, rows, ctx


async def test_transform_survivor_persists_processed_data(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)
    bundle = {"instances": [
        {"plugin": "upper", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle, {"upper": UpperPlugin()}
    )

    assert result.processed_count == 1
    assert result.failed_count == 0
    assert rows["1"].processed_data == {"id": "1", "title": "A"}
    assert rows["1"].excluded is False
    await engine.dispose()


async def test_drop_clears_processed_data_and_sets_excluded(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)
    # First run passes so processed_data is populated.
    pass_bundle = {"instances": [
        {"plugin": "upper", "resolved_config": {}, "resolved_data": {}},
    ]}
    await _run_plugin_step(
        factory, feed_source, products, pks, pass_bundle, {"upper": UpperPlugin()}
    )
    drop_bundle = {"instances": [
        {"plugin": "drop", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, drop_bundle, {"drop": DroppingPlugin()}
    )

    assert result.statistics["plugins"]["dropped"] == 1
    assert result.processed_count == 0
    assert rows["1"].excluded is True
    assert rows["1"].processed_data is None
    await engine.dispose()


async def test_exception_aborts_product_without_staging_write(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks,
        {"instances": []},
        {},
    )
    last_good_raw = dict(rows["1"].raw_data)
    assert rows["1"].processed_data == {"id": "1", "title": "a"}
    assert rows["1"].excluded is False

    explode_bundle = {"instances": [
        {"plugin": "explode", "resolved_config": {}, "resolved_data": {}},
    ]}
    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, explode_bundle,
        {"explode": ExplodingPlugin()},
    )

    assert result.failed_count == 1
    assert result.processed_count == 0  # errored product is not a survivor
    assert result.statistics["plugins"] == {
        "processed": 0, "dropped": 0, "errored": 1,
    }
    assert rows["1"].raw_data == last_good_raw
    assert rows["1"].processed_data == {"id": "1", "title": "a"}
    assert rows["1"].excluded is False
    await engine.dispose()


async def test_multi_instance_chains_in_order(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)
    mutating = MutatingPlugin()
    bundle = {"instances": [
        {"plugin": "mut", "resolved_config": {}, "resolved_data": {}},
        {"plugin": "upper", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle,
        {"mut": mutating, "upper": UpperPlugin()},
    )

    assert mutating.seen_originals[0] == {"id": "1", "title": "a"}
    assert rows["1"].processed_data == {"id": "1", "title": "A", "stage": 1}
    await engine.dispose()


async def test_original_product_is_deep_copy_of_incoming(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "meta": {"tags": ["x"]}}]
    feed_source, pks = await _prepare(factory, products)
    seen = []

    class Mutator:
        def process(self, product, config, data, rctx):
            seen.append(rctx.original_product)
            if len(seen) == 1:
                product["meta"]["tags"].append("y")
            return product

    bundle = {"instances": [
        {"plugin": "m1", "resolved_config": {}, "resolved_data": {}},
        {"plugin": "m2", "resolved_config": {}, "resolved_data": {}},
    ]}

    _, _, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle,
        {"m1": Mutator(), "m2": Mutator()},
    )

    # Second instance's original_product reflects the incoming product of THIS
    # step, not the mutated `current` from the first instance.
    assert seen[1]["meta"]["tags"] == ["x"]
    await engine.dispose()


async def test_statistics_shape(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [
        {"id": "1", "title": "a"},
        {"id": "2", "title": "b"},
    ]
    feed_source, pks = await _prepare(factory, products)

    class DropTwo:
        def process(self, product, config, data, rctx):
            return None if product["id"] == "2" else product

    bundle = {"instances": [
        {"plugin": "mixed", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, _, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle, {"mixed": DropTwo()}
    )

    assert result.statistics["plugins"] == {
        "processed": 1, "dropped": 1, "errored": 0,
    }
    await engine.dispose()


async def test_registry_miss_skips_instance(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)
    bundle = {"instances": [
        {"plugin": "missing", "resolved_config": {}, "resolved_data": {}},
        {"plugin": "upper", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle, {"upper": UpperPlugin()}
    )

    assert result.failed_count == 0
    assert rows["1"].processed_data == {"id": "1", "title": "A"}
    await engine.dispose()


async def test_products_without_staged_pk_flow_through_without_outcome_write(
    isolated_database_url,
):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "ghost", "title": "a"}]
    feed_source, _pks = await _prepare(factory, [])
    bundle = {"instances": [
        {"plugin": "upper", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, {}, bundle, {"upper": UpperPlugin()}
    )

    assert result.processed_count == 1
    assert [p["title"] for p in _.run_state.products] == ["A"]
    assert set(rows) == set()
    await engine.dispose()


async def test_empty_bundle_passes_everything_through(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)

    result, rows, ctx = await _run_plugin_step(
        factory, feed_source, products, pks, {"instances": []}, {}
    )

    assert result.processed_count == 1
    assert ctx.run_state.products == [{"id": "1", "title": "a"}]
    assert rows["1"].processed_data == {"id": "1", "title": "a"}
    await engine.dispose()
