from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from myskin.crawler.fetch import Fetcher
from myskin.crawler.urls import ParsedUrl, is_in_scope, normalize_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    lastmod: datetime | None


def parse_sitemap_lastmod(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_sitemap_xml(content: bytes) -> tuple[list[SitemapEntry], list[str]]:
    root = ET.fromstring(content)
    root_name = _local_name(root.tag)

    if root_name == "sitemapindex":
        children: list[str] = []
        for sitemap_el in root:
            if _local_name(sitemap_el.tag) != "sitemap":
                continue
            loc = _child_text(sitemap_el, "loc")
            if loc:
                children.append(loc.strip())
        return [], children

    if root_name == "urlset":
        entries: list[SitemapEntry] = []
        for url_el in root:
            if _local_name(url_el.tag) != "url":
                continue
            loc = _child_text(url_el, "loc")
            if not loc:
                continue
            lastmod = parse_sitemap_lastmod(_child_text(url_el, "lastmod"))
            entries.append(SitemapEntry(url=loc.strip(), lastmod=lastmod))
        return entries, []

    logger.warning("Unrecognized sitemap root element: %s", root_name)
    return [], []


def _child_text(parent: ET.Element, name: str) -> str | None:
    for child in parent:
        if _local_name(child.tag) == name and child.text:
            return child.text
    return None


def load_sitemap_entries(
    fetcher: Fetcher,
    sitemap_url: str,
    seed: ParsedUrl,
    *,
    max_depth: int = 3,
) -> list[SitemapEntry]:
    merged: dict[str, datetime | None] = {}
    _collect_sitemap(fetcher, sitemap_url, seed, merged, depth=0, max_depth=max_depth)
    return [SitemapEntry(url=url, lastmod=lastmod) for url, lastmod in sorted(merged.items())]


def _collect_sitemap(
    fetcher: Fetcher,
    sitemap_url: str,
    seed: ParsedUrl,
    merged: dict[str, datetime | None],
    *,
    depth: int,
    max_depth: int,
) -> None:
    if depth > max_depth:
        logger.warning("Sitemap recursion limit reached at %s", sitemap_url)
        return

    parsed = normalize_url(sitemap_url)
    if not parsed or not is_in_scope(parsed, seed):
        return

    try:
        result = fetcher.fetch(parsed.normalized)
    except Exception as exc:
        logger.warning("Failed to fetch sitemap %s: %s", parsed.normalized, exc)
        return

    if result.status_code >= 400:
        logger.warning("HTTP %s for sitemap %s", result.status_code, parsed.normalized)
        return

    try:
        entries, children = parse_sitemap_xml(result.content)
    except ET.ParseError as exc:
        logger.warning("Failed to parse sitemap %s: %s", parsed.normalized, exc)
        return

    for entry in entries:
        page = normalize_url(entry.url)
        if not page or not is_in_scope(page, seed):
            continue
        url = page.normalized
        existing = merged.get(url)
        if existing is None or _is_newer(entry.lastmod, existing):
            merged[url] = entry.lastmod

    for child_url in children:
        _collect_sitemap(fetcher, child_url, seed, merged, depth=depth + 1, max_depth=max_depth)


def _is_newer(candidate: datetime | None, current: datetime | None) -> bool:
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate > current
