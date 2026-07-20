from __future__ import annotations

from pathlib import Path

_ADMIN_STATIC_DIR = Path(__file__).resolve().parent / "static" / "admin"


def load_admin_html() -> str:
    return (_ADMIN_STATIC_DIR / "admin.html").read_text(encoding="utf-8")


def resolve_admin_static_file(name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    root = _ADMIN_STATIC_DIR.resolve()
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None
