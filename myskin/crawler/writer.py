from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from myskin.frontmatter import isoformat_dt, render_document


def parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def write_markdown(
    path: Path,
    *,
    title: str,
    body: str,
    source_url: str,
    category: str,
    content_hash: str,
    updated_at: datetime,
    author: str = "myskin-crawler",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = {
        "title": title,
        "author": author,
        "category": category,
        "source_url": source_url,
        "content_hash": content_hash,
        "updated_at": isoformat_dt(updated_at),
    }
    path.write_text(render_document(fields, body), encoding="utf-8")


def remove_file(data_dir: Path, relative_path: str) -> None:
    target = data_dir / relative_path
    if target.is_file():
        target.unlink()
