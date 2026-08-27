import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from app.qc.rules import (
    BaselineRequired, BrandRequired, GtinMpn, EnumValues,
    ConditionalRequired, DateFormat, LengthLimits, CardinalityRule,
    CurrencyConsistency, ImageRequirements, VariantConsistency, VolumeDrop,
)
from app.qc.engine import QcContext, Finding
from registry.model import RegistryDocument, RegistryAttribute, Cardinality, Constraints, AttributeKind, RequirementStatus, FeedDomain, ExportStatus
from app.clock import TestClock

pytestmark = pytest.mark.asyncio


def _make_ctx(**overrides):
    defaults = dict(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(datetime(2026, 6, 1, tzinfo=timezone.utc)),
        image_probe=AsyncMock(),
        previous_export_run=None,
    )
    defaults.update(overrides)
    return QcContext(**defaults)


def _attr(**kwargs):
    defaults = dict(
        name="field",
        kind=AttributeKind.SCALAR,
        type="string",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=ExportStatus.EXPORTABLE,
    )
    defaults.update(kwargs)
    return RegistryAttribute(**defaults)


# -- BaselineRequired --

async def test_baseline_required_finds_missing():
    rule = BaselineRequired()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) > 0
    assert findings[0].severity == "critical"


async def test_baseline_required_passes_complete():
    rule = BaselineRequired()
    product = {"id": "1", "title": "T", "description": "D", "link": "http://x", "image_link": "http://x.jpg", "availability": "in_stock", "price": "10 USD", "condition": "new"}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_baseline_required_accepts_structured_title():
    rule = BaselineRequired()
    product = {"id": "1", "structured_title": "T", "description": "D", "link": "http://x", "image_link": "http://x.jpg", "availability": "in_stock", "price": "10 USD", "condition": "new"}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


# -- BrandRequired --

async def test_brand_required_exempts_books():
    rule = BrandRequired()
    product = {"google_product_category": 784}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_brand_required_exempts_dvd():
    rule = BrandRequired()
    product = {"google_product_category": 839}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_brand_required_exempts_music():
    rule = BrandRequired()
    product = {"google_product_category": 855}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_brand_required_warns_when_missing():
    rule = BrandRequired()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "warning"


async def test_brand_required_non_exempt_category():
    rule = BrandRequired()
    product = {"google_product_category": 1234}
    findings = await rule.check(product, _make_ctx())
    assert len(findings) == 1


# -- GtinMpn --

async def test_gtin_valid_checksum():
    rule = GtinMpn()
    product = {"gtin": "0012345678905"}  # valid GS1
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_gtin_invalid_checksum():
    rule = GtinMpn()
    product = {"gtin": "0012345678900"}
    findings = await rule.check(product, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "critical"


async def test_gtin_missing_requires_mpn_brand():
    rule = GtinMpn()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "warning"


async def test_gtin_missing_with_mpn_brand_ok():
    rule = GtinMpn()
    product = {"mpn": "MPN123", "brand": "Acme"}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_gtin_missing_mpn_only_warns():
    rule = GtinMpn()
    product = {"mpn": "MPN123"}
    findings = await rule.check(product, _make_ctx())
    assert len(findings) == 1


# -- EnumValues --

async def test_enum_values_invalid():
    rule = EnumValues()
    registry = RegistryDocument(attributes={
        "availability": _attr(
            name="availability",
            enum_values=("in_stock", "out_of_stock"),
        ),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"availability": "maybe"}, ctx)
    assert len(findings) == 1


async def test_enum_values_valid():
    rule = EnumValues()
    registry = RegistryDocument(attributes={
        "availability": _attr(
            name="availability",
            enum_values=("in_stock", "out_of_stock"),
        ),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"availability": "in_stock"}, ctx)
    assert findings == []


# -- ConditionalRequired --

async def test_conditional_preorder_needs_date():
    rule = ConditionalRequired()
    findings = await rule.check({"availability": "preorder"}, _make_ctx())
    assert len(findings) == 1


async def test_conditional_preorder_with_date_ok():
    rule = ConditionalRequired()
    findings = await rule.check({"availability": "preorder", "availability_date": "2026-01-15T00:00:00+00:00"}, _make_ctx())
    assert findings == []


async def test_conditional_unit_pricing():
    rule = ConditionalRequired()
    findings = await rule.check({"unit_pricing_base_measure": "100g"}, _make_ctx())
    assert len(findings) == 1


async def test_conditional_unit_pricing_both_ok():
    rule = ConditionalRequired()
    findings = await rule.check({"unit_pricing_base_measure": "100g", "unit_pricing_measure": "1g"}, _make_ctx())
    assert findings == []


# -- DateFormat --

async def test_date_format_missing_timezone():
    rule = DateFormat()
    findings = await rule.check({"availability_date": "2026-01-15"}, _make_ctx())
    assert len(findings) == 1
    assert "timezone" in findings[0].message


async def test_date_format_valid():
    rule = DateFormat()
    findings = await rule.check({"availability_date": "2026-01-15T00:00:00+00:00"}, _make_ctx())
    assert findings == []


async def test_date_format_invalid():
    rule = DateFormat()
    findings = await rule.check({"availability_date": "not-a-date"}, _make_ctx())
    assert len(findings) == 1
    assert "invalid" in findings[0].message


async def test_date_format_multiple_fields():
    rule = DateFormat()
    product = {
        "availability_date": "2026-01-15",
        "expiration_date": "invalid",
        "sale_price_effective_date": "2026-01-15T00:00:00Z",
    }
    findings = await rule.check(product, _make_ctx())
    assert len(findings) == 2  # availability_date missing tz, expiration_date invalid


# -- LengthLimits --

async def test_length_limits_exceeds():
    rule = LengthLimits()
    registry = RegistryDocument(attributes={
        "title": _attr(name="title", constraints=Constraints(max_length=10)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"title": "a" * 11}, ctx)
    assert len(findings) == 1


async def test_length_limits_within():
    rule = LengthLimits()
    registry = RegistryDocument(attributes={
        "title": _attr(name="title", constraints=Constraints(max_length=10)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"title": "a" * 10}, ctx)
    assert findings == []


# -- CardinalityRule --

async def test_cardinality_max_exceeded():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "color": _attr(name="color", cardinality=Cardinality(max_items=3)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"color": ["a", "b", "c", "d"]}, ctx)
    assert len(findings) == 1


async def test_cardinality_min_violated():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "color": _attr(name="color", cardinality=Cardinality(min_items=2)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"color": ["a"]}, ctx)
    assert len(findings) == 1


async def test_cardinality_item_max_length():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "highlight": _attr(name="highlight", cardinality=Cardinality(max_items=5, item_max_length=10)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"highlight": ["short", "this is way too long"]}, ctx)
    assert len(findings) == 1
    assert findings[0].field == "highlight.2"


