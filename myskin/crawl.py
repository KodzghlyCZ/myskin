"""CLI entry point: python -m myskin.crawl"""

from __future__ import annotations

import argparse
import logging
import sys

from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.crawler.config import CrawlSettings
from myskin.crawler.progress import CrawlProgressDisplay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crawl pages and PDFs into the myskin data directory for RAGFlow.",
    )
    parser.add_argument("--seed", help="Seed URL (default: crawler.seed_url in config.yaml)")
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

    overrides: dict = {}
    if args.seed:
        overrides["seed_url"] = args.seed
    if args.max_depth is not None:
        overrides["max_depth"] = args.max_depth
    if args.max_pages is not None:
        overrides["max_pages"] = args.max_pages
    if args.delay is not None:
        overrides["request_delay"] = args.delay
    if args.no_refresh_known:
        overrides["refresh_known"] = False

    settings = CrawlSettings()
    for key, value in overrides.items():
        setattr(settings, key, value)
    progress = CrawlProgressDisplay(
        mode="off" if args.no_progress else ("tty" if sys.stderr.isatty() else "log")
    )
    try:
        result = crawl_runner.run(settings, trigger="cli", progress=progress)
    except CrawlAlreadyRunningError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    s = result.stats

    print(
        f"Crawl run #{result.run_id} complete: "
        f"pages={s.pages_fetched} (updated={s.pages_updated}, unchanged={s.pages_unchanged}, failed={s.pages_failed}), "
        f"pdfs={s.pdfs_fetched} (updated={s.pdfs_updated}, unchanged={s.pdfs_unchanged}, failed={s.pdfs_failed}), "
        f"discovered={s.discovered}"
    )
    return 0 if (s.pages_failed + s.pdfs_failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
