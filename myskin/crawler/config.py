from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myskin.config import settings as app_settings
from myskin.settings_loader import cfg_bool, cfg_get, cfg_path, ensure_config_loaded


class CrawlSettings:
    def __init__(self) -> None:
        ensure_config_loaded()
        self.seed_url: str = str(cfg_get("crawler.seed_url", default="https://edu.gov.cz/"))
        self.max_depth: int = int(cfg_get("crawler.max_depth", default=3))
        self.max_pages: int = int(cfg_get("crawler.max_pages", default=1000))
        self.request_delay: float = float(cfg_get("crawler.request_delay", default=2.5))
        self.user_agent: str = str(
            cfg_get(
                "crawler.user_agent",
                default="MyskinCrawler/1.0 (+https://github.com/KodzghlyCZ/myskin)",
            )
        )
        self.respect_robots: bool = cfg_bool("crawler.respect_robots", True)
        self.state_db: Path = cfg_path("crawler.state_db", "./.myskin/crawl.db")
        self.refresh_known: bool = cfg_bool("crawler.refresh_known", True)
        self.resume_on_startup: bool = cfg_bool("crawler.resume_on_startup", True)
        self.progress: str = str(cfg_get("crawler.progress", default="auto")).strip().lower()
        sitemap_url = cfg_get("crawler.sitemap_url", default=None)
        self.sitemap_url: str | None = (
            str(sitemap_url).strip() if sitemap_url else None
        ) or None
        self.sitemap_only: bool = cfg_bool("crawler.sitemap_only", True)

    @property
    def data_dir(self) -> Path:
        return app_settings.data_dir


@dataclass(frozen=True)
class QueuedUrl:
    url: str
    depth: int


crawl_settings = CrawlSettings()
