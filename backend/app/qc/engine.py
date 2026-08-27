from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field as dc_field
from typing import Any, Protocol, runtime_checkable

from registry.model import RegistryDocument

from ..clock import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QcContext:
    feed_source_id: int
    currency: str | None
    volume_drop_threshold_pct: int
    registry: RegistryDocument
    clock: Clock
    image_probe: ImageProbe
    previous_export_run: ExportRun | None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str  # "critical" | "warning" | "info"
    field: str | None
    message: str
    product_id: str = ""
    details: dict[str, Any] = dc_field(default_factory=dict)


@runtime_checkable
class PerProductRule(Protocol):
    rule_id: str

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class CrossProductRule(Protocol):
    rule_id: str

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class ImageProbe(Protocol):
    async def probe(self, url: str) -> tuple[int | None, int | None, str | None]:
        """Return (width, height, error_message). error_message is None on success."""
        ...


@runtime_checkable
class ExportRun(Protocol):
    feed_source_id: int
    ingestion_run_id: int
    product_count: int
    critical_finding_count: int
    warning_finding_count: int
    info_finding_count: int


async def run_engine(
    products: list[dict],
    product_ids: list[str],
    ctx: QcContext,
    per_product_rules: list[PerProductRule],
    cross_product_rules: list[CrossProductRule],
) -> list[Finding]:
    findings: list[Finding] = []

    # Per-product rules — attach product_id to each finding
    for product, product_id in zip(products, product_ids):
        for rule in per_product_rules:
            try:
                rule_findings = await rule.check(product, ctx)
                for f in rule_findings:
                    findings.append(Finding(
                        rule_id=f.rule_id, severity=f.severity,
                        field=f.field, message=f.message,
                        product_id=product_id, details=f.details,
                    ))
            except Exception:
                logger.exception("rule %s failed on product %s", rule.rule_id, product_id)

    # Cross-product rules — no product_id (findings apply to the feed as a whole)
    for rule in cross_product_rules:
        try:
            rule_findings = await rule.check(products, ctx)
            findings.extend(rule_findings)
        except Exception:
            logger.exception("cross-product rule %s failed", rule.rule_id)

    return findings
