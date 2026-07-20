from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from myskin.config import settings
from myskin.settings_loader import cfg_get, cfg_optional, ensure_config_loaded
from myskin.sites.models import SiteRecord


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _slug_from_seed_url(seed_url: str) -> str:
    host = urlparse(seed_url).hostname or "default"
    return host.replace(".", "-")


def _json_load(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


class SiteRegistry:
    def __init__(self, db_path: Path | None = None) -> None:
        ensure_config_loaded()
        default = cfg_get("api.registry_db", default="./.myskin/sites.db")
        self.db_path = (db_path or Path(str(default))).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    site_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    public_base_url TEXT NOT NULL DEFAULT '',
                    crawler_json TEXT NOT NULL DEFAULT '{}',
                    scheduler_json TEXT NOT NULL DEFAULT '{}',
                    ragflow_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def list_sites(self, *, enabled_only: bool = False) -> list[SiteRecord]:
        query = "SELECT * FROM sites"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY site_id"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, site_id: str) -> SiteRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sites WHERE site_id = ?",
                (site_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def upsert(self, record: SiteRecord) -> SiteRecord:
        now = _utcnow()
        created = record.created_at or now
        updated = record.updated_at or now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sites (
                    site_id, name, enabled, public_base_url,
                    crawler_json, scheduler_json, ragflow_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled,
                    public_base_url = excluded.public_base_url,
                    crawler_json = excluded.crawler_json,
                    scheduler_json = excluded.scheduler_json,
                    ragflow_json = excluded.ragflow_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record.site_id,
                    record.name,
                    1 if record.enabled else 0,
                    record.public_base_url,
                    json.dumps(record.crawler, sort_keys=True),
                    json.dumps(record.scheduler, sort_keys=True),
                    json.dumps(record.ragflow, sort_keys=True),
                    _dt_iso(created),
                    _dt_iso(updated),
                ),
            )
        saved = self.get(record.site_id)
        assert saved is not None
        return saved

    def delete(self, site_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sites WHERE site_id = ?", (site_id,))
            return cursor.rowcount > 0

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM sites").fetchone()
        return int(row["n"]) if row else 0

    def sync_from_config(self) -> list[SiteRecord]:
        """Import sites from config.yaml (sites[] array or legacy single-site block)."""
        ensure_config_loaded()
        imported: list[SiteRecord] = []
        raw_sites = cfg_optional("sites")
        if isinstance(raw_sites, list) and raw_sites:
            for entry in raw_sites:
                if not isinstance(entry, dict):
                    continue
                site_id = str(entry.get("id") or entry.get("site_id") or "").strip()
                if not site_id:
                    continue
                imported.append(self._record_from_mapping(site_id, entry))
        elif self.count() == 0:
            seed = str(cfg_get("crawler.seed_url", default="")).strip()
            if seed:
                site_id = _slug_from_seed_url(seed)
                imported.append(self._legacy_site_record(site_id))

        saved: list[SiteRecord] = []
        for record in imported:
            existing = self.get(record.site_id)
            merged = SiteRecord(
                site_id=record.site_id,
                name=record.name,
                enabled=record.enabled,
                public_base_url=record.public_base_url,
                crawler=record.crawler,
                scheduler=record.scheduler,
                ragflow=record.ragflow,
                created_at=existing.created_at if existing else record.created_at,
                updated_at=_utcnow(),
            )
            saved.append(self.upsert(merged))
        return saved

    def _legacy_site_record(self, site_id: str) -> SiteRecord:
        crawler: dict[str, Any] = {}
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
                crawler[key] = value

        scheduler: dict[str, Any] = {}
        for key in (
            "enabled",
            "cron",
            "interval_hours",
            "interval_minutes",
            "run_on_startup",
            "timezone",
        ):
            value = cfg_optional(f"scheduler.{key}")
            if value is not None:
                scheduler[key] = value

        ragflow: dict[str, Any] = {}
        for key in (
            "enabled",
            "api_url",
            "dataset_id",
            "state_db",
            "sync_on_crawl_complete",
            "parse_on_upload",
            "delete_missing",
        ):
            value = cfg_optional(f"ragflow.{key}")
            if value is not None:
                ragflow[key] = value

        if "api_url" not in ragflow:
            global_url = cfg_optional("ragflow.api_url")
            if global_url:
                ragflow["api_url"] = global_url

        seed = str(crawler.get("seed_url", site_id)).strip()
        name = str(cfg_optional("site.name") or seed).strip()
        public_base_url = str(cfg_get("api.public_base_url", default="")).strip()

        return SiteRecord(
            site_id=site_id,
            name=name,
            enabled=True,
            public_base_url=public_base_url,
            crawler=crawler,
            scheduler=scheduler,
            ragflow=ragflow,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )

    def _record_from_mapping(self, site_id: str, entry: dict[str, Any]) -> SiteRecord:
        crawler = entry.get("crawler")
        scheduler = entry.get("scheduler")
        ragflow = entry.get("ragflow")
        if not isinstance(crawler, dict):
            crawler = {}
        if not isinstance(scheduler, dict):
            scheduler = {}
        if not isinstance(ragflow, dict):
            ragflow = {}

        global_ragflow_url = cfg_optional("ragflow.api_url")
        if global_ragflow_url and "api_url" not in ragflow:
            ragflow = {**ragflow, "api_url": global_ragflow_url}

        seed = str(crawler.get("seed_url", site_id)).strip()
        name = str(entry.get("name") or seed).strip()
        public_base_url = str(
            entry.get("public_base_url") or cfg_get("api.public_base_url", default="")
        ).strip()
        enabled = entry.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}

        return SiteRecord(
            site_id=site_id,
            name=name,
            enabled=bool(enabled),
            public_base_url=public_base_url,
            crawler=crawler,
            scheduler=scheduler,
            ragflow=ragflow,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> SiteRecord:
        return SiteRecord(
            site_id=row["site_id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            public_base_url=row["public_base_url"] or "",
            crawler=_json_load(row["crawler_json"]),
            scheduler=_json_load(row["scheduler_json"]),
            ragflow=_json_load(row["ragflow_json"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )
