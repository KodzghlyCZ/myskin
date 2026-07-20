from __future__ import annotations

import asyncio
import logging

from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.sites.service import site_service

logger = logging.getLogger(__name__)


def mark_interrupted_runs() -> list[int]:
    """Close out crawl runs that were still open when the process stopped."""
    interrupted: list[int] = []
    for site in site_service.list_sites():
        from myskin.crawler.state import CrawlState

        state_db = site_service.state_db_for(site)
        if not state_db.exists():
            continue
        interrupted.extend(CrawlState(state_db).abort_unfinished_runs())
    return interrupted


async def run_recovery_crawl(site_id: str) -> None:
    try:
        await asyncio.to_thread(crawl_runner.run_site, site_id, trigger="recovery")
    except CrawlAlreadyRunningError:
        logger.warning("Recovery crawl skipped for site=%s — crawl in progress", site_id)
    except Exception:
        logger.exception("Recovery crawl failed for site=%s", site_id)


async def recover_interrupted_crawl_on_startup() -> None:
    interrupted = mark_interrupted_runs()
    if not interrupted:
        return

    logger.warning(
        "Marked %s interrupted crawl run(s) as finished: %s",
        len(interrupted),
        interrupted,
    )

    for site in site_service.list_sites(enabled_only=True):
        cfg = site_service.crawl_settings_for(site)
        if not cfg.resume_on_startup:
            logger.info("Resume on startup disabled for site=%s", site.site_id)
            continue

        sched = site_service.scheduler_settings_for(site)
        if sched.run_on_startup:
            logger.info(
                "Startup crawl already scheduled for site=%s; skipping recovery",
                site.site_id,
            )
            continue

        logger.info("Starting recovery crawl for site=%s", site.site_id)
        await run_recovery_crawl(site.site_id)
