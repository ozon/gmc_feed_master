from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..clock import Clock
from ..ingest.fetch import HttpFetcher
from ..mapping.apply import apply_mapping
from ..mapping.document import MappingDocument
from ..mapping.matcher import auto_match
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..qc.engine import Finding, QcContext, run_engine
from ..staging.config_resolver import resolve_config_bundle
from .steps import IngestStep, PluginStep, RunState, StepContext

DRY_RUN_SAMPLE_CAP = 50


@dataclass
class DryRunResult:
    total: int = 0
    processed: int = 0
    parse_errors: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)


async def run_dry_run(
    *,
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any],
    clock: Clock,
    image_probe: Any,
    limit: int | None = None,
) -> DryRunResult:
    logger = logging.getLogger("dry_run")
    run_state = RunState()
    ctx = StepContext(feed_source_id, session_factory, logger, run_state, 0)

    async with session_factory() as session:
        feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise LookupError(f"feed source {feed_source_id} not found")

    ingest = await IngestStep(fetcher, registry).execute(ctx)
    if limit is not None:
        run_state.products = run_state.products[:limit]
    total = len(run_state.products)

    doc = MappingDocument.from_json(feed_source.field_mapping)
    if not doc.auto_mapped:
        doc.mappings = auto_match(run_state.source_fields, registry, existing=doc.mappings)
    for index, product in enumerate(run_state.products):
        mapped, _ = apply_mapping(product, doc.mappings, registry)
        run_state.products[index] = mapped

    async with session_factory() as session:
        run_state.config_bundle = await resolve_config_bundle(session, feed_source)
    run_state.client_id = feed_source.client_id

    await PluginStep(plugin_registry).execute(ctx)
    processed = list(run_state.products)

    async with session_factory() as session:
        previous_export_run = (await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
            .order_by(desc(ExportRun.id)).limit(1)
        )).scalar_one_or_none()

    from ..qc.rules import (
        BaselineRequired, BrandRequired, CardinalityRule, ConditionalRequired,
        CurrencyConsistency, DateFormat, EnumValues, GtinMpn, ImageRequirements,
        LengthLimits, VariantConsistency, VolumeDrop,
    )

    qc_ctx = QcContext(
        feed_source_id=feed_source_id,
        currency=feed_source.currency,
        volume_drop_threshold_pct=feed_source.volume_drop_threshold_pct,
        registry=registry,
        clock=clock,
        image_probe=image_probe,
        previous_export_run=previous_export_run,
    )
    findings = await run_engine(
        processed,
        [str(p.get("id", "")) for p in processed],
        qc_ctx,
        [BaselineRequired(), BrandRequired(), GtinMpn(), EnumValues(),
         ConditionalRequired(), DateFormat(), LengthLimits(), CardinalityRule(),
         CurrencyConsistency(), ImageRequirements()],
        [VariantConsistency(), VolumeDrop()],
    )

    return DryRunResult(
        total=total,
        processed=len(processed),
        parse_errors=ingest.failed_count,
        dropped=list(run_state.dropped),
        findings=findings,
        sample=processed[:DRY_RUN_SAMPLE_CAP],
    )
