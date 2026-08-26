from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..ingest import HttpFetcher, read_feed
from ..ingest.report import SourceField
from ..mapping import MappingDocument, apply_mapping, auto_match
from ..models.feed_source import FeedSource
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


class _NoOpStep:
    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, ctx: StepContext) -> StepResult:
        ctx.logger.info("%s: not implemented (M2 skeleton)", self.name)
        return StepResult()


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


class QualityCheckStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("quality_check")


class ExportStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("export")


def default_steps(
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any] | None = None,
) -> tuple[PipelineStep, ...]:
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(plugin_registry),
        QualityCheckStep(),
        ExportStep(),
    )
