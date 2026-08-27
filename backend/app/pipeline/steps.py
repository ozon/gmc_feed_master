from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_EXPORT_DIR
from registry.model import RegistryDocument

from ..clock import Clock, SystemClock
from ..export.store import ExportFileStore
from ..ingest import HttpFetcher, read_feed
from ..ingest.report import SourceField
from ..mapping import MappingDocument, apply_mapping, auto_match
from ..models.feed_source import FeedSource
from ..qc.engine import ImageProbe
from ..staging.config_resolver import resolve_config_bundle
from ..staging.delta import classify
from ..staging.hashing import content_hash
from ..staging.persistence import (
    PluginOutcome,
    apply_plugin_outcomes,
    apply_staging_delta,
    load_stored_rows,
)
from ..plugins.runtime import RunContext


@dataclass
class RunState:
    products: list[dict[str, Any]] = field(default_factory=list)
    source_fields: list[SourceField] = field(default_factory=list)
    client_id: int | None = None
    config_bundle: dict[str, Any] = field(default_factory=dict)
    product_pks: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StepContext:
    feed_source_id: int
    session_factory: Callable[[], AsyncSession]
    logger: logging.Logger
    run_state: RunState
    ingestion_run_id: int = 0


@dataclass(frozen=True)
class StepResult:
    processed_count: int = 0
    failed_count: int = 0
    statistics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PipelineStep(Protocol):
    name: str

    async def execute(self, ctx: StepContext) -> StepResult: ...


class IngestStep:
    name = "ingest"

    def __init__(self, fetcher: HttpFetcher, registry: RegistryDocument) -> None:
        self._fetcher = fetcher
        self._registry = registry

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)
        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")
        if not feed_source.source_url:
            raise ValueError(
                f"feed source {ctx.feed_source_id} has no source_url configured"
            )

        basic_auth: tuple[str, str] | None = None
        auth_config = feed_source.configuration.get("basic_auth")
        if auth_config:
            basic_auth = (auth_config["username"], auth_config["password"])

        data = await self._fetcher.fetch(feed_source.source_url, basic_auth=basic_auth)
        report = read_feed(data, feed_source.source_format, self._registry)

        ctx.run_state.products.extend(report.products)
        ctx.run_state.source_fields = list(report.source_fields)
        if report.row_errors:
            ctx.logger.warning(
                "ingest: %d row errors for feed source %s",
                len(report.row_errors),
                ctx.feed_source_id,
            )
        return StepResult(
            processed_count=len(report.products),
            failed_count=len(report.row_errors),
            statistics={
                "row_errors": [
                    {"line": error.line, "message": error.message}
                    for error in report.row_errors[:100]
                ]
            },
        )


class MappingStep:
    name = "mapping"

    def __init__(self, registry: RegistryDocument) -> None:
        self._registry = registry

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)
                if feed_source is None:
                    raise LookupError(f"feed source {ctx.feed_source_id} not found")
                doc = MappingDocument.from_json(feed_source.field_mapping)
                if not doc.auto_mapped:
                    doc.mappings = auto_match(
                        ctx.run_state.source_fields,
                        self._registry,
                        existing=doc.mappings,
                    )
                    doc.auto_mapped = True
                doc.source_fields = list(ctx.run_state.source_fields)
                feed_source.field_mapping = doc.to_json()

        dropped_unmapped = 0
        shape_mismatches = 0
        for index, product in enumerate(ctx.run_state.products):
            mapped, stats = apply_mapping(product, doc.mappings, self._registry)
            ctx.run_state.products[index] = mapped
            dropped_unmapped += stats.dropped_unmapped
            shape_mismatches += stats.shape_mismatches

        return StepResult(
            processed_count=len(ctx.run_state.products),
            statistics={
                "mapping": {
                    "applied": len(ctx.run_state.products),
                    "dropped_unmapped_fields": dropped_unmapped,
                    "shape_mismatches": shape_mismatches,
                }
            },
        )


class StagingStep:
    name = "staging"

    def __init__(self, chunk_size: int = 1000) -> None:
        self._chunk_size = chunk_size

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)
        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        async with ctx.session_factory() as session:
            bundle = await resolve_config_bundle(session, feed_source)
        ctx.run_state.client_id = feed_source.client_id
        ctx.run_state.config_bundle = bundle
        config_hash_value = content_hash(bundle)

        stored = await load_stored_rows(ctx.session_factory, ctx.feed_source_id)
        delta = classify(ctx.run_state.products, stored, config_hash_value)
        if delta.counts.failed:
            ctx.logger.warning(
                "staging: %d unusable products (missing/duplicate id)",
                delta.counts.failed,
            )

        pk_map = await apply_staging_delta(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            delta,
            config_hash_value,
            chunk_size=self._chunk_size,
        )
        ctx.run_state.product_pks = pk_map

        ctx.run_state.products = list(delta.enqueue)
        return StepResult(
            processed_count=len(delta.enqueue),
            failed_count=delta.counts.failed,
            statistics={"staging": asdict(delta.counts)},
        )


