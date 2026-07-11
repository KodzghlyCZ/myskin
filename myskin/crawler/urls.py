from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

_UNSAFE_PATH = re.compile(r"[^a-zA-Z0-9._-]+")
_ROOT_INDEX_ALIASES = frozenset(
    {
        "/index",
        "/index.html",
        "/index.htm",
        "/index.php",
        "/index.asp",
        "/index.aspx",
        "/default.html",
        "/default.htm",
        "/home",
        "/home.html",
    }
)


@dataclass(frozen=True)
class ParsedUrl:
    normalized: str
    host: str
    path: str


def normalize_url(url: str, base: str | None = None) -> ParsedUrl | None:
    raw = (url or "").strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None

    joined = urljoin(base, raw) if base else raw
    parsed = urlparse(joined)
    if parsed.scheme not in ("http", "https"):
        return None

    host = parsed.hostname
    if not host:
        return None

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    path = _canonical_path(path)

    normalized = urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))
    return ParsedUrl(normalized=normalized, host=host.lower(), path=path)


def _canonical_path(path: str) -> str:
    if path.lower() in _ROOT_INDEX_ALIASES:
        return "/"
    return path


def is_pdf_url(url: str) -> bool:
    return _path_extension(urlparse(url).path) == ".pdf"


def is_css_url(url: str) -> bool:
    """True when the URL path ends in .css (query string ignored)."""
    return _path_extension(urlparse(url).path) == ".css"


def _path_extension(path: str) -> str:
    return Path(path).suffix.lower()


def is_in_scope(url: ParsedUrl, seed: ParsedUrl) -> bool:
    if url.host != seed.host:
        return False
    if seed.path in ("", "/"):
        return True
    return url.path == seed.path or url.path.startswith(seed.path.rstrip("/") + "/")


def slugify_segment(segment: str) -> str:
    segment = segment.strip().lower()
    segment = _UNSAFE_PATH.sub("-", segment)
    return segment.strip("-") or "index"


def url_to_relative_path(url: ParsedUrl, *, resource_type: str) -> str:
    """Map a URL to a stable path under crawl/<host>/pages|pdfs/."""
    host_slug = slugify_segment(url.host.replace(".", "-"))
    parts = [p for p in url.path.split("/") if p]
    if not parts:
        parts = ["index"]

    if resource_type == "pdf" and parts[-1].lower().endswith(".pdf"):
        stem = parts[-1][:-4]
        parts = parts[:-1] + [stem]

    safe_parts = [slugify_segment(p) for p in parts]
    if resource_type == "pdf":
        filename = f"{safe_parts[-1]}.md"
        dir_parts = safe_parts[:-1]
        rel = Path("crawl") / host_slug / "pdfs" / Path(*dir_parts) / filename
    elif len(safe_parts) == 1:
        rel = Path("crawl") / host_slug / "pages" / f"{safe_parts[0]}.md"
    else:
        rel = Path("crawl") / host_slug / "pages" / Path(*safe_parts[:-1]) / f"{safe_parts[-1]}.md"

    return rel.as_posix()


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
