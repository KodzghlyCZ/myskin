from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myskin.config import settings as app_settings
from myskin.formats import DEFAULT_PASSTHROUGH_EXTENSIONS, normalize_extension
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
        local_sitemap = cfg_get("crawler.local_sitemap", default=None)
        self.local_sitemap_path: Path | None = (
            Path(str(local_sitemap).strip()) if local_sitemap else None
        )
        requeue = str(cfg_get("crawler.local_sitemap_requeue", default="always")).strip().lower()
        self.local_sitemap_requeue_always: bool = requeue in {"always", "all", "true", "yes", "1"}
        self.sitemap_only: bool = cfg_bool("crawler.sitemap_only", True)
        self.follow_file_links: bool = cfg_bool("crawler.follow_file_links", True)
        self.html_to_markdown: bool = cfg_bool("crawler.html_to_markdown", True)
        self.passthrough_enabled: bool = cfg_bool("crawler.passthrough.enabled", True)
        self.passthrough_extensions: frozenset[str] = self._load_passthrough_extensions()
        self.extract_pdf_text: bool = cfg_bool("crawler.passthrough.extract_pdf_text", False)

    @staticmethod
    def _load_passthrough_extensions() -> frozenset[str]:
        raw = cfg_get("crawler.passthrough.extensions", default=None)
        if raw is None:
            return DEFAULT_PASSTHROUGH_EXTENSIONS
        if isinstance(raw, str):
            items = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(raw, (list, tuple)):
            items = [str(part).strip() for part in raw if str(part).strip()]
        else:
            return DEFAULT_PASSTHROUGH_EXTENSIONS
        normalized = {normalize_extension(item) for item in items}
        return frozenset(ext for ext in normalized if ext)

    @property
    def data_dir(self) -> Path:
        return app_settings.data_dir

    def should_passthrough(self, url: str, content_type: str = "") -> bool:
        if not self.passthrough_enabled:
            return False
        from myskin.formats import extension_from_content_type, is_passthrough_url

        if is_passthrough_url(url, self.passthrough_extensions):
            return True
        ext = extension_from_content_type(content_type)
        return bool(ext and ext in self.passthrough_extensions)


@dataclass(frozen=True)
class QueuedUrl:
    url: str
    depth: int


crawl_settings = CrawlSettings()
