from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from myskin.crawler.config import CrawlSettings, QueuedUrl, crawl_settings
from myskin.crawler.extract import extract_page, extract_pdf_text, pdf_title_from_url
from myskin.crawler.fetch import Fetcher, FetchResult, RobotsCache
from myskin.crawler.state import CrawlState, CrawlStats, ResourceRecord
from myskin.crawler.urls import (
    ParsedUrl,
    content_hash,
    is_css_url,
    is_in_scope,
    is_pdf_url,
    normalize_url,
    url_to_relative_path,
)
from myskin.crawler.progress import CrawlProgressDisplay
from myskin.crawler.sitemap import SitemapEntry, load_sitemap_entries
from myskin.crawler.writer import parse_http_date, remove_file, write_markdown

logger = logging.getLogger(__name__)


@dataclass
class _CrawlFrontier:
    queue: deque[QueuedUrl] = field(default_factory=deque)
    enqueued_urls: set[str] = field(default_factory=set)
    enqueued_paths: set[str] = field(default_factory=set)
    updated_paths: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SitemapQueueInfo:
    total: int
    queued: int
    skipped: int


class CrawlEngine:
    def __init__(
        self,
        settings: CrawlSettings | None = None,
        *,
        progress: CrawlProgressDisplay | None = None,
    ) -> None:
        self.settings = settings or crawl_settings
        self.state = CrawlState(self.settings.state_db)
        self.data_dir = self.settings.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.progress = progress

    def run(self, *, trigger: str = "manual") -> CrawlResult:
        seed = normalize_url(self.settings.seed_url)
        if not seed:
            raise ValueError(f"Invalid seed URL: {self.settings.seed_url!r}")

        stats = CrawlStats()
        run_id = self.state.start_run(seed.normalized)

        robots = RobotsCache(self.settings.user_agent) if self.settings.respect_robots else None

        with Fetcher(
            user_agent=self.settings.user_agent,
            delay_seconds=self.settings.request_delay,
        ) as fetcher:
            queue, frontier, sitemap_info = self._build_queue(seed, fetcher)
            if sitemap_info:
                stats.discovered = sitemap_info.total
                stats.sitemap_urls = sitemap_info.total
                stats.sitemap_queued = sitemap_info.queued
                stats.sitemap_skipped = sitemap_info.skipped

            if self.progress:
                self.progress.start(
                    run_id=run_id,
                    seed_url=seed.normalized,
                    queue_size=len(queue),
                    max_pages=self.settings.max_pages,
                    trigger=trigger,
                    initial_stats=stats,
                )

            while queue and stats.pages_fetched + stats.pdfs_fetched < self.settings.max_pages:
                item = queue.popleft()

                parsed = normalize_url(item.url)
                if not parsed or not is_in_scope(parsed, seed):
                    continue

                if robots and not robots.allowed(parsed.normalized):
                    self._report(
                        "page", "blocked", stats, url=parsed.normalized, label=parsed.normalized
                    )
                    continue

                if is_css_url(parsed.normalized):
                    self._report(
                        "page", "skipped", stats, url=parsed.normalized, label=parsed.normalized
                    )
                    continue

                if is_pdf_url(parsed.normalized):
                    self._process_pdf(parsed, fetcher, stats, frontier=frontier)
                else:
                    discovered = self._process_page(
                        parsed, seed, item.depth, fetcher, stats, frontier
                    )
                    if not self.settings.sitemap_url:
                        stats.discovered += discovered

                if self.progress:
                    self.progress.set_queue_pending(len(queue))

        if self.progress:
            self.progress.finish(stats)

        self.state.finish_run(run_id, stats)
        return CrawlResult(stats=stats, run_id=run_id)

    def _build_queue(
        self, seed: ParsedUrl, fetcher: Fetcher
    ) -> tuple[deque[QueuedUrl], _CrawlFrontier, SitemapQueueInfo | None]:
        frontier = _CrawlFrontier()

        if self.settings.sitemap_url:
            entries = load_sitemap_entries(fetcher, self.settings.sitemap_url, seed)
            queued, skipped = self._enqueue_sitemap_entries(frontier, seed, entries)
            info = SitemapQueueInfo(total=len(entries), queued=queued, skipped=skipped)
            logger.info(
                "Sitemap %s: %d URLs, %d queued, %d skipped (unchanged)",
                self.settings.sitemap_url,
                info.total,
                info.queued,
                info.skipped,
            )
            if entries and queued == 0:
                return frontier.queue, frontier, info
            if not entries:
                logger.warning(
                    "No sitemap entries from %s, falling back to link crawl",
                    self.settings.sitemap_url,
                )
                self._enqueue_link_crawl(frontier, seed)
                return frontier.queue, frontier, None
            return frontier.queue, frontier, info

        self._enqueue_link_crawl(frontier, seed)
        return frontier.queue, frontier, None

    def _enqueue_sitemap_entries(
        self,
        frontier: _CrawlFrontier,
        seed: ParsedUrl,
        entries: list[SitemapEntry],
    ) -> tuple[int, int]:
        queued = 0
        skipped = 0
        for entry in entries:
            parsed = normalize_url(entry.url)
            if not parsed or not is_in_scope(parsed, seed):
                continue
            if is_css_url(parsed.normalized):
                continue
            if not self._needs_sitemap_crawl(parsed.normalized, entry.lastmod):
                skipped += 1
                continue
            rtype = "pdf" if is_pdf_url(parsed.normalized) else "page"
            if self._enqueue_url(frontier, parsed, depth=0, resource_type=rtype):
                queued += 1
        return queued, skipped

    def _needs_sitemap_crawl(self, url: str, sitemap_lastmod: datetime | None) -> bool:
        existing = self.state.get_resource(url)
        if existing is None:
            return True
        if sitemap_lastmod is None:
            return False
        return sitemap_lastmod > existing.last_changed_at

    def _enqueue_link_crawl(self, frontier: _CrawlFrontier, seed: ParsedUrl) -> None:
        resource_type = "pdf" if is_pdf_url(seed.normalized) else "page"
        self._enqueue_url(frontier, seed, depth=0, resource_type=resource_type)

        if self.settings.refresh_known:
            for record in self.state.list_resources():
                parsed = normalize_url(record.url)
                if not parsed or not is_in_scope(parsed, seed):
                    continue
                if is_css_url(parsed.normalized):
                    continue
                rtype = "pdf" if is_pdf_url(parsed.normalized) else "page"
                self._enqueue_url(frontier, parsed, depth=0, resource_type=rtype)

    def _enqueue_url(
        self,
        frontier: _CrawlFrontier,
        parsed: ParsedUrl,
        *,
        depth: int,
        resource_type: str,
    ) -> bool:
        rel_path = url_to_relative_path(parsed, resource_type=resource_type)
        if parsed.normalized in frontier.enqueued_urls:
            return False
        if rel_path in frontier.enqueued_paths:
            return False
        if rel_path in frontier.updated_paths:
            return False
        frontier.enqueued_urls.add(parsed.normalized)
        frontier.enqueued_paths.add(rel_path)
        frontier.queue.append(QueuedUrl(parsed.normalized, depth))
        return True

    def _skip_already_updated(
        self,
        frontier: _CrawlFrontier,
        *,
        kind: str,
        rel_path: str,
        url: str,
        stats: CrawlStats,
    ) -> bool:
        if rel_path not in frontier.updated_paths:
            return False
        self._report(kind, "skipped", stats, url=url, label=rel_path)
        return True

    def _process_page(
        self,
        parsed: ParsedUrl,
        seed: ParsedUrl,
        depth: int,
        fetcher: Fetcher,
        stats: CrawlStats,
        frontier: _CrawlFrontier,
    ) -> int:
        rel_path = url_to_relative_path(parsed, resource_type="page")
        if self._skip_already_updated(
            frontier, kind="page", rel_path=rel_path, url=parsed.normalized, stats=stats
        ):
            return 0

        stats.pages_fetched += 1

        try:
            result = fetcher.fetch(parsed.normalized)
        except Exception as exc:
            stats.pages_failed += 1
            self._report("page", "failed", stats, url=parsed.normalized, label=rel_path)
            logger.warning("Failed to fetch page %s: %s", parsed.normalized, exc)
            return 0

        if result.status_code == 404:
            stats.pages_failed += 1
            self._remove_gone(parsed.normalized)
            self._report("page", "failed", stats, url=parsed.normalized, label=rel_path)
            return 0

        if result.status_code >= 400:
            stats.pages_failed += 1
            self._report("page", "failed", stats, url=parsed.normalized, label=rel_path)
            logger.warning("HTTP %s for %s", result.status_code, parsed.normalized)
            return 0

        if "pdf" in result.content_type or is_pdf_url(result.url):
            stats.pages_fetched -= 1
            self._process_pdf(parsed, fetcher, stats, frontier=frontier, result=result)
            return 0

        if "css" in result.content_type:
            stats.pages_fetched -= 1
            self._report("page", "skipped", stats, url=parsed.normalized, label=rel_path)
            return 0

        if "html" not in result.content_type and "text/" not in result.content_type:
            stats.pages_failed += 1
            self._report("page", "skipped", stats, url=parsed.normalized, label=rel_path)
            return 0

        try:
            page = extract_page(result.content, parsed.normalized)
        except Exception as exc:
            stats.pages_failed += 1
            self._report("page", "failed", stats, url=parsed.normalized, label=rel_path)
            logger.warning("Failed to parse HTML %s: %s", parsed.normalized, exc)
            return 0

        body = page.markdown
        if not body.strip():
            stats.pages_failed += 1
            self._report("page", "skipped", stats, url=parsed.normalized, label=rel_path)
            return 0

        changed = self._store_resource(
            url=parsed.normalized,
            resource_type="page",
            rel_path=rel_path,
            title=page.title,
            body=body,
            category="page",
            digest=content_hash(body.encode("utf-8")),
            result=result,
            frontier=frontier,
        )
        if changed:
            stats.pages_updated += 1
            self._report("page", "updated", stats, url=parsed.normalized, label=rel_path)
        else:
            stats.pages_unchanged += 1
            self._report("page", "unchanged", stats, url=parsed.normalized, label=rel_path)

        discovered = 0
        if (
            not self.settings.sitemap_only
            and depth < self.settings.max_depth
        ):
            for link in (*page.page_links, *page.pdf_links):
                link_parsed = normalize_url(link)
                if not link_parsed or not is_in_scope(link_parsed, seed):
                    continue
                if is_css_url(link_parsed.normalized):
                    continue
                rtype = "pdf" if is_pdf_url(link_parsed.normalized) else "page"
                if self._enqueue_url(
                    frontier, link_parsed, depth=depth + 1, resource_type=rtype
                ):
                    discovered += 1

        return discovered

    def _process_pdf(
        self,
        parsed: ParsedUrl,
        fetcher: Fetcher,
        stats: CrawlStats,
        *,
        frontier: _CrawlFrontier,
        result: FetchResult | None = None,
    ) -> None:
        rel_path = url_to_relative_path(parsed, resource_type="pdf")
        if self._skip_already_updated(
            frontier, kind="pdf", rel_path=rel_path, url=parsed.normalized, stats=stats
        ):
            return

        stats.pdfs_fetched += 1

        if result is None:
            try:
                result = fetcher.fetch(parsed.normalized)
            except Exception as exc:
                stats.pdfs_failed += 1
                self._report("pdf", "failed", stats, url=parsed.normalized, label=rel_path)
                logger.warning("Failed to fetch PDF %s: %s", parsed.normalized, exc)
                return

        if result.status_code == 404:
            stats.pdfs_failed += 1
            self._remove_gone(parsed.normalized)
            self._report("pdf", "failed", stats, url=parsed.normalized, label=rel_path)
            return

        if result.status_code >= 400:
            stats.pdfs_failed += 1
            self._report("pdf", "failed", stats, url=parsed.normalized, label=rel_path)
            return

        try:
            text = extract_pdf_text(result.content)
        except Exception as exc:
            stats.pdfs_failed += 1
            self._report("pdf", "failed", stats, url=parsed.normalized, label=rel_path)
            logger.warning("Failed to extract PDF %s: %s", parsed.normalized, exc)
            return

        if not text.strip():
            stats.pdfs_failed += 1
            self._report("pdf", "skipped", stats, url=parsed.normalized, label=rel_path)
            return

        changed = self._store_resource(
            url=parsed.normalized,
            resource_type="pdf",
            rel_path=rel_path,
            title=pdf_title_from_url(parsed),
            body=text,
            category="pdf",
            digest=content_hash(text.encode("utf-8")),
            result=result,
            frontier=frontier,
        )
        if changed:
            stats.pdfs_updated += 1
            self._report("pdf", "updated", stats, url=parsed.normalized, label=rel_path)
        else:
            stats.pdfs_unchanged += 1
            self._report("pdf", "unchanged", stats, url=parsed.normalized, label=rel_path)

    def _store_resource(
        self,
        *,
        url: str,
        resource_type: str,
        rel_path: str,
        title: str,
        body: str,
        category: str,
        digest: str,
        result: FetchResult,
        frontier: _CrawlFrontier,
    ) -> bool:
        if rel_path in frontier.updated_paths:
            return False

        now = _utcnow()
        existing = self.state.get_resource(url)
        if existing is None:
            existing = self.state.get_resource_by_local_path(rel_path)
        http_dt = parse_http_date(result.last_modified)

        if existing and existing.content_hash == digest:
            if existing.url != url:
                self.state.delete_resource(existing.url)
            self.state.upsert_resource(
                ResourceRecord(
                    url=url,
                    resource_type=resource_type,
                    local_path=existing.local_path,
                    content_hash=digest,
                    title=title,
                    etag=result.etag or existing.etag,
                    last_modified=result.last_modified or existing.last_modified,
                    last_crawled_at=now,
                    last_changed_at=existing.last_changed_at,
                    http_status=result.status_code,
                )
            )
            return False

        changed_at = http_dt or now
        if existing and existing.url != url:
            self.state.delete_resource(existing.url)
        write_markdown(
            self.data_dir / rel_path,
            title=title,
            body=body,
            source_url=url,
            category=category,
            content_hash=digest,
            updated_at=changed_at,
        )

        self.state.upsert_resource(
            ResourceRecord(
                url=url,
                resource_type=resource_type,
                local_path=rel_path,
                content_hash=digest,
                title=title,
                etag=result.etag,
                last_modified=result.last_modified,
                last_crawled_at=now,
                last_changed_at=changed_at,
                http_status=result.status_code,
            )
        )
        frontier.updated_paths.add(rel_path)
        return True

    def _report(
        self,
        kind: str,
        outcome: str,
        stats: CrawlStats,
        *,
        url: str,
        label: str | None = None,
    ) -> None:
        display = label or url
        if self.progress:
            self.progress.record(
                kind=kind, outcome=outcome, label=display, url=url, stats=stats
            )
        elif outcome in {"updated", "failed"}:
            logger.info("%s %s: %s", kind, outcome, display)

    def _remove_gone(self, url: str) -> None:
        removed = self.state.delete_resource(url)
        if removed:
            remove_file(self.data_dir, removed)


class CrawlResult:
    def __init__(self, stats: CrawlStats, run_id: int) -> None:
        self.stats = stats
        self.run_id = run_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
