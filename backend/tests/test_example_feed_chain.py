from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.clock import TestClock
from app.export.renderer import ChannelMetadata, render_feed
from app.ingest import read_feed
from app.mapping.apply import apply_mapping
from app.mapping.matcher import auto_match
from app.qc.engine import QcContext
from app.qc.rules import BaselineRequired
from registry.loader import load_registry
from registry.model import RegistryDocument

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feeds"


def _make_ctx() -> QcContext:
    return QcContext(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(datetime(2026, 6, 1, tzinfo=timezone.utc)),
        image_probe=AsyncMock(),
        previous_export_run=None,
    )


async def _baseline_findings(products: list[dict]) -> list:
    rule = BaselineRequired()
    findings = []
    for product in products:
        findings.extend(await rule.check(product, _make_ctx()))
    return [f for f in findings if f.rule_id == "baseline_required"]


class TestMultifeedTsvChain:
    async def test_full_chain(self) -> None:
        data = (_FIXTURES / "multifeed.tsv").read_bytes()
        registry = load_registry()
        report = read_feed(data, "tsv", registry)

        assert len(report.products) == 14
        assert report.row_errors == []

        mappings = auto_match(report.source_fields, registry)
        for source, target in [
            ("id", "id"),
            ("title", "title"),
            ("description", "description"),
            ("link", "link"),
            ("image_link", "image_link"),
            ("price", "price"),
            ("availability", "availability"),
            ("condition", "condition"),
            ("brand", "brand"),
            ("gtin", "gtin"),
            ("shipping", "shipping"),
        ]:
            assert mappings[source].target == target, source

        mapped_products = []
        for product in report.products:
            mapped, _stats = apply_mapping(product, mappings, registry)
            mapped_products.append(mapped)

        first = mapped_products[0]
        assert isinstance(first["shipping"], list)
        assert first["shipping"][0]["country"] == "US"
        assert first["shipping"][0]["price"] == "14.99 USD"
        assert first["shipping"][0]["location_group_name"] == ""

        for product in mapped_products:
            assert isinstance(product["description"], str)
            assert "tax" not in product
            assert "custom_label_1" not in product

        assert any("," in product["description"] for product in mapped_products)

        assert await _baseline_findings(mapped_products) == []

        xml = render_feed(
            mapped_products,
            registry,
            ChannelMetadata(title="t", link="https://example.com", description="d"),
        )
        text = xml.decode("utf-8")
        assert text.count("<item>") == 14
        assert "<g:id>shopify_US_" in text
        assert "<g:description>" in text


class TestExampleXmlChain:
    async def test_full_chain(self) -> None:
        data = (_FIXTURES / "example_feed.xml").read_bytes()
        registry = load_registry()
        report = read_feed(data, "xml", registry)

        assert len(report.products) == 308
        assert report.row_errors == []

        mappings = auto_match(report.source_fields, registry)
        assert mappings["id"].target == "id"
        assert mappings["title"].target == "title"
        assert mappings["description"].target == "description"

        mapped_products = []
        for product in report.products:
            mapped, _stats = apply_mapping(product, mappings, registry)
            mapped_products.append(mapped)

        findings = await _baseline_findings(mapped_products)
        assert len(findings) == 27
        assert all(f.severity == "critical" for f in findings)

        xml = render_feed(
            mapped_products,
            registry,
            ChannelMetadata(title="t", link="https://example.com", description="d"),
        )
        text = xml.decode("utf-8")
        assert text.count("<item>") == 308
        assert "<g:custom_label_0>" in text
