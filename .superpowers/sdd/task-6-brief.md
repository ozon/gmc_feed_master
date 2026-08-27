### Task 6: QC Rules — All 12 Implementations

**Goal:** Implement all 12 QC rules.

**Files:**
- Create: `backend/app/qc/rules.py`
- Create: `backend/tests/test_qc_rules.py`

#### Steps

- [ ] **Step 1: Create rules module with all 12 rules**

```python
# backend/app/qc/rules.py
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..clock import Clock
from .constants import EXEMPT_TAXONOMY_IDS, IMAGE_FORMATS, IMAGE_SIZE_ENFORCEMENT_DATE
from .engine import QcContext, Finding


class BaselineRequired:
    rule_id = "baseline_required"
    _REQUIRED = ("id", "link", "image_link", "availability", "price", "condition")

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for field_name in self._REQUIRED:
            if not product.get(field_name):
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=field_name, message=f"missing required field {field_name}",
                ))
        # title or structured_title
        if not product.get("title") and not product.get("structured_title"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="critical",
                field="title", message="missing required field title/structured_title",
            ))
        # description or structured_description
        if not product.get("description") and not product.get("structured_description"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="critical",
                field="description", message="missing required field description/structured_description",
            ))
        return findings


class BrandRequired:
    rule_id = "brand_required"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        if not product.get("brand"):
            cat_id = product.get("google_product_category")
            if cat_id is not None:
                try:
                    cat_int = int(cat_id)
                except (ValueError, TypeError):
                    cat_int = None
                if cat_int in EXEMPT_TAXONOMY_IDS:
                    return []
            return [Finding(
                rule_id=self.rule_id, severity="warning",
                field="brand", message="missing brand",
            )]
        return []


class GtinMpn:
    rule_id = "gtin_mpn"

    @staticmethod
    def _gs1_checksum(gtin: str) -> bool:
        if not gtin.isdigit() or len(gtin) < 8:
            return False
        digits = [int(d) for d in reversed(gtin)]
        total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits))
        return total % 10 == 0

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        gtin = product.get("gtin")
        if not gtin:
            if not product.get("mpn") or not product.get("brand"):
                return [Finding(
                    rule_id=self.rule_id, severity="warning",
                    field="gtin", message="missing gtin requires mpn and brand",
                )]
            return []
        if not self._gs1_checksum(str(gtin)):
            return [Finding(
                rule_id=self.rule_id, severity="critical",
                field="gtin", message="invalid GTIN checksum",
            )]
        return []


class EnumValues:
    rule_id = "enum_values"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for attr_name, attr_info in ctx.registry.attributes.items():
            if not attr_info.enum_values:
                continue
            value = product.get(attr_name)
            if value is not None and value not in attr_info.enum_values:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=attr_name, message=f"invalid value for {attr_name}: {value}",
                ))
        return findings


class ConditionalRequired:
    rule_id = "conditional_required"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        if product.get("availability") == "preorder" and not product.get("availability_date"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="warning",
                field="availability_date", message="availability_date required for preorder",
            ))
        if product.get("unit_pricing_base_measure") and not product.get("unit_pricing_measure"):
            findings.append(Finding(
                rule_id=self.rule_id, severity="warning",
                field="unit_pricing_measure", message="unit_pricing_measure required when base_measure is set",
            ))
        return findings


class DateFormat:
    rule_id = "date_format"
    _FIELDS = ("availability_date", "expiration_date", "sale_price_effective_date")

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for field_name in self._FIELDS:
            value = product.get(field_name)
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value))
                if parsed.tzinfo is None:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="critical",
                        field=field_name, message=f"{field_name} must include timezone",
                    ))
            except (ValueError, TypeError):
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=field_name, message=f"invalid date format for {field_name}",
                ))
        return findings


class LengthLimits:
    rule_id = "length_limits"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for attr_name, attr_info in ctx.registry.attributes.items():
            if not attr_info.constraints or not attr_info.constraints.max_length:
                continue
            value = product.get(attr_name)
            if value is not None and len(str(value)) > attr_info.constraints.max_length:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="warning",
                    field=attr_name, message=f"{attr_name} exceeds max length {attr_info.constraints.max_length}",
                ))
        return findings


class CardinalityRule:
    rule_id = "cardinality"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        for attr_name, attr_info in ctx.registry.attributes.items():
            if not attr_info.cardinality:
                continue
            value = product.get(attr_name)
            if value is None:
                continue
            if isinstance(value, list):
                max_items = attr_info.cardinality.max_items
                min_items = attr_info.cardinality.min_items
                if max_items is not None and len(value) > max_items:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="warning",
                        field=attr_name, message=f"{attr_name} has {len(value)} items, max is {max_items}",
                    ))
                if min_items is not None and len(value) < min_items:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="warning",
                        field=attr_name, message=f"{attr_name} has {len(value)} items, min is {min_items}",
                    ))
                if attr_info.cardinality.item_max_length:
                    for i, item in enumerate(value):
                        if len(str(item)) > attr_info.cardinality.item_max_length:
                            findings.append(Finding(
                                rule_id=self.rule_id, severity="warning",
                                field=f"{attr_name}.{i+1}",
                                message=f"{attr_name}[{i+1}] exceeds max length {attr_info.cardinality.item_max_length}",
                            ))
        return findings


class CurrencyConsistency:
    rule_id = "currency_consistency"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        if not ctx.currency:
            return []
        findings = []
        for field_name in ("price", "sale_price"):
            value = product.get(field_name)
            if not value:
                continue
            parts = str(value).split(" ")
            if len(parts) >= 2 and parts[0] != ctx.currency:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field=field_name, message=f"currency mismatch: {parts[0]} vs {ctx.currency}",
                ))
        return findings


class ImageRequirements:
    rule_id = "image_requirements"

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        findings = []
        urls = []
        if product.get("image_link"):
            urls.append(("image_link", str(product["image_link"])))
        for i, url in enumerate(product.get("additional_image_link") or [], start=1):
            urls.append((f"additional_image_link.{i}", str(url)))

        for field_name, url in urls:
            ext = url.rsplit(".", 1)[-1].lower() if "." in url else ""
            if ext not in IMAGE_FORMATS:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="warning",
                    field=field_name, message=f"unrecognized image format: {ext or '(none)'}",
                ))
            width, height, error = await ctx.image_probe.probe(url)
            if error:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="info",
                    field=field_name, message=f"image fetch error: {error}",
                ))
                continue
            if width is None or height is None:
                continue
            if width < 500 or height < 500:
                severity = "critical" if ctx.clock.now().date() >= IMAGE_SIZE_ENFORCEMENT_DATE else "warning"
                findings.append(Finding(
                    rule_id=self.rule_id, severity=severity,
                    field=field_name, message=f"image too small: {width}x{height}",
                ))
            elif width < 1500 or height < 1500:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="info",
                    field=field_name, message=f"image below recommended size: {width}x{height}",
                ))
        return findings


class VariantConsistency:
    rule_id = "variant_consistency"
    _BASE_ATTRS = ("id", "title", "description", "link", "image_link", "availability", "condition", "price")

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]:
        groups: dict[str, list[dict]] = {}
        for p in products:
            gid = p.get("item_group_id")
            if gid:
                groups.setdefault(str(gid), []).append(p)

        findings = []
        for gid, group in groups.items():
            if len(group) < 2:
                continue
            base = group[0]
            for attr in self._BASE_ATTRS:
                values = {str(p.get(attr)) for p in group if p.get(attr) is not None}
                if len(values) > 1:
                    findings.append(Finding(
                        rule_id=self.rule_id, severity="warning",
                        field=attr, message=f"inconsistent {attr} across variant group {gid}",
                    ))
        return findings


class VolumeDrop:
    rule_id = "volume_drop"

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]:
        if ctx.previous_export_run is None:
            return []
        prev_count = ctx.previous_export_run.product_count
        if prev_count == 0:
            return []
        current_count = len(products)
        drop_pct = ((prev_count - current_count) / prev_count) * 100
        if drop_pct >= ctx.volume_drop_threshold_pct:
            return [Finding(
                rule_id=self.rule_id, severity="warning",
                field=None,
                message=f"volume drop {drop_pct:.1f}% exceeds threshold {ctx.volume_drop_threshold_pct}%",
                details={"previous_count": prev_count, "current_count": current_count, "drop_pct": round(drop_pct, 1)},
            )]
        return []
```

