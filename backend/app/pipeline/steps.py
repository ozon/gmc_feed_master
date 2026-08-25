from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RunState:
    products: list[dict[str, Any]] = field(default_factory=list)


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


class IngestStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("ingest")


class PluginStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("run_plugins")


class QualityCheckStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("quality_check")


class ExportStep(_NoOpStep):
    def __init__(self) -> None:
        super().__init__("export")


DEFAULT_STEPS: list[PipelineStep] = [
    IngestStep(),
    PluginStep(),
    QualityCheckStep(),
    ExportStep(),
]
