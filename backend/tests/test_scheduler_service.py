import types

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.pipeline import SchedulerService, job_id, validate_cron


class FakeRunner:
    async def execute(self, feed_source_id, run_id=None):
        return None


def feed_source(id, cron_expression):
    return types.SimpleNamespace(id=id, cron_expression=cron_expression)


@pytest.fixture
def service():
    return SchedulerService(FakeRunner())


def test_validate_cron_returns_trigger():
    trigger = validate_cron("0 * * * *")
    assert isinstance(trigger, CronTrigger)


def test_validate_cron_rejects_garbage():
    with pytest.raises(ValueError):
        validate_cron("not a cron")


def test_validate_cron_rejects_croniter_style_day_of_week_seven():
    with pytest.raises(ValueError):
        validate_cron("0 0 * * 7")


def test_job_id_format():
    assert job_id(42) == "feed-source-42"


def test_register_adds_job(service):
    service.register(feed_source(1, "0 * * * *"))
    job = service._scheduler.get_job("feed-source-1")
    assert job is not None
    assert job.misfire_grace_time is None


def test_register_duplicate_replaces(service):
    service.register(feed_source(1, "0 * * * *"))
    service.register(feed_source(1, "30 * * * *"))
    jobs = service._scheduler.get_jobs()
    assert len(jobs) == 1
    assert "30" in str(jobs[0].trigger)


def test_unregister_removes_job(service):
    service.register(feed_source(1, "0 * * * *"))
    service.unregister(1)
    assert service._scheduler.get_job("feed-source-1") is None


def test_unregister_unknown_id_is_noop(service):
    service.unregister(999)


def test_reschedule_updates_trigger(service):
    service.register(feed_source(1, "0 * * * *"))
    service.reschedule(feed_source(1, "15 3 * * *"))
    job = service._scheduler.get_job("feed-source-1")
    assert job is not None
    assert "15" in str(job.trigger) and "3" in str(job.trigger)


def test_scheduler_timezone_is_utc(service):
    assert str(service._scheduler.timezone) == "UTC"


@pytest.mark.asyncio
async def test_shutdown_without_start_does_not_raise(service):
    await service.shutdown()


@pytest.mark.asyncio
async def test_start_and_shutdown(service):
    await service.start()
    assert service._scheduler.running
    await service.shutdown()
    assert not service._scheduler.running
