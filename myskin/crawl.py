"""CLI entry point: python -m myskin.crawl"""

from __future__ import annotations

import argparse
import logging
import sys

from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.crawler.config import CrawlSettings
from myskin.crawler.progress import CrawlProgressDisplay
from myskin.sites.service import site_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crawl pages and PDFs into the myskin data directory for RAGFlow.",
    )
    parser.add_argument("--site", help="Site id (default: first configured site)")
    parser.add_argument("--seed", help="Seed URL override")
    parser.add_argument("--max-depth", type=int, help="Max link depth from seed")
    parser.add_argument("--max-pages", type=int, help="Max resources to fetch per run")
    parser.add_argument("--delay", type=float, help="Seconds between HTTP requests")
    parser.add_argument(
        "--no-refresh-known",
        action="store_true",
        help="Only follow links from seed; do not re-check known URLs",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable live crawl progress output",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    site_service.bootstrap()
    site = (
        site_service.require_site(args.site)
        if args.site
        else site_service.default_site()
    )
    if site is None:
        print("Error: no sites configured", file=sys.stderr)
        return 2

    mapping = dict(site.crawler)
    if args.seed:
        mapping["seed_url"] = args.seed
    if args.max_depth is not None:
        mapping["max_depth"] = args.max_depth
    if args.max_pages is not None:
        mapping["max_pages"] = args.max_pages
    if args.delay is not None:
        mapping["request_delay"] = args.delay
    if args.no_refresh_known:
        mapping["refresh_known"] = False

    settings = CrawlSettings.from_mapping(
        mapping,
        data_dir=site_service.data_dir_for(site),
        state_db=site_service.state_db_for(site),
    )
    progress = CrawlProgressDisplay(
        mode="off" if args.no_progress else ("tty" if sys.stderr.isatty() else "log")
    )
    try:
        result = crawl_runner.run(site, settings, trigger="cli", progress=progress)
    except CrawlAlreadyRunningError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    s = result.stats

    print(
        f"Crawl run #{result.run_id} complete for site={site.site_id}: "
        f"pages={s.pages_fetched} (updated={s.pages_updated}, unchanged={s.pages_unchanged}, failed={s.pages_failed}), "
        f"pdfs={s.pdfs_fetched} (updated={s.pdfs_updated}, unchanged={s.pdfs_unchanged}, failed={s.pdfs_failed}), "
        f"discovered={s.discovered}"
    )
    return 0 if (s.pages_failed + s.pdfs_failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
