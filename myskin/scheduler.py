from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.scheduler_config import SchedulerSettings
from myskin.sites.service import site_service

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


async def run_scheduled_crawl_for_site(site_id: str) -> None:
    try:
        await asyncio.to_thread(crawl_runner.run_site, site_id, trigger="scheduler")
    except CrawlAlreadyRunningError:
        logger.warning(
            "Skipping scheduled crawl for site=%s — another crawl is active",
            site_id,
        )
    except Exception:
        logger.exception("Scheduled crawl failed for site=%s", site_id)


async def run_startup_crawls() -> None:
    for site in site_service.list_sites(enabled_only=True):
        sched = site_service.scheduler_settings_for(site)
        if sched.enabled and sched.run_on_startup:
            await run_scheduled_crawl_for_site(site.site_id)


async def run_scheduled_crawls() -> None:
    sites = site_service.list_sites(enabled_only=True)
    for site in sites:
        sched = site_service.scheduler_settings_for(site)
        if not sched.enabled:
            continue
        await run_scheduled_crawl_for_site(site.site_id)


def _job_id(site_id: str) -> str:
    return f"myskin-crawl-{site_id}"


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler

    sites = site_service.list_sites(enabled_only=True)
    scheduled = [
        site
        for site in sites
        if site_service.scheduler_settings_for(site).enabled
    ]
    if not scheduled:
        logger.info("No enabled sites with scheduler — internal scheduler not started")
        return None

    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler()
    for site in scheduled:
        sched = site_service.scheduler_settings_for(site)
        scheduler.add_job(
            run_scheduled_crawl_for_site,
            trigger=_build_trigger(sched),
            args=[site.site_id],
            id=_job_id(site.site_id),
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "Scheduled site=%s: %s",
            site.site_id,
            sched.schedule_description,
        )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started for %d site(s)", len(scheduled))
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def reload_scheduler() -> AsyncIOScheduler | None:
    stop_scheduler()
    return start_scheduler()


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def get_next_run_at(site_id: str | None = None) -> datetime | None:
    scheduler = get_scheduler()
    if scheduler is None:
        return None
    if site_id:
        job: Job | None = scheduler.get_job(_job_id(site_id))
        return job.next_run_time if job else None

    earliest: datetime | None = None
    for site in site_service.list_sites(enabled_only=True):
        when = get_next_run_at(site.site_id)
        if when is None:
            continue
        if earliest is None or when < earliest:
            earliest = when
    return earliest
