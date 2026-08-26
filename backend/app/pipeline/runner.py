from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from .locks import LockRegistry
from .steps import PipelineStep, RunState, StepContext, StepResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(
        self,
        lock_registry: LockRegistry,
        session_factory: async_sessionmaker[AsyncSession],
        steps: Sequence[PipelineStep],
    ) -> None:
        self._lock_registry = lock_registry
        self._session_factory = session_factory
        self._steps = steps

    async def execute(self, feed_source_id: int, run_id: int | None = None) -> int | None:
        if self._lock_registry.is_locked(feed_source_id):
            if run_id is None and not await self._feed_source_exists(feed_source_id):
                logger.warning(
                    "feed source %s not found; no run recorded", feed_source_id
                )
                return None
            return await self._finish(feed_source_id, run_id, "skipped")

        lock = self._lock_registry.get(feed_source_id)
        await lock.acquire()
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    feed_source = await session.get(FeedSource, feed_source_id)
            if feed_source is None:
                if run_id is not None:
                    return await self._finish(feed_source_id, run_id, "skipped")
                logger.warning(
                    "feed source %s not found; no run recorded", feed_source_id
                )
                return None

            run_id = await self._start(feed_source_id, run_id)
            processed_count = 0
            failed_count = 0
            statistics: dict = {}
            run_state = RunState()
            try:
                for step in self._steps:
                    ctx = StepContext(
                        feed_source_id=feed_source_id,
                        session_factory=self._session_factory,
                        logger=logger,
                        run_state=run_state,
                        ingestion_run_id=run_id,
                    )
                    result: StepResult = await step.execute(ctx)
                    processed_count += result.processed_count
                    failed_count += result.failed_count
                    statistics.update(result.statistics)
            except Exception as exc:
                logger.exception("pipeline run %s failed for feed source %s", run_id, feed_source_id)
                return await self._finish(
                    feed_source_id,
                    run_id,
                    "error",
                    processed_count=processed_count,
                    failed_count=failed_count,
                    statistics=statistics,
                    error_message=str(exc)[:4000],
                    error_stack_trace=traceback.format_exc()[:20000],
                )
            return await self._finish(
                feed_source_id,
                run_id,
                "success",
                processed_count=processed_count,
                failed_count=failed_count,
                statistics=statistics,
            )
        finally:
            lock.release()

    async def _feed_source_exists(self, feed_source_id: int) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                return await session.get(FeedSource, feed_source_id) is not None

    async def _start(self, feed_source_id: int, run_id: int | None) -> int:
        async with self._session_factory() as session:
            async with session.begin():
                if run_id is None:
                    run = IngestionRun(feed_source_id=feed_source_id, status="running")
                    session.add(run)
                    await session.flush()
                    return run.id
                run = await session.get(IngestionRun, run_id)
                if run is None:
                    raise ValueError(f"unknown run id {run_id}")
                run.status = "running"
                return run.id

    async def _finish(
        self,
        feed_source_id: int,
        run_id: int | None,
        status: str,
        processed_count: int = 0,
        failed_count: int = 0,
        statistics: dict | None = None,
        error_message: str | None = None,
        error_stack_trace: str | None = None,
    ) -> int:
        async with self._session_factory() as session:
            async with session.begin():
                if run_id is None:
                    run = IngestionRun(feed_source_id=feed_source_id, status=status)
                    session.add(run)
                    await session.flush()
                else:
                    run = await session.get(IngestionRun, run_id)
                    if run is None:
                        raise ValueError(f"unknown run id {run_id}")
                    run.status = status
                run.processed_count = processed_count
                run.failed_count = failed_count
                run.statistics = statistics or {}
                run.error_message = error_message
                run.error_stack_trace = error_stack_trace
                run.completed_at = datetime.now(timezone.utc)
                return run.id
