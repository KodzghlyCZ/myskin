from __future__ import annotations

import mimetypes
from pathlib import Path

# Extensions RAGFlow can parse natively (see ragflow.io dataset docs).
DEFAULT_PASSTHROUGH_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".csv",
        ".json",
        ".eml",
        ".txt",
        ".text",
    }
)

TEXT_CATALOG_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown"})

BINARY_CATALOG_SUFFIXES: frozenset[str] = DEFAULT_PASSTHROUGH_EXTENSIONS - {".txt", ".text"}

CATALOG_SUFFIXES = TEXT_CATALOG_SUFFIXES | BINARY_CATALOG_SUFFIXES | frozenset({".txt", ".text"})

_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/csv": ".csv",
    "application/json": ".json",
    "message/rfc822": ".eml",
    "text/plain": ".txt",
}


def normalize_extension(ext: str) -> str:
    value = (ext or "").strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def extension_from_url(url: str) -> str:
    return normalize_extension(Path(urlparse_path(url)).suffix)


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path or "/"


def extension_from_content_type(content_type: str) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXTENSIONS.get(ct, "")


def is_passthrough_extension(ext: str, allowed: frozenset[str]) -> bool:
    return normalize_extension(ext) in allowed


def is_passthrough_url(url: str, allowed: frozenset[str]) -> bool:
    return is_passthrough_extension(extension_from_url(url), allowed)


def guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def format_label(ext: str) -> str:
    return normalize_extension(ext).lstrip(".") or "unknown"


def infer_resource_kind(url: str) -> str:
    ext = extension_from_url(url)
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT_CATALOG_SUFFIXES:
        return "page"
    if ext in BINARY_CATALOG_SUFFIXES:
        return "file"
    if ext:
        return "file"
    return "page"
