from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..models.feed_source import FeedSource
    from .runner import PipelineRunner

logger = logging.getLogger(__name__)


def validate_cron(expression: str) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(expression, timezone="UTC")
    except ValueError as exc:
        raise ValueError(f"invalid cron expression {expression!r}: {exc}") from exc


def job_id(feed_source_id: int) -> str:
    return f"feed-source-{feed_source_id}"


SYSTEM_PURGE_JOB_ID = "system-staging-purge"
PURGE_CRON = "0 3 * * *"


class SchedulerService:
    def __init__(self, runner: PipelineRunner) -> None:
        self._runner = runner
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    async def start(self) -> None:
        self._scheduler.start()

    async def shutdown(self) -> None:
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=False)
        for _ in range(100):
            if not self._scheduler.running:
                return
            await asyncio.sleep(0.01)

    def register(self, feed_source: FeedSource) -> None:
        trigger = validate_cron(feed_source.cron_expression)
        if not self._scheduler.running and self.has_job(feed_source.id):
            self._scheduler.remove_job(job_id(feed_source.id))
        self._scheduler.add_job(
            self._runner.execute,
            trigger,
            args=[feed_source.id],
            id=job_id(feed_source.id),
            replace_existing=True,
            misfire_grace_time=None,
        )

    def unregister(self, feed_source_id: int) -> None:
        if self.has_job(feed_source_id):
            self._scheduler.remove_job(job_id(feed_source_id))

    def has_job(self, feed_source_id: int) -> bool:
        return self._scheduler.get_job(job_id(feed_source_id)) is not None

    def reschedule(self, feed_source: FeedSource) -> None:
        self.register(feed_source)

    def register_system_job(
        self,
        job_id: str,
        cron_expression: str,
        func,
        *args,
    ) -> None:
        trigger = validate_cron(cron_expression)
        self._scheduler.add_job(
            func,
            trigger,
            args=list(args),
            id=job_id,
            replace_existing=True,
            misfire_grace_time=None,
        )

    async def register_all(self, session: AsyncSession) -> int:
        from sqlalchemy import select

        from ..models.feed_source import FeedSource

        result = await session.execute(select(FeedSource))
        registered = 0
        for feed_source in result.scalars():
            if not feed_source.cron_expression:
                continue
            try:
                self.register(feed_source)
                registered += 1
            except ValueError:
                logger.exception("failed to register feed source %s", feed_source.id)
        return registered
