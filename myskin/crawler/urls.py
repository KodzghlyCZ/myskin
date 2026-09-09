from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from myskin.formats import extension_from_url, normalize_extension

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
    return extension_from_url(url) == ".pdf"


def is_css_url(url: str) -> bool:
    """True when the URL path ends in .css (query string ignored)."""
    return extension_from_url(url) == ".css"


def is_passthrough_url(url: str, allowed_extensions: frozenset[str]) -> bool:
    return normalize_extension(extension_from_url(url)) in allowed_extensions


def url_to_relative_path(
    url: ParsedUrl,
    *,
    resource_type: str,
    extension: str | None = None,
) -> str:
    """Map a URL to a stable path under crawl/<host>/pages|files/."""
    host_slug = slugify_segment(url.host.replace(".", "-"))
    parts = [p for p in url.path.split("/") if p]
    if not parts:
        parts = ["index"]

    safe_parts = [slugify_segment(p) for p in parts]

    if resource_type == "file":
        ext = normalize_extension(extension or extension_from_url(url.normalized) or ".bin")
        filename = safe_parts[-1]
        if filename.lower().endswith(ext):
            filename = filename[: -len(ext)]
        filename = f"{filename}{ext}"
        dir_parts = safe_parts[:-1]
        rel = Path("crawl") / host_slug / "files" / Path(*dir_parts) / filename
        return rel.as_posix()

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


def same_host(url: ParsedUrl, seed: ParsedUrl) -> bool:
    return url.host == seed.host


def is_in_scope(
    url: ParsedUrl,
    seed: ParsedUrl,
    url_pattern: re.Pattern[str] | None = None,
) -> bool:
    """True when `url` may be crawled for this seed.

    Always requires the same host. Seed path is a prefix filter when it is
    not `/`. Optional `url_pattern` further restricts pages (matched against
    the normalized URL, then the path) so a prefix like `^/docs/` or
    `^https://example.com/docs/` both work.
    """
    if not same_host(url, seed):
        return False
    if seed.path not in ("", "/"):
        prefix = seed.path.rstrip("/") + "/"
        if url.path != seed.path and not url.path.startswith(prefix):
            return False
    if url_pattern is None:
        return True
    if url_pattern.search(url.normalized):
        return True
    return url_pattern.search(url.path) is not None


def slugify_segment(segment: str) -> str:
    segment = segment.strip().lower()
    segment = _UNSAFE_PATH.sub("-", segment)
    return segment.strip("-") or "index"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