# -- CurrencyConsistency --

async def test_currency_mismatch():
    rule = CurrencyConsistency()
    findings = await rule.check({"price": "10 EUR"}, _make_ctx(currency="USD"))
    assert len(findings) == 1
    assert findings[0].severity == "critical"


async def test_currency_match():
    rule = CurrencyConsistency()
    findings = await rule.check({"price": "USD 10"}, _make_ctx(currency="USD"))
    assert findings == []


async def test_currency_no_ctx_currency():
    rule = CurrencyConsistency()
    findings = await rule.check({"price": "10 EUR"}, _make_ctx(currency=None))
    assert findings == []


# -- ImageRequirements --

async def test_image_requirements_too_small():
    probe = AsyncMock()
    probe.probe.return_value = (200, 200, None)
    rule = ImageRequirements()
    ctx = _make_ctx(image_probe=probe)
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, ctx)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


async def test_image_requirements_before_enforcement():
    probe = AsyncMock()
    probe.probe.return_value = (200, 200, None)
    rule = ImageRequirements()
    clock = TestClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    ctx = _make_ctx(image_probe=probe, clock=clock)
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, ctx)
    assert findings[0].severity == "warning"


async def test_image_requirements_after_enforcement():
    probe = AsyncMock()
    probe.probe.return_value = (200, 200, None)
    rule = ImageRequirements()
    clock = TestClock(datetime(2027, 2, 1, tzinfo=timezone.utc))
    ctx = _make_ctx(image_probe=probe, clock=clock)
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, ctx)
    assert findings[0].severity == "critical"


async def test_image_requirements_good_size():
    probe = AsyncMock()
    probe.probe.return_value = (1600, 1600, None)
    rule = ImageRequirements()
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, _make_ctx(image_probe=probe))
    assert findings == []


async def test_image_requirements_probe_error():
    probe = AsyncMock()
    probe.probe.return_value = (None, None, "timeout")
    rule = ImageRequirements()
    findings = await rule.check({"image_link": "http://example.com/img.jpg"}, _make_ctx(image_probe=probe))
    assert len(findings) == 1
    assert findings[0].severity == "info"


# -- VariantConsistency --

async def test_variant_consistency_inconsistent():
    rule = VariantConsistency()
    products = [
        {"item_group_id": "G1", "title": "A"},
        {"item_group_id": "G1", "title": "B"},
    ]
    findings = await rule.check(products, _make_ctx())
    assert len(findings) == 1


async def test_variant_consistent():
    rule = VariantConsistency()
    products = [
        {"item_group_id": "G1", "title": "Same", "price": "10 USD"},
        {"item_group_id": "G1", "title": "Same", "price": "10 USD"},
    ]
    findings = await rule.check(products, _make_ctx())
    assert findings == []


async def test_variant_single_no_issue():
    rule = VariantConsistency()
    products = [{"item_group_id": "G1", "title": "Solo"}]
    findings = await rule.check(products, _make_ctx())
    assert findings == []


# -- VolumeDrop --

async def test_volume_drop_fires():
    rule = VolumeDrop()
    prev = type("Prev", (), {"product_count": 100})()
    ctx = _make_ctx(previous_export_run=prev)
    products = [{"id": str(i)} for i in range(70)]
    findings = await rule.check(products, ctx)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


async def test_volume_drop_skipped_without_prior():
    rule = VolumeDrop()
    findings = await rule.check([{"id": "1"}], _make_ctx())
    assert findings == []


async def test_volume_drop_no_issue_small_drop():
    rule = VolumeDrop()
    prev = type("Prev", (), {"product_count": 100})()
    ctx = _make_ctx(previous_export_run=prev, volume_drop_threshold_pct=20)
    products = [{"id": str(i)} for i in range(90)]
    findings = await rule.check(products, ctx)
    assert findings == []
