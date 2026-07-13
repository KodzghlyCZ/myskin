from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from myskin.config import settings
from myskin.formats import (
    BINARY_CATALOG_SUFFIXES,
    CATALOG_SUFFIXES,
    TEXT_CATALOG_SUFFIXES,
    format_label,
    guess_mime_type,
)
from myskin.frontmatter import parse_frontmatter
from myskin.models import DocumentItem

_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_META_SUFFIX = ".meta.yaml"


@dataclass(frozen=True)
class RawDocument:
    relative_path: str
    title: str
    updated_at: datetime
    author: str
    category: str
    format: str
    filename: str
    mime_type: str

    @property
    def id(self) -> str:
        return self.relative_path.replace("/", "--").replace(" ", "-")


def _title_from_body(body: str, fallback: str) -> str:
    heading = _HEADING_RE.search(body)
    if heading:
        return heading.group(1).strip()
    first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return first_line[:120] if first_line else fallback


def _read_sidecar(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    meta, _ = parse_frontmatter(text)
    return meta


def _parse_updated_at(meta: dict[str, str], path: Path) -> datetime:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    updated_raw = meta.get("updated_at")
    if updated_raw:
        try:
            mtime = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
            if mtime.tzinfo is None:
                mtime = mtime.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return mtime


def _read_text_document(path: Path, root: Path) -> RawDocument | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    relative = path.relative_to(root).as_posix()
    stem = path.stem.replace("-", " ").replace("_", " ").title()
    meta, body = parse_frontmatter(text)
    ext = path.suffix.lower()

    return RawDocument(
        relative_path=relative,
        title=meta.get("title") or _title_from_body(body, stem),
        updated_at=_parse_updated_at(meta, path),
        author=meta.get("author", "myskin"),
        category=meta.get("category", "general"),
        format=meta.get("format") or format_label(ext),
        filename=path.name,
        mime_type="text/markdown" if ext in TEXT_CATALOG_SUFFIXES else "text/plain",
    )


def _read_binary_document(path: Path, root: Path) -> RawDocument | None:
    relative = path.relative_to(root).as_posix()
    sidecar = path.with_suffix(path.suffix + ".meta.yaml")
    meta = _read_sidecar(sidecar)
    stem = path.stem.replace("-", " ").replace("_", " ").title()
    ext = path.suffix.lower()

    return RawDocument(
        relative_path=relative,
        title=meta.get("title") or stem,
        updated_at=_parse_updated_at(meta, path),
        author=meta.get("author", "myskin"),
        category=meta.get("category", format_label(ext)),
        format=meta.get("format") or format_label(ext),
        filename=path.name,
        mime_type=guess_mime_type(path),
    )


def file_url_for(doc_id: str) -> str | None:
    base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else ""
    if not base_url:
        return None
    return f"{base_url}/api/files/{doc_id}"


def resolve_document_path(doc_id: str, data_dir: Path | None = None) -> Path | None:
    root = (data_dir or settings.data_dir).resolve()
    if not root.is_dir():
        return None
    target = doc_id.replace("--", "/").replace(" ", "-")
    path = (root / target).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if path.is_file() and path.suffix.lower() in CATALOG_SUFFIXES:
        return path
    return None


def scan_documents(data_dir: Path | None = None) -> list[DocumentItem]:
    """Walk the data directory and build the catalog (metadata + file URLs)."""
    root = (data_dir or settings.data_dir).resolve()
    if not root.is_dir():
        return []

    docs: list[RawDocument] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.name.endswith(_META_SUFFIX):
            continue

        suffix = path.suffix.lower()
        if suffix not in CATALOG_SUFFIXES:
            continue

        if suffix in TEXT_CATALOG_SUFFIXES or suffix in {".txt", ".text"}:
            raw = _read_text_document(path, root)
        elif suffix in BINARY_CATALOG_SUFFIXES:
            raw = _read_binary_document(path, root)
        else:
            continue

        if raw is not None:
            docs.append(raw)

    docs.sort(key=lambda d: d.id)
    return [
        DocumentItem(
            id=d.id,
            title=d.title,
            updated_at=d.updated_at,
            author=d.author,
            category=d.category,
            format=d.format,
            filename=d.filename,
            mime_type=d.mime_type,
            file_url=file_url_for(d.id),
        )
        for d in docs
    ]


def catalog_stats(documents: list[DocumentItem] | None = None) -> dict[str, dict[str, int]]:
    items = documents if documents is not None else scan_documents()
    by_format: dict[str, int] = {}
    with_url = 0
    for doc in items:
        by_format[doc.format] = by_format.get(doc.format, 0) + 1
        if doc.file_url:
            with_url += 1
    return {"by_format": by_format, "with_file_url": with_url}


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
