from __future__ import annotations

from pathlib import Path

_CRAWL_STATIC_DIR = Path(__file__).resolve().parent / "static" / "crawl"


def crawl_static_dir() -> Path:
    return _CRAWL_STATIC_DIR


def load_dashboard_html() -> str:
    return (_CRAWL_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


def resolve_crawl_static_file(name: str) -> Path | None:
    """Return a file under static/crawl/ if it exists and stays within that directory."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    root = _CRAWL_STATIC_DIR.resolve()
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None