- [ ] **Step 2: Write rule unit tests**

```python
# backend/tests/test_qc_rules.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from app.qc.rules import (
    BaselineRequired, BrandRequired, GtinMpn, EnumValues,
    ConditionalRequired, DateFormat, LengthLimits, CardinalityRule,
    CurrencyConsistency, ImageRequirements, VariantConsistency, VolumeDrop,
)
from app.qc.engine import QcContext, Finding
from registry.model import RegistryDocument, AttributeInfo, Cardinality, Constraints
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


# -- BrandRequired --

async def test_brand_required_exempts_books():
    rule = BrandRequired()
    product = {"google_product_category": 784}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_brand_required_warns_when_missing():
    rule = BrandRequired()
    findings = await rule.check({}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "warning"


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


# -- EnumValues --

async def test_enum_values_invalid():
    rule = EnumValues()
    registry = RegistryDocument(attributes={
        "availability": AttributeInfo(type="enumeration", enum_values=["in_stock", "out_of_stock"]),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"availability": "maybe"}, ctx)
    assert len(findings) == 1


# -- ConditionalRequired --

async def test_conditional_preorder_needs_date():
    rule = ConditionalRequired()
    findings = await rule.check({"availability": "preorder"}, _make_ctx())
    assert len(findings) == 1


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


# -- LengthLimits --

async def test_length_limits_exceeds():
    rule = LengthLimits()
    registry = RegistryDocument(attributes={
        "title": AttributeInfo(type="string", constraints=Constraints(max_length=10)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"title": "a" * 11}, ctx)
    assert len(findings) == 1


# -- CardinalityRule --

async def test_cardinality_max_exceeded():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "color": AttributeInfo(type="enumeration", cardinality=Cardinality(max_items=3)),
    })
    ctx = _make_ctx(registry=registry)
    findings = await rule.check({"color": ["a", "b", "c", "d"]}, ctx)
    assert len(findings) == 1


async def test_cardinality_item_max_length():
    rule = CardinalityRule()
    registry = RegistryDocument(attributes={
        "highlight": AttributeInfo(type="enumeration", cardinality=Cardinality(max_items=5, item_max_length=10)),
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


# -- VariantConsistency --

async def test_variant_consistency_inconsistent():
    rule = VariantConsistency()
    products = [
        {"item_group_id": "G1", "title": "A"},
        {"item_group_id": "G1", "title": "B"},
    ]
    findings = await rule.check(products, _make_ctx())
    assert len(findings) == 1


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
```

- [ ] **Step 3: Run rule tests**

Run: `cd backend && python -m pytest tests/test_qc_rules.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/qc/rules.py backend/tests/test_qc_rules.py
git commit -m "feat(qc): implement all 12 QC rules"
```

---

