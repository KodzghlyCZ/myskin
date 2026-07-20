from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from myskin.crawler.config import CrawlSettings
from myskin.crawler.engine import CrawlEngine, CrawlResult
from myskin.crawler.progress import CrawlProgressDisplay
from myskin.crawler.state import CrawlStats
from myskin.ragflow_sync import maybe_sync_after_crawl
from myskin.sites.models import SiteRecord
from myskin.sites.service import site_service

logger = logging.getLogger(__name__)


class CrawlAlreadyRunningError(RuntimeError):
    pass


@dataclass
class CrawlRunSnapshot:
    site_id: str | None = None
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
    running_site_id: str | None = None
    last_snapshot: CrawlRunSnapshot = field(default_factory=CrawlRunSnapshot)
    last_snapshots: dict[str, CrawlRunSnapshot] = field(default_factory=dict)

    def run(
        self,
        site: SiteRecord | None = None,
        settings: CrawlSettings | None = None,
        *,
        trigger: str = "manual",
        progress: CrawlProgressDisplay | None = None,
    ) -> CrawlResult:
        if not self._lock.acquire(blocking=False):
            raise CrawlAlreadyRunningError("A crawl is already in progress")

        resolved_site = site or site_service.default_site()
        if resolved_site is None:
            self._lock.release()
            raise RuntimeError("No sites configured")

        cfg = settings or site_service.crawl_settings_for(resolved_site)
        display = progress if progress is not None else CrawlProgressDisplay()
        snapshot = CrawlRunSnapshot(
            site_id=resolved_site.site_id,
            started_at=_utcnow(),
            trigger=trigger,
        )
        self.running = True
        self.running_site_id = resolved_site.site_id
        self.last_snapshot = snapshot
        self.last_snapshots[resolved_site.site_id] = snapshot

        engine_logger = logging.getLogger("myskin.crawler.engine")
        previous_level = engine_logger.level
        if display.uses_tty:
            engine_logger.setLevel(logging.WARNING)

        try:
            logger.info(
                "Starting crawl for site=%s (trigger=%s, seed=%s)",
                resolved_site.site_id,
                trigger,
                cfg.seed_url,
            )
            result = CrawlEngine(cfg, progress=display).run(trigger=trigger)
            snapshot.run_id = result.run_id
            snapshot.stats = result.stats
            snapshot.finished_at = _utcnow()
            if not display.uses_tty:
                logger.info(
                    "Crawl #%s finished for site=%s: pages=%s updated=%s, files=%s updated=%s",
                    result.run_id,
                    resolved_site.site_id,
                    result.stats.pages_fetched,
                    result.stats.pages_updated,
                    result.stats.pdfs_fetched,
                    result.stats.pdfs_updated,
                )

            ragflow = site_service.ragflow_settings_for(resolved_site)
            data_dir = site_service.data_dir_for(resolved_site)
            from myskin.catalog import scan_documents

            documents = scan_documents(
                data_dir=data_dir,
                file_url_builder=lambda doc_id: site_service.file_url_for(
                    resolved_site, doc_id
                ),
            )
            maybe_sync_after_crawl(
                site_id=resolved_site.site_id,
                ragflow=ragflow,
                data_dir=data_dir,
                documents=documents,
            )
            return result
        except Exception as exc:
            snapshot.error = str(exc)
            snapshot.finished_at = _utcnow()
            display.abort()
            logger.exception("Crawl failed for site=%s", resolved_site.site_id)
            raise
        finally:
            if display.uses_tty:
                engine_logger.setLevel(previous_level)
            self.running = False
            self.running_site_id = None
            self._lock.release()

    def run_site(
        self,
        site_id: str,
        *,
        trigger: str = "manual",
        progress: CrawlProgressDisplay | None = None,
    ) -> CrawlResult:
        site = site_service.require_site(site_id)
        if not site.enabled:
            raise RuntimeError(f"Site is disabled: {site_id}")
        return self.run(site, trigger=trigger, progress=progress)

    def snapshot_for(self, site_id: str) -> CrawlRunSnapshot | None:
        return self.last_snapshots.get(site_id)


crawl_runner = CrawlRunner()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
