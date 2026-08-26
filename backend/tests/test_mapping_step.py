import logging
from types import SimpleNamespace

import pytest

from app.ingest.report import SourceField
from app.mapping import MappingDocumentError, MappingEntry
from app.pipeline import MappingStep, RunState, StepContext
from registry.loader import load_registry


class FakeSession:
    def __init__(self, feed_source):
        self._feed_source = feed_source

    async def get(self, model, pk):
        return self._feed_source

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSessionFactory:
    def __init__(self, feed_source):
        self._feed_source = feed_source

    def __call__(self):
        return FakeSession(self._feed_source)


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def _feed_source(field_mapping=None):
    return SimpleNamespace(
        field_mapping=field_mapping if field_mapping is not None else {}
    )


def _ctx(feed_source, run_state=None):
    return StepContext(
        feed_source_id=1,
        session_factory=FakeSessionFactory(feed_source),
        logger=logging.getLogger("test"),
        run_state=run_state if run_state is not None else RunState(),
    )


class TestFirstIngestion:
    @pytest.mark.asyncio
    async def test_auto_maps_persists_and_applies(self, registry):
        source_fields = [
            SourceField("id", "scalar"),
            SourceField("title", "scalar"),
            SourceField("ean", "scalar"),
            SourceField("margin", "scalar"),
        ]
        products = [{"id": "1", "title": "Shirt", "ean": "123", "margin": "10"}]
        run_state = RunState(products=products, source_fields=list(source_fields))
        feed_source = _feed_source()

        result = await MappingStep(registry).execute(_ctx(feed_source, run_state))

        assert feed_source.field_mapping["auto_mapped"] is True
        assert feed_source.field_mapping["mappings"] == {
            "id": {"target": "id", "origin": "auto"},
            "title": {"target": "title", "origin": "auto"},
            "ean": {"target": "gtin", "origin": "synonym"},
        }
        assert feed_source.field_mapping["source_fields"] == [
            {"name": "id", "kind": "scalar", "sub_fields": []},
            {"name": "title", "kind": "scalar", "sub_fields": []},
            {"name": "ean", "kind": "scalar", "sub_fields": []},
            {"name": "margin", "kind": "scalar", "sub_fields": []},
        ]
        assert run_state.products is products
        assert run_state.products == [{"id": "1", "title": "Shirt", "gtin": ["123"]}]
        assert result.processed_count == 1
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_missing_feed_source_raises(self, registry):
        with pytest.raises(LookupError, match="feed source"):
            await MappingStep(registry).execute(_ctx(None))


class TestSecondRun:
    @pytest.mark.asyncio
    async def test_manual_preserved_source_fields_refreshed_products_mapped(
        self, registry
    ):
        existing = {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [{"name": "stale", "kind": "scalar", "sub_fields": []}],
            "mappings": {"sku": {"target": "id", "origin": "manual"}},
        }
        feed_source = _feed_source(field_mapping=existing)
        run_state = RunState(
            products=[{"sku": "A1", "title": "Shirt"}],
            source_fields=[
                SourceField("sku", "scalar"),
                SourceField("title", "scalar"),
            ],
        )

        result = await MappingStep(registry).execute(_ctx(feed_source, run_state))

        assert feed_source.field_mapping["auto_mapped"] is True
        assert feed_source.field_mapping["mappings"] == {
            "sku": {"target": "id", "origin": "manual"}
        }
        assert feed_source.field_mapping["source_fields"] == [
            {"name": "sku", "kind": "scalar", "sub_fields": []},
            {"name": "title", "kind": "scalar", "sub_fields": []},
        ]
        assert run_state.products == [{"id": "A1"}]
        assert result.processed_count == 1


class TestCorruptDocument:
    @pytest.mark.asyncio
    async def test_raises_mapping_document_error(self, registry):
        feed_source = _feed_source(field_mapping={"mappings": "bad"})
        with pytest.raises(MappingDocumentError):
            await MappingStep(registry).execute(_ctx(feed_source))


class TestStatistics:
    @pytest.mark.asyncio
    async def test_counts_dropped_and_shape_mismatches(self, registry):
        existing = {
            "version": 1,
            "auto_mapped": True,
            "source_fields": [],
            "mappings": {"images": {"target": "title", "origin": "manual"}},
        }
        feed_source = _feed_source(field_mapping=existing)
        run_state = RunState(
            products=[
                {"images": ["a.jpg"], "margin": "10"},
                {"images": "b.jpg"},
            ],
            source_fields=[
                SourceField("images", "repeated_scalar"),
                SourceField("margin", "scalar"),
            ],
        )

        result = await MappingStep(registry).execute(_ctx(feed_source, run_state))

        assert result.statistics["mapping"] == {
            "applied": 2,
            "dropped_unmapped_fields": 1,
            "shape_mismatches": 1,
        }
        assert run_state.products == [{}, {"title": "b.jpg"}]

    @pytest.mark.asyncio
    async def test_no_products(self, registry):
        feed_source = _feed_source()
        run_state = RunState(source_fields=[SourceField("id", "scalar")])

        result = await MappingStep(registry).execute(_ctx(feed_source, run_state))

        assert result.processed_count == 0
        assert result.statistics["mapping"] == {
            "applied": 0,
            "dropped_unmapped_fields": 0,
            "shape_mismatches": 0,
        }


class TestContract:
    def test_name_is_mapping(self, registry):
        assert MappingStep(registry).name == "mapping"
