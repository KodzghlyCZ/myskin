from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from myskin.config import settings
from myskin.frontmatter import parse_frontmatter
from myskin.models import DocumentItem

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".text"}
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class RawDocument:
    relative_path: str
    title: str
    body: str
    updated_at: datetime
    author: str
    category: str

    @property
    def id(self) -> str:
        return self.relative_path.replace("/", "--").replace(" ", "-")


def _title_from_body(body: str, fallback: str) -> str:
    heading = _HEADING_RE.search(body)
    if heading:
        return heading.group(1).strip()
    first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return first_line[:120] if first_line else fallback


def _read_file(path: Path, root: Path) -> RawDocument | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    relative = path.relative_to(root).as_posix()
    stem = path.stem.replace("-", " ").replace("_", " ").title()
    meta, body = parse_frontmatter(text)
    body = body.strip()

    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    updated_raw = meta.get("updated_at")
    if updated_raw:
        try:
            mtime = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
            if mtime.tzinfo is None:
                mtime = mtime.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return RawDocument(
        relative_path=relative,
        title=meta.get("title") or _title_from_body(body, stem),
        body=body,
        updated_at=mtime,
        author=meta.get("author", "myskin"),
        category=meta.get("category", "general"),
    )


def scan_documents(data_dir: Path | None = None) -> list[DocumentItem]:
    """Walk the data directory and build the current document catalog."""
    root = (data_dir or settings.data_dir).resolve()
    if not root.is_dir():
        return []

    docs: list[RawDocument] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.name.startswith("."):
            continue
        raw = _read_file(path, root)
        if raw is not None:
            docs.append(raw)

    docs.sort(key=lambda d: d.id)
    return [
        DocumentItem(
            id=d.id,
            title=d.title,
            body=d.body,
            updated_at=d.updated_at,
            author=d.author,
            category=d.category,
        )
        for d in docs
    ]


def paginate(
    documents: list[DocumentItem],
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[DocumentItem], int]:
    total = len(documents)
    if offset < 0:
        offset = 0
    if limit < 1:
        limit = 50
    return documents[offset : offset + limit], total
