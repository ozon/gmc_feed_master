from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..ingest import HttpFetcher, read_feed
from ..ingest.report import SourceField
from ..models.feed_source import FeedSource


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
        PluginStep(),
        QualityCheckStep(),
        ExportStep(),
    )
