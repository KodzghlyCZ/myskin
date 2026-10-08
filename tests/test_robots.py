from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from myskin.crawler.fetch import RobotsCache


class RobotsCacheTests(unittest.TestCase):
    def test_missing_robots_allows_the_host(self) -> None:
        response = httpx.Response(404, text="missing")
        with patch("myskin.crawler.fetch.httpx.get", return_value=response) as get:
            cache = RobotsCache("MyskinCrawler/1.0")
            self.assertTrue(cache.allowed("https://www.csicr.cz/cz/Dokumenty"))
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], "MyskinCrawler/1.0")

    def test_published_rules_are_honored(self) -> None:
        response = httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        with patch("myskin.crawler.fetch.httpx.get", return_value=response) as get:
            cache = RobotsCache("MyskinCrawler/1.0")
            self.assertTrue(cache.allowed("https://example.com/cs/1"))
            self.assertFalse(cache.allowed("https://example.com/private/x"))
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
