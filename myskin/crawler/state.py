from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ResourceRecord:
    url: str
    resource_type: str
    local_path: str
    content_hash: str
    title: str
    etag: str | None
    last_modified: str | None
    last_crawled_at: datetime
    last_changed_at: datetime
    http_status: int


@dataclass
class CrawlStats:
    pages_fetched: int = 0
    pdfs_fetched: int = 0
    pages_updated: int = 0
    pdfs_updated: int = 0
    pages_unchanged: int = 0
    pdfs_unchanged: int = 0
    pages_failed: int = 0
    pdfs_failed: int = 0
    discovered: int = 0
    sitemap_urls: int = 0
    sitemap_queued: int = 0
    sitemap_skipped: int = 0


class CrawlState:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    url TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    etag TEXT,
                    last_modified TEXT,
                    last_crawled_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL,
                    http_status INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS crawl_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    seed_url TEXT NOT NULL,
                    pages_fetched INTEGER DEFAULT 0,
                    pdfs_fetched INTEGER DEFAULT 0,
                    pages_updated INTEGER DEFAULT 0,
                    pdfs_updated INTEGER DEFAULT 0,
                    pages_unchanged INTEGER DEFAULT 0,
                    pdfs_unchanged INTEGER DEFAULT 0,
                    pages_failed INTEGER DEFAULT 0,
                    pdfs_failed INTEGER DEFAULT 0,
                    discovered INTEGER DEFAULT 0
                );
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

    def get_resource(self, url: str) -> ResourceRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resources WHERE url = ?", (url,)).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def get_resource_by_local_path(self, local_path: str) -> ResourceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM resources WHERE local_path = ? LIMIT 1",
                (local_path,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def list_resources(self, resource_type: str | None = None) -> list[ResourceRecord]:
        with self._connect() as conn:
            if resource_type:
                rows = conn.execute(
                    "SELECT * FROM resources WHERE resource_type = ? ORDER BY url",
                    (resource_type,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM resources ORDER BY url").fetchall()
        return [self._row_to_record(r) for r in rows]

    def upsert_resource(self, record: ResourceRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resources (
                    url, resource_type, local_path, content_hash, title,
                    etag, last_modified, last_crawled_at, last_changed_at, http_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    resource_type = excluded.resource_type,
                    local_path = excluded.local_path,
                    content_hash = excluded.content_hash,
                    title = excluded.title,
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    last_crawled_at = excluded.last_crawled_at,
                    last_changed_at = excluded.last_changed_at,
                    http_status = excluded.http_status
                """,
                (
                    record.url,
                    record.resource_type,
                    record.local_path,
                    record.content_hash,
                    record.title,
                    record.etag,
                    record.last_modified,
                    _dt_iso(record.last_crawled_at),
                    _dt_iso(record.last_changed_at),
                    record.http_status,
                ),
            )

    def delete_resource(self, url: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT local_path FROM resources WHERE url = ?", (url,)
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM resources WHERE url = ?", (url,))
            return row["local_path"]

    def start_run(self, seed_url: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO crawl_runs (started_at, seed_url) VALUES (?, ?)",
                (_dt_iso(_utcnow()), seed_url),
            )
            return int(cur.lastrowid)

    def abort_unfinished_runs(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM crawl_runs WHERE finished_at IS NULL ORDER BY id"
            ).fetchall()
            run_ids = [int(row["id"]) for row in rows]
            if not run_ids:
                return []

            now = _dt_iso(_utcnow())
            conn.execute(
                "UPDATE crawl_runs SET finished_at = ? WHERE finished_at IS NULL",
                (now,),
            )
            return run_ids

    def finish_run(self, run_id: int, stats: CrawlStats) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE crawl_runs SET
                    finished_at = ?,
                    pages_fetched = ?,
                    pdfs_fetched = ?,
                    pages_updated = ?,
                    pdfs_updated = ?,
                    pages_unchanged = ?,
                    pdfs_unchanged = ?,
                    pages_failed = ?,
                    pdfs_failed = ?,
                    discovered = ?
                WHERE id = ?
                """,
                (
                    _dt_iso(_utcnow()),
                    stats.pages_fetched,
                    stats.pdfs_fetched,
                    stats.pages_updated,
                    stats.pdfs_updated,
                    stats.pages_unchanged,
                    stats.pdfs_unchanged,
                    stats.pages_failed,
                    stats.pdfs_failed,
                    stats.discovered,
                    run_id,
                ),
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ResourceRecord:
        return ResourceRecord(
            url=row["url"],
            resource_type=row["resource_type"],
            local_path=row["local_path"],
            content_hash=row["content_hash"],
            title=row["title"] or "",
            etag=row["etag"],
            last_modified=row["last_modified"],
            last_crawled_at=_parse_dt(row["last_crawled_at"]),
            last_changed_at=_parse_dt(row["last_changed_at"]),
            http_status=int(row["http_status"] or 0),
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
