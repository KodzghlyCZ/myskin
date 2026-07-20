from __future__ import annotations

from pathlib import Path

from myskin.config import settings
from myskin.crawler.config import CrawlSettings
from myskin.scheduler_config import SchedulerSettings
from myskin.sites.models import SiteRecord
from myskin.sites.registry import SiteRegistry
from myskin.ragflow_sync import RagflowSettings


class SiteService:
    def __init__(self, registry: SiteRegistry | None = None) -> None:
        self.registry = registry or SiteRegistry()

    def bootstrap(self) -> list[SiteRecord]:
        return self.registry.sync_from_config()

    def list_sites(self, *, enabled_only: bool = False) -> list[SiteRecord]:
        return self.registry.list_sites(enabled_only=enabled_only)

    def get_site(self, site_id: str) -> SiteRecord | None:
        return self.registry.get(site_id)

    def require_site(self, site_id: str) -> SiteRecord:
        site = self.get_site(site_id)
        if site is None:
            raise KeyError(f"Unknown site: {site_id}")
        return site

    def upsert_site(self, record: SiteRecord) -> SiteRecord:
        return self.registry.upsert(record)

    def delete_site(self, site_id: str) -> bool:
        return self.registry.delete(site_id)

    def myskin_root(self) -> Path:
        return self.registry.db_path.parent

    def data_dir_for(self, site: SiteRecord) -> Path:
        override = site.crawler.get("data_dir")
        if override:
            return Path(str(override))
        legacy_root = settings.data_dir.resolve()
        if self._uses_legacy_layout(site, legacy_root):
            return legacy_root
        return legacy_root / "sites" / site.site_id

    def state_db_for(self, site: SiteRecord) -> Path:
        override = site.crawler.get("state_db")
        if override:
            return Path(str(override))
        return self.myskin_root() / "sites" / site.site_id / "crawl.db"

    def ragflow_state_db_for(self, site: SiteRecord) -> Path:
        override = site.ragflow.get("state_db")
        if override:
            return Path(str(override))
        return self.myskin_root() / "sites" / site.site_id / "ragflow_sync.db"

    def crawl_settings_for(self, site: SiteRecord) -> CrawlSettings:
        return CrawlSettings.from_mapping(
            site.crawler,
            data_dir=self.data_dir_for(site),
            state_db=self.state_db_for(site),
        )

    def scheduler_settings_for(self, site: SiteRecord) -> SchedulerSettings:
        return SchedulerSettings.from_mapping(site.scheduler)

    def ragflow_settings_for(self, site: SiteRecord) -> RagflowSettings:
        return RagflowSettings.from_mapping(
            site.ragflow,
            state_db=self.ragflow_state_db_for(site),
            site_id=site.site_id,
        )

    def file_url_for(self, site: SiteRecord, doc_id: str) -> str | None:
        base = site.public_base_url.rstrip("/")
        if not base:
            return None
        return f"{base}/api/sites/{site.site_id}/files/{doc_id}"

    @staticmethod
    def _uses_legacy_layout(site: SiteRecord, legacy_root: Path) -> bool:
        if site.crawler.get("data_dir") or site.crawler.get("state_db"):
            return True
        if not legacy_root.is_dir():
            return False
        crawl_dir = legacy_root / "crawl"
        return crawl_dir.is_dir()

    def default_site(self) -> SiteRecord | None:
        sites = self.list_sites()
        if not sites:
            return None
        if len(sites) == 1:
            return sites[0]
        for site in sites:
            if site.enabled:
                return site
        return sites[0]


site_service = SiteService()
