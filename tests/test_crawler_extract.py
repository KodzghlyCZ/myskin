from __future__ import annotations

import unittest
from pathlib import Path

from myskin.crawler.config import CrawlSettings
from myskin.crawler.extract import extract_page

EDU_HTML = """<!doctype html>
<html><head><title>Anonymní režim</title></head>
<body>
<header class="bde-header-builder">
  Jednotný metodický portál Search for: Ukrajina Starší obsah
  <a href="https://edu.gov.cz/nav.pdf">nav</a>
</header>
<main>
  <h1>Režim soukromého prohlížení</h1>
  <p>Tělo článku o anonymním režimu.</p>
  <a href="https://edu.gov.cz/priloha.pdf">příloha</a>
  <aside class="bde-header-builder">Nejdůležitější odkazy</aside>
</main>
</body></html>
"""

TAG_HTML = """<!doctype html>
<html><head><title>Archiv</title></head>
<body>
<header class="bde-header-builder">Starší obsah Search for: Ukrajina</header>
<section><p>Menu Newsletter Copyright</p></section>
</body></html>
"""

EDU_RULES = [
    {
        "select": "main, article",
        "remove": ["header", "nav", "footer", ".bde-header-builder"],
    }
]


def _settings(rules):
    return CrawlSettings.from_mapping(
        {"seed_url": "https://edu.gov.cz/", "content_rules": rules},
        data_dir=Path("/tmp"),
        state_db=Path("/tmp/crawl.db"),
    )


class ContentRuleTests(unittest.TestCase):
    def test_article_keeps_body_and_drops_chrome(self) -> None:
        rules = _settings(EDU_RULES).content_rules
        page = extract_page(EDU_HTML.encode(), "https://edu.gov.cz/anonymni-rezim", content_rules=rules)
        self.assertIn("Tělo článku o anonymním režimu", page.markdown)
        self.assertIn("Režim soukromého prohlížení", page.markdown)
        self.assertNotIn("Ukrajina", page.markdown)
        self.assertNotIn("Starší obsah", page.markdown)
        self.assertNotIn("Nejdůležitější", page.markdown)
        self.assertNotIn("Search for", page.markdown)
        self.assertEqual(page.file_links, ["https://edu.gov.cz/priloha.pdf"])

    def test_archive_without_main_is_skipped(self) -> None:
        rules = _settings(EDU_RULES).content_rules
        page = extract_page(TAG_HTML.encode(), "https://edu.gov.cz/tag/kariera", content_rules=rules)
        self.assertEqual(page.markdown, "")
        self.assertEqual(page.file_links, [])

    def test_unmatched_url_keeps_default_extraction(self) -> None:
        rules = _settings(
            [{"url_regex": r"/metodicke_materialy/", "select": "main"}]
        ).content_rules
        page = extract_page(EDU_HTML.encode(), "https://edu.gov.cz/anonymni-rezim", content_rules=rules)
        self.assertIn("Tělo článku o anonymním režimu", page.markdown)
        self.assertIn("https://edu.gov.cz/nav.pdf", page.file_links)

    def test_invalid_selector_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _settings([{"select": "main:not("}])

    def test_no_rules_still_prefers_main(self) -> None:
        page = extract_page(EDU_HTML.encode(), "https://edu.gov.cz/anonymni-rezim")
        self.assertIn("Tělo článku o anonymním režimu", page.markdown)
        self.assertNotIn("Ukrajina", page.markdown)
        self.assertIn("https://edu.gov.cz/nav.pdf", page.file_links)


if __name__ == "__main__":
    unittest.main()
