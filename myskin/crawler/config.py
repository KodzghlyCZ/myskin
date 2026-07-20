from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from myskin.config import settings as app_settings
from myskin.formats import DEFAULT_PASSTHROUGH_EXTENSIONS, normalize_extension
from myskin.settings_loader import cfg_bool, cfg_get, cfg_optional, cfg_path, ensure_config_loaded


def _mapping_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _mapping_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    if key not in data or data[key] is None or data[key] == "":
        return default
    return data[key]


class CrawlSettings:
    def __init__(
        self,
        *,
        seed_url: str,
        max_depth: int,
        max_pages: int,
        request_delay: float,
        user_agent: str,
        respect_robots: bool,
        state_db: Path,
        refresh_known: bool,
        resume_on_startup: bool,
        progress: str,
        sitemap_url: str | None,
        local_sitemap_path: Path | None,
        local_sitemap_requeue_always: bool,
        sitemap_only: bool,
        follow_file_links: bool,
        html_to_markdown: bool,
        passthrough_enabled: bool,
        passthrough_extensions: frozenset[str],
        extract_pdf_text: bool,
        data_dir: Path,
    ) -> None:
        self.seed_url = seed_url
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.state_db = state_db
        self.refresh_known = refresh_known
        self.resume_on_startup = resume_on_startup
        self.progress = progress
        self.sitemap_url = sitemap_url
        self.local_sitemap_path = local_sitemap_path
        self.local_sitemap_requeue_always = local_sitemap_requeue_always
        self.sitemap_only = sitemap_only
        self.follow_file_links = follow_file_links
        self.html_to_markdown = html_to_markdown
        self.passthrough_enabled = passthrough_enabled
        self.passthrough_extensions = passthrough_extensions
        self.extract_pdf_text = extract_pdf_text
        self._data_dir = data_dir

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any],
        *,
        data_dir: Path | None = None,
        state_db: Path | None = None,
    ) -> CrawlSettings:
        passthrough = data.get("passthrough")
        if not isinstance(passthrough, dict):
            passthrough = {}

        sitemap_url = _mapping_get(data, "sitemap_url")
        local_sitemap = _mapping_get(data, "local_sitemap")
        requeue = str(_mapping_get(data, "local_sitemap_requeue", "always")).strip().lower()

        resolved_data_dir = data_dir
        if resolved_data_dir is None:
            override = _mapping_get(data, "data_dir")
            resolved_data_dir = Path(str(override)) if override else app_settings.data_dir

        resolved_state_db = state_db
        if resolved_state_db is None:
            override = _mapping_get(data, "state_db")
            resolved_state_db = (
                Path(str(override)) if override else Path("./.myskin/crawl.db")
            )

        return cls(
            seed_url=str(_mapping_get(data, "seed_url", default="https://example.com/")),
            max_depth=int(_mapping_get(data, "max_depth", 3)),
            max_pages=int(_mapping_get(data, "max_pages", 1000)),
            request_delay=float(_mapping_get(data, "request_delay", 2.5)),
            user_agent=str(
                _mapping_get(
                    data,
                    "user_agent",
                    default="MyskinCrawler/1.0 (+https://github.com/KodzghlyCZ/myskin)",
                )
            ),
            respect_robots=_mapping_bool(data, "respect_robots", True),
            state_db=resolved_state_db,
            refresh_known=_mapping_bool(data, "refresh_known", True),
            resume_on_startup=_mapping_bool(data, "resume_on_startup", True),
            progress=str(_mapping_get(data, "progress", "auto")).strip().lower(),
            sitemap_url=str(sitemap_url).strip() if sitemap_url else None,
            local_sitemap_path=Path(str(local_sitemap).strip()) if local_sitemap else None,
            local_sitemap_requeue_always=requeue in {"always", "all", "true", "yes", "1"},
            sitemap_only=_mapping_bool(data, "sitemap_only", True),
            follow_file_links=_mapping_bool(data, "follow_file_links", True),
            html_to_markdown=_mapping_bool(data, "html_to_markdown", True),
            passthrough_enabled=_mapping_bool(passthrough, "enabled", True),
            passthrough_extensions=cls._extensions_from_value(
                passthrough.get("extensions")
            ),
            extract_pdf_text=_mapping_bool(passthrough, "extract_pdf_text", False),
            data_dir=resolved_data_dir,
        )

    @classmethod
    def load_global(cls) -> CrawlSettings:
        ensure_config_loaded()
        mapping: dict[str, Any] = {}
        for key in (
            "seed_url",
            "max_depth",
            "max_pages",
            "request_delay",
            "user_agent",
            "respect_robots",
            "state_db",
            "refresh_known",
            "resume_on_startup",
            "sitemap_url",
            "local_sitemap",
            "local_sitemap_requeue",
            "sitemap_only",
            "follow_file_links",
            "progress",
            "html_to_markdown",
            "passthrough",
        ):
            value = cfg_optional(f"crawler.{key}")
            if value is not None:
                mapping[key] = value
        return cls.from_mapping(
            mapping,
            data_dir=app_settings.data_dir,
            state_db=cfg_path("crawler.state_db", "./.myskin/crawl.db"),
        )

    @staticmethod
    def _extensions_from_value(raw: Any) -> frozenset[str]:
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
        return self._data_dir

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


crawl_settings = CrawlSettings.load_global()
