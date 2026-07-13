from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class RagflowSyncRecord:
    myskin_id: str
    ragflow_document_id: str
    content_hash: str
    updated_at: datetime
    synced_at: datetime


def _dt_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _parse_dt(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


class RagflowSyncState:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ragflow_sync (
                    myskin_id TEXT PRIMARY KEY,
                    ragflow_document_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    synced_at TEXT NOT NULL
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

    def list_records(self) -> dict[str, RagflowSyncRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM ragflow_sync").fetchall()
        return {row["myskin_id"]: self._row_to_record(row) for row in rows}

    def get(self, myskin_id: str) -> RagflowSyncRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ragflow_sync WHERE myskin_id = ?", (myskin_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def upsert(self, record: RagflowSyncRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ragflow_sync (
                    myskin_id, ragflow_document_id, content_hash, updated_at, synced_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(myskin_id) DO UPDATE SET
                    ragflow_document_id = excluded.ragflow_document_id,
                    content_hash = excluded.content_hash,
                    updated_at = excluded.updated_at,
                    synced_at = excluded.synced_at
                """,
                (
                    record.myskin_id,
                    record.ragflow_document_id,
                    record.content_hash,
                    _dt_iso(record.updated_at),
                    _dt_iso(record.synced_at),
                ),
            )

    def delete(self, myskin_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ragflow_document_id FROM ragflow_sync WHERE myskin_id = ?",
                (myskin_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM ragflow_sync WHERE myskin_id = ?", (myskin_id,))
            return row["ragflow_document_id"]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> RagflowSyncRecord:
        return RagflowSyncRecord(
            myskin_id=row["myskin_id"],
            ragflow_document_id=row["ragflow_document_id"],
            content_hash=row["content_hash"],
            updated_at=_parse_dt(row["updated_at"]),
            synced_at=_parse_dt(row["synced_at"]),
        )
