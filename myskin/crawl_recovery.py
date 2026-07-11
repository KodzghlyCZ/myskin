from __future__ import annotations

import asyncio
import logging

from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.crawler.config import crawl_settings
from myskin.crawler.state import CrawlState
from myskin.scheduler_config import scheduler_settings

logger = logging.getLogger(__name__)


def mark_interrupted_runs() -> list[int]:
    """Close out crawl runs that were still open when the process stopped."""
    return CrawlState(crawl_settings.state_db).abort_unfinished_runs()


async def run_recovery_crawl() -> None:
    try:
        await asyncio.to_thread(crawl_runner.run, trigger="recovery")
    except CrawlAlreadyRunningError:
        logger.warning("Recovery crawl skipped — crawl already in progress")
    except Exception:
        logger.exception("Recovery crawl failed")


async def recover_interrupted_crawl_on_startup() -> None:
    interrupted = mark_interrupted_runs()
    if not interrupted:
        return

    logger.warning(
        "Marked %s interrupted crawl run(s) as finished: %s",
        len(interrupted),
        interrupted,
    )

    if not crawl_settings.resume_on_startup:
        logger.info("Resume on startup disabled; not starting recovery crawl")
        return

    if scheduler_settings.run_on_startup:
        logger.info("Startup crawl already scheduled; skipping separate recovery crawl")
        return

    logger.info("Starting recovery crawl after interrupted run")
    await run_recovery_crawl()
