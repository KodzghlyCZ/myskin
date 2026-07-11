from __future__ import annotations

import re
from datetime import datetime

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip().strip("\"'")

    return meta, text[match.end() :]


def format_frontmatter(fields: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if not value:
            continue
        safe = value.replace("\n", " ").strip()
        if ":" in safe or safe.startswith("#"):
            safe = f'"{safe}"'
        lines.append(f"{key}: {safe}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def render_document(fields: dict[str, str], body: str) -> str:
    return format_frontmatter(fields) + body.strip() + "\n"


def isoformat_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=None).isoformat() + "Z"
    return dt.astimezone().replace(microsecond=0).isoformat().replace("+00:00", "Z")
