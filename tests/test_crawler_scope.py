from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from myskin.crawler.config import CrawlSettings
from myskin.crawler.sitemap import SitemapEntry, load_sitemap_entries, parse_sitemap_xml
from myskin.crawler.urls import is_in_scope, normalize_url, same_host


def _url(value: str):
    parsed = normalize_url(value)
    assert parsed is not None
    return parsed


class UrlScopeTests(unittest.TestCase):
    def test_host_and_seed_prefix(self) -> None:
        seed = _url("https://edu.gov.cz/cs/")
        self.assertTrue(is_in_scope(_url("https://edu.gov.cz/cs/dokumenty/a"), seed))
        self.assertTrue(is_in_scope(_url("https://edu.gov.cz/cs"), seed))
        self.assertFalse(is_in_scope(_url("https://edu.gov.cz/en/dokumenty/a"), seed))
        self.assertFalse(is_in_scope(_url("https://other.example/cs/a"), seed))

    def test_root_seed_allows_whole_host(self) -> None:
        seed = _url("https://edu.gov.cz/")
        self.assertTrue(is_in_scope(_url("https://edu.gov.cz/anything"), seed))

    def test_regex_matches_full_url_or_path(self) -> None:
        seed = _url("https://edu.gov.cz/")
        prefix = re.compile(r"^https://edu\.gov\.cz/cs/")
        path_only = re.compile(r"^/cs/")
        self.assertTrue(is_in_scope(_url("https://edu.gov.cz/cs/foo"), seed, url_pattern=prefix))
        self.assertFalse(is_in_scope(_url("https://edu.gov.cz/en/foo"), seed, url_pattern=prefix))
        self.assertTrue(is_in_scope(_url("https://edu.gov.cz/cs/foo"), seed, url_pattern=path_only))
        self.assertFalse(is_in_scope(_url("https://edu.gov.cz/en/foo"), seed, url_pattern=path_only))

    def test_regex_and_seed_prefix_both_apply(self) -> None:
        seed = _url("https://edu.gov.cz/cs/")
        pattern = re.compile(r"/dokumenty/")
        self.assertTrue(is_in_scope(_url("https://edu.gov.cz/cs/dokumenty/a"), seed, url_pattern=pattern))
        self.assertFalse(is_in_scope(_url("https://edu.gov.cz/cs/novinky/a"), seed, url_pattern=pattern))

    def test_same_host_ignores_path(self) -> None:
        seed = _url("https://edu.gov.cz/cs/")
        self.assertTrue(same_host(_url("https://edu.gov.cz/sitemap.xml"), seed))
        self.assertFalse(same_host(_url("https://other.example/sitemap.xml"), seed))


