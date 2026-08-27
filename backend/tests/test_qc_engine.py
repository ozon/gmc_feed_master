import pytest
from app.qc.engine import QcContext, Finding, PerProductRule, CrossProductRule, run_engine
from registry.model import RegistryDocument
from app.clock import TestClock

pytestmark = pytest.mark.asyncio


class StubImageProbe:
    async def probe(self, url):
        return (800, 600, None)


class StubPerProductRule:
    rule_id = "stub_per"

    async def check(self, product, ctx):
        if not product.get("title"):
            return [Finding(rule_id="stub_per", severity="warning", field="title", message="missing title")]
        return []


class StubCrossProductRule:
    rule_id = "stub_cross"

    async def check(self, products, ctx):
        if len(products) < 2:
            return [Finding(rule_id="stub_cross", severity="info", field=None, message="need more products")]
        return []


def _make_ctx(**overrides):
    defaults = dict(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)),
        image_probe=StubImageProbe(),
        previous_export_run=None,
    )
    defaults.update(overrides)
    return QcContext(**defaults)


async def test_per_product_rule_finds_issues():
    products = [{"id": "1"}, {"id": "2", "title": "Good"}]
    product_ids = ["1", "2"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [StubPerProductRule()], [])
    assert len(findings) == 1
    assert findings[0].rule_id == "stub_per"
    assert findings[0].field == "title"
    assert findings[0].product_id == "1"


async def test_cross_product_rule_finds_issues():
    products = [{"id": "1"}]
    product_ids = ["1"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [], [StubCrossProductRule()])
    assert len(findings) == 1
    assert findings[0].rule_id == "stub_cross"


async def test_no_findings_on_clean_data():
    products = [{"id": "1", "title": "Good"}, {"id": "2", "title": "Also good"}]
    product_ids = ["1", "2"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [StubPerProductRule()], [StubCrossProductRule()])
    assert findings == []


async def test_rule_exception_does_not_crash_engine():
    class BrokenRule:
        rule_id = "broken"
        async def check(self, product, ctx):
            raise RuntimeError("boom")

    products = [{"id": "1"}]
    product_ids = ["1"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [BrokenRule()], [])
    assert findings == []
