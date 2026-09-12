from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Protocol, runtime_checkable

from registry.model import RegistryDocument

from ..clock import Clock
from ..models.export import ExportRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QcContext:
    feed_source_id: int
    currency: str | None
    volume_drop_threshold_pct: int
    registry: RegistryDocument
    clock: Clock
    image_probe: ImageProbe | None
    previous_export_run: ExportRun | None
    ai_service: Any = None
    client_id: int | None = None
    ai_budget: int = 0
    previous_ai_product_ids: frozenset[str] = frozenset()


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

    async def check(self, products: list[dict], product_ids: list[str], ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class ImageProbe(Protocol):
    async def probe(self, url: str) -> tuple[int | None, int | None, str | None]:
        """Return (width, height, error_message). error_message is None on success."""
        ...


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
    for cross_rule in cross_product_rules:
        try:
            rule_findings = await cross_rule.check(products, product_ids, ctx)
            findings.extend(rule_findings)
        except Exception:
            logger.exception("cross-product rule %s failed", cross_rule.rule_id)

    return findings