class PluginStep:
    name = "run_plugins"

    def __init__(self, registry: dict[str, Any] | None = None) -> None:
        self._registry = registry if registry is not None else {}

    async def execute(self, ctx: StepContext) -> StepResult:
        from copy import deepcopy

        bundle = ctx.run_state.config_bundle or {"instances": []}
        pks = ctx.run_state.product_pks
        survivors: list[dict[str, Any]] = []
        outcomes: list[PluginOutcome] = []
        processed = dropped = errored = 0

        for product in ctx.run_state.products:
            pid = product.get("id")
            current = product
            original = deepcopy(product)
            drop = error = False
            for instance in bundle.get("instances", []):
                plugin_obj = self._registry.get(instance["plugin"])
                if plugin_obj is None:
                    continue
                rctx = RunContext(
                    client_id=ctx.run_state.client_id or 0,
                    feed_source_id=ctx.feed_source_id,
                    run_id=ctx.ingestion_run_id,
                    logger=ctx.logger,
                    original_product=original,
                )
                try:
                    result = plugin_obj.process(
                        current,
                        instance["resolved_config"],
                        instance["resolved_data"],
                        rctx,
                    )
                except Exception as exc:
                    ctx.logger.warning(
                        "plugin %s errored on product %s: %s",
                        instance["plugin"], pid, exc,
                    )
                    errored += 1
                    error = True
                    break
                if result is None:
                    drop = True
                    break
                current = result
            if error:
                continue
            pk = pks.get(pid) if isinstance(pid, str) else None
            if drop:
                dropped += 1
                if pk is not None:
                    outcomes.append(PluginOutcome(pid, pk, "dropped", None))
                continue
            processed += 1
            survivors.append(current)
            if pk is not None:
                outcomes.append(PluginOutcome(str(pid), pk, "processed", current))

        await apply_plugin_outcomes(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            outcomes,
        )
        ctx.run_state.products = survivors
        return StepResult(
            processed_count=len(survivors),
            failed_count=errored,
            statistics={
                "plugins": {
                    "processed": processed,
                    "dropped": dropped,
                    "errored": errored,
                }
            },
        )


class QualityCheckStep:
    name = "quality_check"

    def __init__(
        self,
        registry: RegistryDocument,
        clock: Clock,
        image_probe: ImageProbe | None = None,
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._image_probe = image_probe

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)

        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        from ..staging.persistence import load_export_bound

        bound = await load_export_bound(ctx.session_factory, ctx.feed_source_id)
        product_ids = [product_id for product_id, _ in bound]
        products = [product for _, product in bound]

        async with ctx.session_factory() as session:
            from sqlalchemy import select, desc
            from ..models.export import ExportRun
            result = await session.execute(
                select(ExportRun).where(
                    ExportRun.feed_source_id == ctx.feed_source_id
                ).order_by(desc(ExportRun.id)).limit(1)
            )
            previous_export_run = result.scalar_one_or_none()

        from ..qc.engine import QcContext, run_engine
        from ..qc.rules import (
            BaselineRequired, BrandRequired, GtinMpn, EnumValues,
            ConditionalRequired, DateFormat, LengthLimits, CardinalityRule,
            CurrencyConsistency, ImageRequirements, VariantConsistency, VolumeDrop,
        )
        from ..qc.persistence import persist_findings

        qc_ctx = QcContext(
            feed_source_id=ctx.feed_source_id,
            currency=feed_source.currency,
            volume_drop_threshold_pct=feed_source.volume_drop_threshold_pct,
            registry=self._registry,
            clock=self._clock,
            image_probe=self._image_probe,
            previous_export_run=previous_export_run,
        )

        per_product_rules = [
            BaselineRequired(), BrandRequired(), GtinMpn(), EnumValues(),
            ConditionalRequired(), DateFormat(), LengthLimits(), CardinalityRule(),
            CurrencyConsistency(), ImageRequirements(),
        ]
        cross_product_rules = [VariantConsistency(), VolumeDrop()]

        findings = await run_engine(products, product_ids, qc_ctx, per_product_rules, cross_product_rules)

        await persist_findings(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            findings,
            len(products),
        )

        counts = {"critical": 0, "warning": 0, "info": 0}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1

        return StepResult(
            processed_count=0,
            statistics={"qc": {"products": len(products), **counts}},
        )


class ExportStep:
    name = "export"

    def __init__(
        self,
        registry: RegistryDocument,
        store: ExportFileStore,
        clock: Clock,
        public_base_url: str,
    ) -> None:
        self._registry = registry
        self._store = store
        self._clock = clock
        self._public_base_url = public_base_url

    async def execute(self, ctx: StepContext) -> StepResult:
        from ..export.service import ExportService
        from ..staging.persistence import load_export_bound

        bound = await load_export_bound(ctx.session_factory, ctx.feed_source_id)
        products = [product for _, product in bound]
        service = ExportService(
            ctx.session_factory, self._store, self._clock, self._public_base_url
        )
        outcome = await service.export_for_run(
            ctx.feed_source_id, ctx.ingestion_run_id, products, self._registry
        )
        return StepResult(
            statistics={
                "export": {
                    "products": outcome.product_count,
                    "version": outcome.version_number,
                    "deduplicated": outcome.deduplicated,
                }
            }
        )


def default_steps(
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any] | None = None,
    clock: Clock | None = None,
    image_probe: ImageProbe | None = None,
    export_dir: Path | str | None = None,
    public_base_url: str | None = None,
) -> tuple[PipelineStep, ...]:
    if clock is None:
        clock = SystemClock()
    store = ExportFileStore(
        Path(export_dir) if export_dir is not None else DEFAULT_EXPORT_DIR
    )
    base_url = public_base_url if public_base_url is not None else "http://localhost:8000"
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(plugin_registry),
        QualityCheckStep(registry, clock, image_probe),
        ExportStep(registry, store, clock, base_url),
    )
