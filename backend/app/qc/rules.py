from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .constants import (
    BASELINE_REQUIRED,
    EXEMPT_TAXONOMY_IDS,
    IMAGE_FORMATS,
    IMAGE_SIZE_ENFORCEMENT_DATE,
)
from .engine import QcContext, Finding


class BaselineRequired:
    rule_id = "baseline_required"
    _REQUIRED = BASELINE_REQUIRED

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
