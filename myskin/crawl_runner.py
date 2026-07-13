from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from myskin.crawler.config import CrawlSettings, crawl_settings
from myskin.crawler.engine import CrawlEngine, CrawlResult
from myskin.crawler.state import CrawlStats

logger = logging.getLogger(__name__)


class CrawlAlreadyRunningError(RuntimeError):
    pass


@dataclass
class CrawlRunSnapshot:
    run_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stats: CrawlStats | None = None
    error: str | None = None
    trigger: str = "manual"


@dataclass
class CrawlRunner:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    running: bool = False
    last_snapshot: CrawlRunSnapshot = field(default_factory=CrawlRunSnapshot)

    def run(
        self,
        settings: CrawlSettings | None = None,
        *,
        trigger: str = "manual",
        progress: CrawlProgressDisplay | None = None,
    ) -> CrawlResult:
        if not self._lock.acquire(blocking=False):
            raise CrawlAlreadyRunningError("A crawl is already in progress")

        cfg = settings or crawl_settings
        display = progress if progress is not None else CrawlProgressDisplay()
        snapshot = CrawlRunSnapshot(started_at=_utcnow(), trigger=trigger)
        self.running = True
        self.last_snapshot = snapshot

        engine_logger = logging.getLogger("myskin.crawler.engine")
        previous_level = engine_logger.level
        if display.uses_tty:
            engine_logger.setLevel(logging.WARNING)

        try:
            logger.info("Starting crawl (trigger=%s, seed=%s)", trigger, cfg.seed_url)
            result = CrawlEngine(cfg, progress=display).run(trigger=trigger)
            snapshot.run_id = result.run_id
            snapshot.stats = result.stats
            snapshot.finished_at = _utcnow()
            if not display.uses_tty:
                logger.info(
                    "Crawl #%s finished: pages=%s updated=%s, files=%s updated=%s",
                    result.run_id,
                    result.stats.pages_fetched,
                    result.stats.pages_updated,
                    result.stats.pdfs_fetched,
                    result.stats.pdfs_updated,
                )
            return result
        except Exception as exc:
            snapshot.error = str(exc)
            snapshot.finished_at = _utcnow()
            display.abort()
            logger.exception("Crawl failed")
            raise
        finally:
            if display.uses_tty:
                engine_logger.setLevel(previous_level)
            self.running = False
            self._lock.release()


crawl_runner = CrawlRunner()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
