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
from ..staging.persistence import apply_staging_delta, load_stored_rows


@dataclass
class RunState:
    products: list[dict[str, Any]] = field(default_factory=list)
    source_fields: list[SourceField] = field(default_factory=list)


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
        config_hash_value = content_hash(bundle)

        stored = await load_stored_rows(ctx.session_factory, ctx.feed_source_id)
        delta = classify(ctx.run_state.products, stored, config_hash_value)
        if delta.counts.failed:
            ctx.logger.warning(
                "staging: %d unusable products (missing/duplicate id)",
                delta.counts.failed,
            )

        await apply_staging_delta(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            delta,
            config_hash_value,
            chunk_size=self._chunk_size,
        )

        ctx.run_state.products = list(delta.enqueue)
        return StepResult(
            processed_count=len(delta.enqueue),
            failed_count=delta.counts.failed,
            statistics={"staging": asdict(delta.counts)},
        )


class PluginStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("run_plugins")


class QualityCheckStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("quality_check")


class ExportStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("export")


def default_steps(
    fetcher: HttpFetcher, registry: RegistryDocument
) -> tuple[PipelineStep, ...]:
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(),
        QualityCheckStep(),
        ExportStep(),
    )
