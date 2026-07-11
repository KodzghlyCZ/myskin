from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.scheduler_config import SchedulerSettings, scheduler_settings

if TYPE_CHECKING:
    from apscheduler.job import Job

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _build_trigger(settings: SchedulerSettings):
    if settings.mode == "interval":
        seconds = settings.interval_seconds
        assert seconds is not None
        return IntervalTrigger(seconds=seconds, timezone=settings.tzinfo())
    return CronTrigger.from_crontab(settings.cron, timezone=settings.tzinfo())


async def run_scheduled_crawl() -> None:
    try:
        await asyncio.to_thread(crawl_runner.run, trigger="scheduler")
    except CrawlAlreadyRunningError:
        logger.warning("Skipping scheduled crawl — previous run still active")
    except Exception:
        logger.exception("Scheduled crawl failed")


def start_scheduler(settings: SchedulerSettings | None = None) -> AsyncIOScheduler | None:
    global _scheduler

    cfg = settings or scheduler_settings
    if not cfg.enabled:
        logger.info("Internal scheduler disabled (MYSKIN_SCHEDULER_ENABLED=false)")
        return None

    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone=cfg.tzinfo())
    scheduler.add_job(
        run_scheduled_crawl,
        trigger=_build_trigger(cfg),
        id="myskin-crawl",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    _scheduler = scheduler

    logger.info("Scheduler started: %s", cfg.schedule_description)

    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def get_next_run_at() -> datetime | None:
    scheduler = get_scheduler()
    if scheduler is None:
        return None
    job: Job | None = scheduler.get_job("myskin-crawl")
    if job is None:
        return None
    return job.next_run_time