class CrawlSettingsSitemapTests(unittest.TestCase):
    def test_single_sitemap_url_string(self) -> None:
        settings = CrawlSettings.from_mapping(
            {"seed_url": "https://edu.gov.cz/", "sitemap_url": "https://edu.gov.cz/sitemap.xml"},
            data_dir=Path("/tmp"),
            state_db=Path("/tmp/crawl.db"),
        )
        self.assertEqual(settings.sitemap_urls, ("https://edu.gov.cz/sitemap.xml",))
        self.assertEqual(settings.sitemap_url, "https://edu.gov.cz/sitemap.xml")

    def test_multiple_sitemap_urls_list(self) -> None:
        settings = CrawlSettings.from_mapping(
            {
                "seed_url": "https://edu.gov.cz/",
                "sitemap_url": [
                    "https://edu.gov.cz/page-sitemap.xml",
                    "https://edu.gov.cz/post-sitemap.xml",
                ],
            },
            data_dir=Path("/tmp"),
            state_db=Path("/tmp/crawl.db"),
        )
        self.assertEqual(
            settings.sitemap_urls,
            (
                "https://edu.gov.cz/page-sitemap.xml",
                "https://edu.gov.cz/post-sitemap.xml",
            ),
        )

    def test_merges_sitemap_url_and_sitemap_urls(self) -> None:
        settings = CrawlSettings.from_mapping(
            {
                "seed_url": "https://edu.gov.cz/",
                "sitemap_url": "https://edu.gov.cz/a.xml",
                "sitemap_urls": ["https://edu.gov.cz/b.xml", "https://edu.gov.cz/a.xml"],
            },
            data_dir=Path("/tmp"),
            state_db=Path("/tmp/crawl.db"),
        )
        self.assertEqual(
            settings.sitemap_urls,
            ("https://edu.gov.cz/a.xml", "https://edu.gov.cz/b.xml"),
        )

    def test_newline_separated_sitemap_urls(self) -> None:
        settings = CrawlSettings.from_mapping(
            {
                "seed_url": "https://edu.gov.cz/",
                "sitemap_url": "https://edu.gov.cz/a.xml\nhttps://edu.gov.cz/b.xml\n",
            },
            data_dir=Path("/tmp"),
            state_db=Path("/tmp/crawl.db"),
        )
        self.assertEqual(
            settings.sitemap_urls,
            ("https://edu.gov.cz/a.xml", "https://edu.gov.cz/b.xml"),
        )

    def test_url_regex_compiles(self) -> None:
        settings = CrawlSettings.from_mapping(
            {"seed_url": "https://edu.gov.cz/", "url_regex": r"^/cs/"},
            data_dir=Path("/tmp"),
            state_db=Path("/tmp/crawl.db"),
        )
        self.assertIsNotNone(settings.url_pattern)
        self.assertTrue(settings.allows_url(_url("https://edu.gov.cz/cs/x"), _url(settings.seed_url)))
        self.assertFalse(settings.allows_url(_url("https://edu.gov.cz/en/x"), _url(settings.seed_url)))

    def test_invalid_url_regex_raises(self) -> None:
        with self.assertRaises(ValueError):
            CrawlSettings.from_mapping(
                {"seed_url": "https://edu.gov.cz/", "url_regex": "("},
                data_dir=Path("/tmp"),
                state_db=Path("/tmp/crawl.db"),
            )


@dataclass
class _FakeResult:
    status_code: int
    content: bytes


class _FakeFetcher:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    def fetch(self, url: str) -> _FakeResult:
        return _FakeResult(status_code=200, content=self.payloads[url])


class SitemapLoadTests(unittest.TestCase):
    def test_parse_urlset(self) -> None:
        xml = b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://edu.gov.cz/cs/a</loc></url>
          <url><loc>https://edu.gov.cz/en/b</loc></url>
        </urlset>
        """
        entries, children = parse_sitemap_xml(xml)
        self.assertEqual([entry.url for entry in entries], ["https://edu.gov.cz/cs/a", "https://edu.gov.cz/en/b"])
        self.assertEqual(children, [])

    def test_loads_multiple_sitemaps_and_filters_pages(self) -> None:
        fetcher = _FakeFetcher(
            {
                "https://edu.gov.cz/a.xml": b"""<?xml version="1.0"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://edu.gov.cz/cs/one</loc></url>
                  <url><loc>https://edu.gov.cz/en/skip</loc></url>
                </urlset>
                """,
                "https://edu.gov.cz/b.xml": b"""<?xml version="1.0"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://edu.gov.cz/cs/two</loc></url>
                </urlset>
                """,
            }
        )
        seed = _url("https://edu.gov.cz/")
        entries = load_sitemap_entries(
            fetcher,
            ("https://edu.gov.cz/a.xml", "https://edu.gov.cz/b.xml"),
            seed,
            url_pattern=re.compile(r"^/cs/"),
        )
        self.assertEqual(
            [entry.url for entry in entries],
            ["https://edu.gov.cz/cs/one", "https://edu.gov.cz/cs/two"],
        )

    def test_fetches_sitemap_outside_page_prefix(self) -> None:
        fetcher = _FakeFetcher(
            {
                "https://edu.gov.cz/sitemap.xml": b"""<?xml version="1.0"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://edu.gov.cz/cs/keep</loc></url>
                  <url><loc>https://edu.gov.cz/en/drop</loc></url>
                </urlset>
                """,
            }
        )
        seed = _url("https://edu.gov.cz/cs/")
        entries = load_sitemap_entries(fetcher, "https://edu.gov.cz/sitemap.xml", seed)
        self.assertEqual([entry.url for entry in entries], ["https://edu.gov.cz/cs/keep"])
        self.assertIsInstance(entries[0], SitemapEntry)


if __name__ == "__main__":
    unittest.main()
